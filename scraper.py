#!/usr/bin/env python3
"""
Rescata las fichas de proveedores de matrimonios.cl guardadas en Wayback Machine (2025).

Uso:
    python3 scraper.py --publicar florerias musica-matrimonio   # descarga y sube a GitHub
    python3 scraper.py --publicar                               # todas las de categorias.txt
    python3 scraper.py --armar                                  # rearma data/ desde cache/, sin red

Por cada proveedor guarda nombre, nota, opiniones (con estrellas y texto), precio,
ubicación, descripción, preguntas frecuentes y los links a sus fotos en el archivo.
Al final escribe data/<categoria>.js, que lee index.html. Si se corta, retoma:
las páginas quedan comprimidas en cache/, así que re-correrlo solo vuelve a procesar.
"""
import gzip
import html as htmllib
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DESDE = "2025"
RAIZ = Path(__file__).parent
CACHE = RAIZ / "cache"
DATA = RAIZ / "data"
INTERVALO = 5.0  # segundos entre pedidos: el archivo bloquea sobre ~15 por minuto
BLOQUEOS = [300, 900, 3600]  # esperas si el archivo nos rechaza; después, alerta
PUBLICAR_CADA = 100  # proveedores nuevos entre cada subida a GitHub
MAX_NO_ENCONTRADAS = 20  # seguidas: más que eso huele a URLs mal armadas, no a huecos del archivo
UA = {"User-Agent": "Mozilla/5.0 (archivo personal de matrimonio)"}
FICHA = re.compile(r"--e(\d+)/?$")
LD_JSON = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.S)
FOTO = re.compile(r"https://cdn\d\.matrimonios\.cl/vendor/(\d+)/3_2/\d+/(\w+)/([\w.-]+?)\.(?:jpe?g|webp|png)")


_ultimo_pedido = 0.0


def log(mensaje):
    print(f"{time.strftime('%H:%M')} {mensaje}", flush=True)


def alerta(mensaje):
    """Se detiene y avisa: mejor parar y mirar que seguir golpeando al archivo."""
    log(f"ALERTA: {mensaje}")
    sys.exit(2)


def get(url):
    """Espera los bloqueos (5, 15, 60 min); si siguen, se detiene. Un 4xx que no sea 429 = no existe."""
    global _ultimo_pedido
    for i in range(len(BLOQUEOS) + 1):
        time.sleep(max(0.0, _ultimo_pedido + INTERVALO - time.monotonic()))
        _ultimo_pedido = time.monotonic()
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                cuerpo = r.read()
                if cuerpo[:2] == b"\x1f\x8b":  # el archivo a veces responde comprimido sin avisar
                    cuerpo = gzip.decompress(cuerpo)
                return cuerpo.decode("utf-8", "replace")
        except Exception as e:
            codigo = getattr(e, "code", None)
            if codigo and 400 <= codigo < 500 and codigo != 429:
                return None
            if i == len(BLOQUEOS):
                alerta(f"el archivo sigue sin responder tras {sum(BLOQUEOS) // 60} min ({e})")
            log(f"archivo no responde ({e}), espero {BLOQUEOS[i] // 60} min")
            time.sleep(BLOQUEOS[i])


def listar_fichas(cat):
    guardadas = CACHE / cat / "_fichas.json"
    if guardadas.exists():
        return json.loads(guardadas.read_text("utf-8"))
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
    if data:
        guardadas.parent.mkdir(parents=True, exist_ok=True)
        guardadas.write_text(json.dumps(fichas), "utf-8")
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


def categorias():
    lineas = (RAIZ / "categorias.txt").read_text("utf-8").splitlines()
    return [l.split()[1] for l in lineas if l.startswith("[v]")]


def leer(archivo):
    """HTML guardado en cache/, o "" si no existe o quedó corrupto."""
    if not archivo.exists():
        return ""
    html = gzip.decompress(archivo.read_bytes()).decode("utf-8")
    return html if html.lstrip().startswith("<") else ""


