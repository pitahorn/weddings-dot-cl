"""
Baja las fotos que el archivo guardó de un proveedor y las deja en WebP, listas para R2.

Por proveedor produce portada.webp (640 px, para la tarjeta, de la primera foto que exista) y
1.webp, 2.webp… (galería, al tamaño que guardó el archivo; las que ya son WebP pasan tal cual).
Usa el ritmo de scraper.get. Nada queda en disco: todo se arma en memoria.
"""
import re
import subprocess
import tempfile
from pathlib import Path

import scraper

ANCHO_PORTADA = 640
CALIDAD_PORTADA = 70
CALIDAD_GALERIA = 75


def ancho_de(archivo):
    salida = subprocess.run(["sips", "-g", "pixelWidth", str(archivo)], capture_output=True, text=True).stdout
    m = re.search(r"pixelWidth: (\d+)", salida)
    return int(m.group(1)) if m else 0


def webp(datos, calidad, ancho=None):
    if not ancho and datos[8:12] == b"WEBP":
        return datos  # ya viene en WebP: recomprimir solo pierde calidad
    with tempfile.TemporaryDirectory() as carpeta:
        entrada, salida = Path(carpeta) / "entrada", Path(carpeta) / "salida.webp"
        entrada.write_bytes(datos)
        tamano = ["-resize", str(ancho), "0"] if ancho and ancho_de(entrada) > ancho else []
        hecho = subprocess.run(["cwebp", "-quiet", "-q", str(calidad), *tamano, str(entrada), "-o", str(salida)])
        return salida.read_bytes() if hecho.returncode == 0 else None


def fotos_de(proveedor):
    """[(nombre, bytes)] listos para subir; vacío si el archivo no guardó ninguna."""
    archivos = []
    for n, (_, grande) in enumerate(proveedor["fotos"], 1):
        ts, ruta = grande.split("/", 1)
        datos = scraper.get(f"https://web.archive.org/web/{ts}im_/https://cdn0.matrimonios.cl/{ruta}", binario=True)
        galeria = datos and webp(datos, CALIDAD_GALERIA)
        if not galeria:
            continue
        archivos.append((f"{n}.webp", galeria))
        if not any(nombre == "portada.webp" for nombre, _ in archivos):
            portada = webp(datos, CALIDAD_PORTADA, ANCHO_PORTADA)
            if portada:
                archivos.append(("portada.webp", portada))
    return archivos
