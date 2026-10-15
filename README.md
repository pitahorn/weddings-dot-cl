# weddings-dot-cl
respaldo del webarchive de matrimonios.cl, con un poco de amor para hacerlo navegable

matrimonios.cl cerró, pero Wayback Machine guardó las fichas de sus proveedores en 2025.
Este repo las rescata: nombre, nota, opiniones con estrellas, precio, ubicación, descripción
y preguntas frecuentes de cada proveedor, en un catálogo que se abre sin instalar nada.

## Ver el catálogo

Abre `index.html` con doble clic. Elige una categoría, busca, filtra por zona y nota.
Las fotos cargan desde el archivo, así que necesitan internet; el archivo no guardó fotos
de todos los proveedores.

## Descargar más categorías

```sh
python3 scraper.py florerias photobooth
```

Las categorías están en `categorias.txt` (`[v]` = de proveedores). Solo usa librerías
estándar de Python. Va lento a propósito (unos 15–20 s por ficha) y, si se corta, retoma:
las páginas quedan comprimidas en `cache/`, que no se sube al repo.

## Qué hay en `data/`

Un `<categoria>.js` por categoría, con una lista de proveedores:
`nombre`, `nota`, `n_opiniones`, `precio`, `comuna`, `region`, `direccion`, `geo`,
`descripcion`, `faqs`, `opiniones` (las primeras que mostraba la ficha), `fotos` (rutas
en el CDN, sin tamaño) y `url` + `ts` para abrir la ficha original en el archivo.

## Pendiente

- `vestidos-novia` es un catálogo de vestidos (diseñador → colección → vestido), no de
  proveedores; necesita su propia pasada.
- Pasada de fotos: consultar al archivo cuáles existen de verdad y guardar solo esas.