def armar(cat):
    """Escribe data/<cat>.js con todo lo que hay en cache/, sin tocar la red."""
    carpeta = CACHE / cat
    fichas = listar_fichas(cat) if (carpeta / "_fichas.json").exists() else {}
    ts_por_id = {FICHA.search(u).group(1): ts for u, ts in fichas.items()}
    proveedores = []
    for archivo in sorted(carpeta.glob("*.html.gz")):
        html = leer(archivo)
        canonica = re.search(r'<link rel="canonical" href="([^"]+)"', html)
        if not canonica:
            continue
        url = htmllib.unescape(canonica.group(1))
        proveedores.append(extraer(html, url, ts_por_id.get(archivo.name.split(".")[0], DESDE)))
    DATA.mkdir(exist_ok=True)
    cuerpo = json.dumps(proveedores, ensure_ascii=False, separators=(",", ":"))
    (DATA / f"{cat}.js").write_text(f"CATALOGO.agregar({json.dumps(cat)},{cuerpo});\n", "utf-8")
    return len(proveedores), (len(fichas) if fichas else None)


def escribir_estado():
    estado = {}
    for cat in categorias():
        archivo = DATA / f"{cat}.js"
        if not archivo.exists():
            continue
        fichas = CACHE / cat / "_fichas.json"
        total = len(json.loads(fichas.read_text("utf-8"))) if fichas.exists() else None
        listos = archivo.read_text("utf-8").count('"url":')
        estado[cat] = {"listos": listos, "total": total}
    (DATA / "estado.js").write_text(
        f"CATALOGO.estado({json.dumps(estado)},{json.dumps(time.strftime('%Y-%m-%d %H:%M'))});\n", "utf-8")


def publicar(mensaje):
    escribir_estado()
    subprocess.run(["git", "add", "data"], cwd=RAIZ, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=RAIZ).returncode == 0:
        return
    cuerpo = f"{mensaje}\n\n🪨 Generated with Claude Code\n\nCo-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>\n"
    subprocess.run(["git", "commit", "-q", "-m", cuerpo], cwd=RAIZ, check=True)
    if subprocess.run(["git", "push", "-q", "origin", "main"], cwd=RAIZ).returncode:
        alerta("git push falló; los datos quedaron commiteados en local")


def procesar(cat, sube):
    log(f"== {cat}")
    fichas = listar_fichas(cat)
    log(f"{len(fichas)} fichas archivadas desde {DESDE}")
    carpeta = CACHE / cat
    nuevas = no_encontradas = 0
    for i, (url, ts) in enumerate(sorted(fichas.items()), 1):
        archivo = carpeta / f"{FICHA.search(url).group(1)}.html.gz"
        if leer(archivo):
            continue
        html = get(f"https://web.archive.org/web/{ts}id_/{url}")
        if not html:
            no_encontradas += 1
            log(f"[{i}/{len(fichas)}] x el archivo no tiene {url}")
            if no_encontradas >= MAX_NO_ENCONTRADAS:
                alerta(f"{no_encontradas} fichas seguidas no existen en el archivo")
            continue
        archivo.write_bytes(gzip.compress(html.encode("utf-8")))
        nuevas, no_encontradas = nuevas + 1, 0
        log(f"[{i}/{len(fichas)}] {url.rsplit('/', 1)[-1][:60]}")
        if sube and nuevas % PUBLICAR_CADA == 0:
            armar(cat)
            publicar(f"data: {cat} ({i}/{len(fichas)})")
    listos, total = armar(cat)
    escribir_estado()
    log(f"-> data/{cat}.js ({listos} proveedores)")
    if sube:
        publicar(f"data: {cat} completa ({listos} proveedores)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--armar"]:
        for cat in categorias():
            if (CACHE / cat).exists():
                print(cat, armar(cat), flush=True)
        escribir_estado()
    else:
        sube = "--publicar" in args
        for categoria in [a for a in args if a != "--publicar"] or categorias():
            procesar(categoria, sube)
