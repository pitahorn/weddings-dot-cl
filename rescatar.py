#!/usr/bin/env python3
"""
Rescata categorías completas, proveedor por proveedor: ficha → fotos en WebP → R2.

Uso:
    caffeinate -i python3 -u rescatar.py banquetes centros-de-eventos

Sube el avance a GitHub cada 100 fichas nuevas, así se ven aparecer. Retoma solo: las fichas
quedan en cache/ y los proveedores ya subidos en cache/r2.txt.
"""
import sys

import fotos
import scraper
import subir


def main(categorias):
    subidor = subir.Subidor()
    ya_en_r2 = scraper.en_r2()

    def con_fotos(cat, url, ts, html):
        id_proveedor = scraper.FICHA.search(url).group(1)
        if f"{cat}/{id_proveedor}" in ya_en_r2:
            return
        archivos = fotos.fotos_de(scraper.extraer(html, url, ts))
        if archivos:
            subidor.proveedor(cat, id_proveedor, archivos)

    for cat in categorias:
        scraper.procesar(cat, sube=True, despues=con_fotos)
        subidor.esperar()
        scraper.armar(cat)
        scraper.publicar(f"data: {cat} con fotos en R2")


if __name__ == "__main__":
    main(sys.argv[1:])
