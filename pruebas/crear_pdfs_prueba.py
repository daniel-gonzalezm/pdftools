"""Crea PDF de prueba para verificar el ejecutable después de compilarlo."""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

carpeta = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(carpeta, exist_ok=True)

TEXTO = ["The quick brown fox jumps", "over the lazy dog again", "and again, page number {n}"]


def pagina(n, color=False):
    im = Image.new("RGB", (1700, 2200), (236, 226, 200) if color else "white")
    d = ImageDraw.Draw(im)
    fuente = ImageFont.load_default(size=70)
    for i, linea in enumerate(TEXTO):
        d.text((150, 300 + i * 130), linea.format(n=n), fill=(20, 20, 20), font=fuente)
    if color and n == 1:   # portada con un título grande en tinta roja
        d.text((150, 900), "RED TITLE", fill=(200, 20, 20), font=ImageFont.load_default(size=220))
    return im


# 1) Escaneo en blanco y negro, 4 páginas (para extraer, cortar, comprimir, ocr)
bn = [pagina(n).convert("1") for n in range(1, 5)]
bn[0].save(os.path.join(carpeta, "bn.pdf"), save_all=True, append_images=bn[1:], resolution=200)

# 2) Escaneo a color a 72 ppp, 3 páginas, la primera con tinta roja (para escaneo)
col = [pagina(n, color=True) for n in range(1, 4)]
col[0].save(os.path.join(carpeta, "color.pdf"), save_all=True, append_images=col[1:], resolution=72)
print("PDF de prueba creados en", carpeta)
