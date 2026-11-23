"""Prueba el ejecutable compilado con los PDF de prueba.
Uso: python probar_exe.py <ruta al ejecutable> <carpeta con PDF de prueba> [--sin-ocr]"""
import os
import subprocess
import sys

import pymupdf

exe, carpeta = os.path.abspath(sys.argv[1]), sys.argv[2]
sin_ocr = "--sin-ocr" in sys.argv
os.chdir(carpeta)
errores = []


def correr(*args):
    print(">", "pdftools", *args, flush=True)
    r = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    salida = (r.stdout + r.stderr).replace("\r", "\n")
    lineas = [l for l in salida.splitlines() if l.strip() and "%|" not in l]
    print("\n".join("   " + l for l in lineas[-4:]), flush=True)
    if r.returncode != 0:
        errores.append(f"{' '.join(args)} terminó con código {r.returncode}")
    return salida


def comprobar(condicion, mensaje):
    print("   OK:" if condicion else "   FALLA:", mensaje, flush=True)
    if not condicion:
        errores.append(mensaje)


v = correr("--version")
comprobar("jbig2:     sí" in v, "jbig2 incluido en el ejecutable")
if "--tesseract-incluido" in sys.argv:
    comprobar("tesseract: incluido" in v, "Tesseract incluido en el ejecutable")
    comprobar(all(l in v for l in ("eng", "spa", "lat", "rus")), "Tesseract con eng, spa, lat y rus")

correr("extraer", "bn.pdf", "-p", "2-3")
comprobar(len(pymupdf.open("bn_paginas.pdf")) == 2, "extraer: 2 páginas")

correr("cortar", "bn.pdf")
comprobar(len(pymupdf.open("bn_cortado.pdf")) == 8, "cortar: 8 páginas")

s = correr("comprimir", "bn.pdf", "--verificar")
comprobar("idénticas" in s, "comprimir: páginas idénticas al original")

correr("comprimir", "bn.pdf", "--perdida", "-o", "bn_perdida.pdf")
comprobar(os.path.isfile("bn_perdida.pdf"), "comprimir --perdida: archivo creado")

s = correr("escaneo", "color.pdf")
comprobar("[1]" in s, "escaneo: detecta color solo en la página 1")
d = pymupdf.open("color_escaneo.pdf")
comprobar(abs(d[0].rect.width - 1700 * 72 / 300) < 1, "escaneo: tamaño de página corregido")

correr("escaneo", "color.pdf", "--modo", "bn", "--color", "ninguna", "-o", "color_bn.pdf")
comprobar(os.path.isfile("color_bn.pdf"), "escaneo --modo bn: archivo creado")

s = correr("fondo", "bn.pdf", "-o", "no_debe_existir.pdf")
comprobar(not os.path.isfile("no_debe_existir.pdf"), "fondo: no crea archivo en PDF sin capas")

if not sin_ocr:
    correr("ocr", "bn.pdf", "-l", "eng+spa+lat+rus")
    texto = pymupdf.open("bn_ocr.pdf")[0].get_text().lower() if os.path.isfile("bn_ocr.pdf") else ""
    comprobar("quick" in texto and "fox" in texto, "ocr: texto reconocido")

print()
if errores:
    print(f"FALLARON {len(errores)} pruebas:")
    for e in errores:
        print(" -", e)
    sys.exit(1)
print("Todas las pruebas pasaron.")
