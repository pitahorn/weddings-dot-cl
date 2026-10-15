#!/usr/bin/env python3
"""
Rescata las fichas de proveedores de matrimonios.cl guardadas en Wayback Machine (2025).

Uso:
    python3 scraper.py musica-matrimonio photobooth

Por cada proveedor guarda nombre, nota, opiniones (con estrellas y texto), precio,
ubicación, descripción, preguntas frecuentes y los links a sus fotos en el archivo.
Al final escribe data/<categoria>.js, que lee index.html. Si se corta, retoma:
las páginas quedan comprimidas en cache/, así que re-correrlo solo vuelve a procesar.
"""
import gzip
import html as htmllib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DESDE = "2025"
RAIZ = Path(__file__).parent
CACHE = RAIZ / "cache"
DATA = RAIZ / "data"
PAUSA = 2.0  # segundos entre descargas, para que el archivo no nos bloquee
UA = {"User-Agent": "Mozilla/5.0 (archivo personal de matrimonio)"}
FICHA = re.compile(r"--e(\d+)/?$")
LD_JSON = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.S)
FOTO = re.compile(r"https://cdn\d\.matrimonios\.cl/vendor/(\d+)/3_2/\d+/(\w+)/([\w.-]+?)\.(?:jpe?g|webp|png)")


def get(url, intentos=4):
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                cuerpo = r.read()
                if cuerpo[:2] == b"\x1f\x8b":  # el archivo a veces responde comprimido sin avisar
                    cuerpo = gzip.decompress(cuerpo)
                return cuerpo.decode("utf-8", "replace")
        except Exception as e:
            if getattr(e, "code", None) == 404:
                return None
            espera = PAUSA * 2 ** (i + 1)
            print(f"  reintento en {espera:.0f}s ({e})", flush=True)
            time.sleep(espera)
    return None


def listar_fichas(cat):
    q = urllib.parse.urlencode({
        "url": f"matrimonios.cl/{cat}/",
        "matchType": "prefix",
        "from": DESDE,
        "output": "json",
        "fl": "original,timestamp",
        "filter": "statuscode:200",
        "collapse": "urlkey",
    })
    data = get(f"https://web.archive.org/cdx/search/cdx?{q}")
    fichas = {}
    for original, ts in (json.loads(data)[1:] if data else []):
        limpia = original.split("?")[0].split("#")[0].rstrip("/").replace("http://", "https://")
        if FICHA.search(limpia):
            fichas.setdefault(limpia, ts)
    return fichas


def texto(fragmento):
    sin_tags = re.sub(r"<br\s*/?>", "\n", fragmento)
    sin_tags = re.sub(r"<[^>]*(>|$)", " ", sin_tags)
    lineas = [re.sub(r"[ \t]+", " ", l).strip() for l in htmllib.unescape(sin_tags).split("\n")]
    return "\n".join(l for l in lineas if l).strip()


def bloque(html, clase):
    """Devuelve el HTML interno del primer <div> con esa clase, respetando anidamiento."""
    m = re.search(r'<div[^>]*class="[^"]*\b' + re.escape(clase) + r'\b[^"]*"[^>]*>', html)
    if not m:
        return ""
    pos, nivel = m.end(), 1
    abre, cierra = re.compile(r"<div\b"), re.compile(r"</div>")
    while nivel and pos < len(html):
        a, c = abre.search(html, pos), cierra.search(html, pos)
        if not c:
            break
        if a and a.start() < c.start():
            nivel, pos = nivel + 1, a.end()
        else:
            nivel, pos = nivel - 1, c.end()
            if not nivel:
                return html[m.end():c.start()]
    return ""


def negocio(html):
    for b in LD_JSON.findall(html):
        try:
            obj = json.loads(b.strip())
        except ValueError:
            continue
        for o in obj if isinstance(obj, list) else [obj]:
            if isinstance(o, dict) and ("address" in o or "aggregateRating" in o):
                return o
    return {}


