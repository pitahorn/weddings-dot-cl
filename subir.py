#!/usr/bin/env python3
"""
Sube fotos/<categoria>/ a Cloudflare R2, con la misma ruta como clave.

Uso:
    python3 subir.py trajes-novio

Lee las credenciales de .env (no se sube a git; ver .env.example). Retoma: lo que ya está en
el bucket con el mismo tamaño no se vuelve a subir. El bucket solo recibe lo que hay en fotos/,
así que si fotos/ pasa de 8 GB no sube nada.
"""
import datetime
import hashlib
import hmac
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).parent
FOTOS = RAIZ / "fotos"
CACHE_DE_UN_ANO = "public, max-age=31536000, immutable"
LIMITE_BYTES = 8 * 1024**3  # R2 gratis llega a 10 GB; paramos antes


def credenciales():
    lineas = (RAIZ / ".env").read_text("utf-8").splitlines()
    return dict(l.split("=", 1) for l in lineas if "=" in l and not l.startswith("#"))


def firmar(env, metodo, clave, cuerpo=b"", extra=None):
    """Request de S3 firmado con SigV4, como lo pide R2."""
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
    return urllib.request.Request(f"https://{host}{ruta}", data=cuerpo or None, method=metodo, headers=cabeceras)


def tamano_remoto(env, clave):
    try:
        with urllib.request.urlopen(firmar(env, "HEAD", clave), timeout=30) as r:
            return int(r.headers.get("Content-Length", -1))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def subir(env, archivo):
    clave = archivo.relative_to(FOTOS).as_posix()
    cuerpo = archivo.read_bytes()
    if tamano_remoto(env, clave) == len(cuerpo):
        return False
    extra = {"content-type": "image/webp", "cache-control": CACHE_DE_UN_ANO}
    with urllib.request.urlopen(firmar(env, "PUT", clave, cuerpo, extra), timeout=60):
        return True


if __name__ == "__main__":
    total = sum(a.stat().st_size for a in FOTOS.rglob("*.webp"))
    if total > LIMITE_BYTES:
        sys.exit(f"ALERTA: fotos/ pesa {total / 1024**3:.1f} GB, sobre el límite de {LIMITE_BYTES / 1024**3:.0f} GB. No subo nada.")
    env = credenciales()
    for categoria in sys.argv[1:]:
        archivos = sorted((FOTOS / categoria).rglob("*.webp"))
        nuevas = sum(subir(env, a) for a in archivos)
        print(f"{categoria}: {nuevas} subidas, {len(archivos) - nuevas} ya estaban", flush=True)
