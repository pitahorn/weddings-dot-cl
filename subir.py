"""
Sube las fotos de cada proveedor a Cloudflare R2 en segundo plano, con una sola conexión.

Lee las credenciales de .env (no se sube a git; ver .env.example). Cada proveedor que termina
de subir queda anotado en cache/r2.txt, que es lo que scraper.armar usa para apuntar a R2.
Si lo ya subido pasa de 8 GB, se detiene antes de subir más.
"""
import datetime
import hashlib
import hmac
import http.client
import queue
import threading
import urllib.parse

import scraper

CACHE_DE_UN_ANO = "public, max-age=31536000, immutable"
LIMITE_BYTES = 8 * 1024**3  # R2 gratis llega a 10 GB; paramos antes
REINTENTOS = 3


def credenciales():
    lineas = (scraper.RAIZ / ".env").read_text("utf-8").splitlines()
    return dict(l.split("=", 1) for l in lineas if "=" in l and not l.startswith("#"))


def firmar(env, metodo, clave, cuerpo=b"", extra=None):
    """Ruta y cabeceras de un pedido S3 firmado con SigV4, como lo pide R2."""
    host = f"{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
    ruta = "/" + urllib.parse.quote(f"{env['R2_BUCKET']}/{clave}")
    ahora = datetime.datetime.now(datetime.timezone.utc)
    fecha, momento = ahora.strftime("%Y%m%d"), ahora.strftime("%Y%m%dT%H%M%SZ")
    cabeceras = {"host": host, "x-amz-content-sha256": hashlib.sha256(cuerpo).hexdigest(), "x-amz-date": momento, **(extra or {})}
    nombres = ";".join(sorted(cabeceras))
    canonico = "\n".join([metodo, ruta, "", *[f"{k}:{cabeceras[k]}" for k in sorted(cabeceras)], "", nombres, cabeceras["x-amz-content-sha256"]])
    alcance = f"{fecha}/auto/s3/aws4_request"
    a_firmar = "\n".join(["AWS4-HMAC-SHA256", momento, alcance, hashlib.sha256(canonico.encode()).hexdigest()])
    llave = ("AWS4" + env["R2_SECRET_ACCESS_KEY"]).encode()
    for parte in (fecha, "auto", "s3", "aws4_request"):
        llave = hmac.new(llave, parte.encode(), hashlib.sha256).digest()
    firma = hmac.new(llave, a_firmar.encode(), hashlib.sha256).hexdigest()
    cabeceras["authorization"] = f"AWS4-HMAC-SHA256 Credential={env['R2_ACCESS_KEY_ID']}/{alcance}, SignedHeaders={nombres}, Signature={firma}"
    return ruta, cabeceras


class Subidor:
    """Recibe proveedores (cat, id, [(nombre, bytes)]) y los sube mientras el scraper espera al archivo."""

    def __init__(self):
        self.env = credenciales()
        self.host = f"{self.env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
        self.total = sum(scraper.en_r2().values())
        self.cola = queue.Queue()
        self.conexion = None
        self.error = None
        threading.Thread(target=self._trabajar, daemon=True).start()

    def proveedor(self, cat, id_proveedor, archivos):
        if self.error:
            scraper.alerta(f"la subida a R2 falló: {self.error}")
        self.total += sum(len(b) for _, b in archivos)
        if self.total > LIMITE_BYTES:
            scraper.alerta(f"R2 llegaría a {self.total / 1024**3:.1f} GB, sobre el límite de {LIMITE_BYTES / 1024**3:.0f} GB")
        self.cola.put((cat, id_proveedor, archivos))

    def esperar(self):
        self.cola.join()
        if self.error:
            scraper.alerta(f"la subida a R2 falló: {self.error}")

    def _trabajar(self):
        while True:
            cat, id_proveedor, archivos = self.cola.get()
            try:
                if not self.error:
                    for nombre, cuerpo in archivos:
                        self._poner(f"{cat}/{id_proveedor}/{nombre}", cuerpo)
                    with scraper.MANIFIESTO_R2.open("a") as f:
                        f.write(f"{cat}/{id_proveedor} {sum(len(b) for _, b in archivos)}\n")
            except Exception as e:
                self.error = e
            finally:
                self.cola.task_done()

    def _poner(self, clave, cuerpo):
        extra = {"content-type": "image/webp", "cache-control": CACHE_DE_UN_ANO}
        for intento in range(REINTENTOS):
            try:
                self.conexion = self.conexion or http.client.HTTPSConnection(self.host, timeout=60)
                ruta, cabeceras = firmar(self.env, "PUT", clave, cuerpo, extra)
                self.conexion.request("PUT", ruta, cuerpo, cabeceras)
                respuesta = self.conexion.getresponse()
                respuesta.read()
                if respuesta.status < 300:
                    return
                raise OSError(f"R2 respondió {respuesta.status} para {clave}")
            except (OSError, http.client.HTTPException):
                self.conexion.close()
                self.conexion = None
                if intento == REINTENTOS - 1:
                    raise
