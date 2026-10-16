#!/usr/bin/env python3
"""
Baja las fotos que el archivo guardó y las deja optimizadas en WebP, listas para subir a R2.

Uso:
    python3 fotos.py trajes-novio

Por proveedor escribe fotos/<categoria>/<id>/portada.webp (640 px, para la tarjeta) y
1.webp, 2.webp… (galería, al tamaño que guardó el archivo; las que ya son WebP se copian tal cual). Usa el mismo ritmo que scraper.py
y retoma si se corta: lo ya bajado queda en cache/_img/.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import scraper

ORIGINALES = scraper.CACHE / "_img"
SALIDA = scraper.RAIZ / "fotos"
ANCHO_PORTADA = 640
CALIDAD_PORTADA = 70
CALIDAD_GALERIA = 75


def proveedores(cat):
    texto = (scraper.DATA / f"{cat}.js").read_text("utf-8")
    return json.loads(texto[texto.index(",") + 1:texto.rindex(")")])


def original(ref):
    """Archivo local con la foto tal como la guardó el archivo; None si ya no está."""
    archivo = ORIGINALES / hashlib.sha1(ref.encode()).hexdigest()
    if archivo.exists():
        return archivo
    ts, ruta = ref.split("/", 1)
    datos = scraper.get(f"https://web.archive.org/web/{ts}im_/https://cdn0.matrimonios.cl/{ruta}", binario=True)
    if not datos:
        return None
    ORIGINALES.mkdir(parents=True, exist_ok=True)
    archivo.write_bytes(datos)
    return archivo


def ancho_de(archivo):
    salida = subprocess.run(["sips", "-g", "pixelWidth", str(archivo)], capture_output=True, text=True).stdout
    m = re.search(r"pixelWidth: (\d+)", salida)
    return int(m.group(1)) if m else 0


def webp(entrada, salida, calidad, ancho=None):
    salida.parent.mkdir(parents=True, exist_ok=True)
    datos = entrada.read_bytes()
    if not ancho and datos[8:12] == b"WEBP":
        return salida.write_bytes(datos) > 0  # ya viene en WebP: recomprimir solo pierde calidad
    tamano = ["-resize", str(ancho), "0"] if ancho and ancho_de(entrada) > ancho else []
    hecho = subprocess.run(["cwebp", "-quiet", "-q", str(calidad), *tamano, str(entrada), "-o", str(salida)])
    return hecho.returncode == 0


def procesar(cat):
    provs = [p for p in proveedores(cat) if p["fotos"]]
    scraper.log(f"== fotos {cat}: {len(provs)} proveedores, {sum(len(p['fotos']) for p in provs)} fotos")
    for i, p in enumerate(provs, 1):
        carpeta = SALIDA / cat / re.search(r"--e(\d+)", p["url"]).group(1)
        for n, (_, grande) in enumerate(p["fotos"], 1):
            destino, portada = carpeta / f"{n}.webp", carpeta / "portada.webp"
            if destino.exists() and (n > 1 or portada.exists()):
                continue
            fuente = original(grande)
            if fuente and webp(fuente, destino, CALIDAD_GALERIA) and n == 1:
                webp(fuente, portada, CALIDAD_PORTADA, ANCHO_PORTADA)
        scraper.log(f"[{i}/{len(provs)}] {p['nombre'][:50]}")


if __name__ == "__main__":
    for categoria in sys.argv[1:]:
        procesar(categoria)