def faqs(html):
    salida = []
    for item in re.findall(r'class="storefrontFaqs__item">(.*?)(?=class="storefrontFaqs__item"|class="storefrontReviews|$)', html, re.S):
        titulo = re.search(r'storefrontFaqs__itemTitle">(.*?)</h3>', item, re.S)
        if not titulo:
            continue
        lista = [texto(x) for x in re.findall(r'storefrontFaqs__itemList">(.*?)</div>', item, re.S)]
        resp = [x for x in lista if x] or [texto(item[titulo.end():])]
        salida.append({"p": texto(titulo.group(1)), "r": resp})
    return salida


def fotos(html, id_proveedor):
    vistas, salida = set(), []
    for carpeta, formato, nombre in FOTO.findall(html):
        if not re.search(rf"_{id_proveedor}(_v\d+)?(-\d+)?$", nombre) or nombre in vistas:
            continue
        vistas.add(nombre)
        salida.append(f"{carpeta}/{formato}/{nombre}")
    return salida


def extraer(html, url, ts):
    id_proveedor = FICHA.search(url).group(1)
    n = negocio(html)
    ar = n.get("aggregateRating") or {}
    adr = n.get("address") or {}
    geo = n.get("geo") or {}
    precio = n.get("priceRange") or texto(bloque(html, "storefrontHeadingFaqsCard")).split("\n")[0] or None
    opiniones = [{
        "autor": (r.get("author") or {}).get("name"),
        "fecha": r.get("datePublished"),
        "nota": (r.get("reviewRating") or {}).get("ratingValue"),
        "texto": htmllib.unescape(r.get("description") or "").strip(),
    } for r in n.get("review") or []]
    return {
        "nombre": htmllib.unescape(n.get("name") or "").strip(),
        "nota": ar.get("ratingValue"),
        "n_opiniones": ar.get("reviewCount") or 0,
        "precio": precio if precio and "$" in precio else None,
        "comuna": adr.get("addressLocality"),
        "region": adr.get("addressRegion"),
        "direccion": adr.get("streetAddress"),
        "geo": [geo.get("latitude"), geo.get("longitude")] if geo else None,
        "descripcion": texto(bloque(html, "storefrontDescription__content")),
        "faqs": faqs(html),
        "fotos": fotos(html, id_proveedor),
        "opiniones": opiniones,
        "ts": ts,
        "url": url,
    }


def procesar(cat):
    print(f"== {cat}", flush=True)
    fichas = listar_fichas(cat)
    print(f"  {len(fichas)} fichas archivadas desde {DESDE}", flush=True)
    carpeta = CACHE / cat
    carpeta.mkdir(parents=True, exist_ok=True)
    proveedores = []
    for i, (url, ts) in enumerate(sorted(fichas.items()), 1):
        archivo = carpeta / f"{FICHA.search(url).group(1)}.html.gz"
        html = gzip.decompress(archivo.read_bytes()).decode("utf-8") if archivo.exists() else ""
        if not html.lstrip().startswith("<"):
            html = get(f"https://web.archive.org/web/{ts}id_/{url}")
            time.sleep(PAUSA)
            if not html:
                print(f"  [{i}/{len(fichas)}] x no se pudo bajar {url}", flush=True)
                continue
            archivo.write_bytes(gzip.compress(html.encode("utf-8")))
        datos = extraer(html, url, ts)
        proveedores.append(datos)
        print(f"  [{i}/{len(fichas)}] {datos['nombre'][:50]} · {len(datos['fotos'])} fotos · {len(datos['opiniones'])} opiniones", flush=True)
    DATA.mkdir(exist_ok=True)
    cuerpo = json.dumps(proveedores, ensure_ascii=False, separators=(",", ":"))
    (DATA / f"{cat}.js").write_text(f"CATALOGO.agregar({json.dumps(cat)},{cuerpo});\n", "utf-8")
    print(f"  -> data/{cat}.js ({len(proveedores)} proveedores)", flush=True)


if __name__ == "__main__":
    for categoria in sys.argv[1:]:
        procesar(categoria)
