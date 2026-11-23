#!/usr/bin/env python3
"""
pdftools — herramientas para PDF escaneados, desde la línea de comandos.

Comandos:
  extraer    Crea un PDF con las páginas indicadas ("1-5, 10-15").
  cortar     Divide cada página en dos (escaneos de doble página).
  ocr        Agrega una capa de texto buscable (requiere Tesseract).
  comprimir  Limpia y comprime sin pérdida (opcionalmente con pérdida sutil).
  fondo      Para PDF en capas (MRC): baja la resolución del fondo o lo elimina.
  escaneo    Para PDF que son solo imágenes: corrige el tamaño de página y
             convierte a grises o a blanco y negro.

Ayuda de cada comando:  pdftools <comando> -h
"""
import argparse
import io
import math
import os
import shutil
import subprocess
import sys
import tempfile
import zlib

import pikepdf
import pymupdf
from pikepdf import Name, PdfImage
from PIL import Image
from tqdm import tqdm

Image.MAX_IMAGE_PIXELS = None
VERSION = "1.0"


# =====================================================================
#  Utilidades
# =====================================================================

def rangos(texto, total):
    """'1-5, 10-15' -> índices base 0. Admite 'fin' o un final abierto: '10-'."""
    paginas = []
    for parte in texto.split(","):
        parte = parte.strip()
        if not parte:
            continue
        a, guion, b = parte.partition("-")
        ini = int(a)
        fin = (total if b.strip() in ("", "fin") else int(b)) if guion else ini
        if not (1 <= ini <= fin <= total):
            raise SystemExit(f"Rango fuera del documento ({total} páginas): '{parte}'")
        paginas += range(ini, fin + 1)
    return [p - 1 for p in paginas]


def salida_por_defecto(entrada, sufijo):
    base, _ = os.path.splitext(entrada)
    return f"{base}_{sufijo}.pdf"


def tamano(ruta):
    return os.path.getsize(ruta) / 1e6


def informar(entrada, salida):
    a, b = tamano(entrada), tamano(salida)
    cambio = 100 * (b / a - 1)
    print(f"{os.path.basename(salida)}: {a:.2f} MB -> {b:.2f} MB ({cambio:+.1f} %)")


def _imagenes(pdf):
    return [o for o in pdf.objects
            if isinstance(o, pikepdf.Stream) and o.get("/Subtype") == "/Image"]


def _buscar_jbig2():
    """Busca el codificador jbig2 en el PATH o junto al programa."""
    encontrado = shutil.which("jbig2")
    if encontrado:
        return encontrado
    carpetas = [os.path.dirname(os.path.abspath(sys.argv[0])),
                os.path.dirname(sys.executable),
                getattr(sys, "_MEIPASS", "")]
    for c in carpetas:
        for sub in ("jbig2", ""):
            for nombre in ("jbig2.exe", "jbig2"):
                ruta = os.path.join(c, sub, nombre)
                if c and os.path.isfile(ruta):
                    return ruta
    return None


JBIG2 = _buscar_jbig2()


def codificar_bn(im):
    """Imagen en blanco y negro -> (datos, filtro). JBIG2 sin pérdida si está disponible."""
    im = im.convert("1")
    if JBIG2:
        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, "p.png")
            im.save(png)
            datos = subprocess.run([JBIG2, "-p", png], capture_output=True, check=True).stdout
        return datos, Name.JBIG2Decode
    return zlib.compress(im.tobytes(), 9), Name.FlateDecode


def codificar_jpx(im, razon):
    """Codifica en JPEG 2000 con una razón de compresión dada (40 = 40:1)."""
    b = io.BytesIO()
    im.save(b, "JPEG2000", quality_mode="rates", quality_layers=[razon], irreversible=True)
    return b.getvalue()


def nueva_imagen(pdf, im, datos, filtro, mascara=False):
    d = dict(Type=Name.XObject, Subtype=Name.Image, Width=im.width, Height=im.height, Filter=filtro)
    if mascara:
        d["ImageMask"] = True
    else:
        d["ColorSpace"] = {"1": Name.DeviceGray, "L": Name.DeviceGray}.get(im.mode, Name.DeviceRGB)
        d["BitsPerComponent"] = 1 if im.mode == "1" else 8
    return pdf.make_stream(datos, **d)


def umbral_otsu(gris):
    """Umbral automático de binarización (método de Otsu)."""
    hist = gris.histogram()[:256]
    total = sum(hist)
    suma_total = sum(i * h for i, h in enumerate(hist))
    w0 = suma0 = 0
    mejor, umbral = -1.0, 128
    for t in range(256):
        w0 += hist[t]
        if w0 == 0:
            continue
        w1 = total - w0
        if w1 == 0:
            break
        suma0 += t * hist[t]
        m0, m1 = suma0 / w0, (suma_total - suma0) / w1
        var = w0 * w1 * (m0 - m1) ** 2
        if var > mejor:
            mejor, umbral = var, t
    return umbral


def binarizar(im, umbral=None):
    g = im.convert("L")
    u = umbral_otsu(g) if umbral is None else umbral
    return g.point(lambda v: 255 if v > u else 0).convert("1")


# =====================================================================
#  1) Extraer páginas
# =====================================================================

def extraer(entrada, salida, seleccion):
    pdf = pikepdf.open(entrada)
    nuevo = pikepdf.new()
    for i in tqdm(rangos(seleccion, len(pdf.pages)), desc="Extrayendo", unit="pág"):
        nuevo.pages.append(pdf.pages[i])
    nuevo.save(salida)
    informar(entrada, salida)
    if tamano(salida) > 0.5 * tamano(entrada) and len(nuevo.pages) < 0.5 * len(pdf.pages):
        print("Nota: pesa casi lo mismo que el original; usa 'comprimir' para quitar lo que sobra.")


# =====================================================================
#  2) Cortar a la mitad
# =====================================================================

def cortar(entrada, salida, corte=0.5, derecha_a_izquierda=False):
    pdf = pikepdf.open(entrada)
    nuevo = pikepdf.new()
    for page in tqdm(pdf.pages, desc="Cortando", unit="pág"):
        x0, y0, x1, y1 = [float(v) for v in page.obj.get("/CropBox", page.mediabox)]
        rot = int(page.obj.get("/Rotate", 0)) % 360
        ancho, alto = (x1 - x0, y1 - y0) if rot in (0, 180) else (y1 - y0, x1 - x0)
        horizontal = ancho >= alto
        eje_x = horizontal if rot in (0, 180) else not horizontal
        if horizontal:
            invertir = {0: False, 90: False, 180: True, 270: True}[rot]
        else:
            invertir = {0: True, 90: False, 180: False, 270: True}[rot]
        if derecha_a_izquierda and horizontal:
            invertir = not invertir
        if eje_x:
            c = x0 + corte * (x1 - x0)
            mitades = [[x0, y0, c, y1], [c, y0, x1, y1]]
        else:
            c = y0 + corte * (y1 - y0)
            mitades = [[x0, y0, x1, c], [x0, c, x1, y1]]
        if invertir:
            mitades.reverse()
        for caja in mitades:
            nuevo.pages.append(page)
            p = nuevo.pages[-1]
            p.obj.MediaBox = pikepdf.Array(caja)
            p.obj.CropBox = pikepdf.Array(caja)
            for k in ("/TrimBox", "/BleedBox", "/ArtBox"):
                if k in p.obj:
                    del p.obj[k]
    nuevo.save(salida)
    print(f"{len(pdf.pages)} páginas -> {len(nuevo.pages)} páginas")
    informar(entrada, salida)


# =====================================================================
#  3) OCR
# =====================================================================

def _preparar_tesseract():
    """Busca Tesseract en el PATH o en las carpetas donde lo deja el instalador de Windows."""
    if shutil.which("tesseract"):
        return
    candidatos = [os.path.join(os.environ.get(v, ""), "Tesseract-OCR")
                  for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    candidatos += [os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "Tesseract-OCR")]
    for c in candidatos:
        if os.path.isfile(os.path.join(c, "tesseract.exe")):
            os.environ["PATH"] = c + os.pathsep + os.environ.get("PATH", "")
            return
    raise SystemExit("No se encontró Tesseract. Instálalo (ver README) o agrégalo al PATH.")


def idiomas_disponibles():
    try:
        r = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
        return set(r.stdout.split()[1:]) if r.returncode == 0 else set()
    except OSError:
        return set()


def ocr(entrada, salida, idiomas="eng+spa+lat+rus", rehacer=False):
    try:
        import ocrmypdf
    except ImportError:
        raise SystemExit("Falta el paquete ocrmypdf (pip install ocrmypdf).")
    _preparar_tesseract()
    faltan = [l for l in idiomas.split("+") if l not in idiomas_disponibles()]
    if faltan:
        raise SystemExit(f"Tesseract no tiene instalados estos idiomas: {', '.join(faltan)}. "
                         "Agrégalos reinstalando Tesseract (ver README) o usa -l con otros.")
    # use_threads: evita el multiproceso, que da problemas en ejecutables de Windows
    opciones = dict(language=idiomas.split("+"), output_type="pdf", optimize=0,
                    progress_bar=True, use_threads=True)
    if rehacer:
        opciones["redo_ocr"] = True
    else:
        opciones["skip_text"] = True
    ocrmypdf.ocr(entrada, salida, **opciones)
    informar(entrada, salida)


# =====================================================================
#  4) Comprimir
# =====================================================================

def _limpiar(entrada, salida):
    with pikepdf.open(entrada) as pdf:
        pdf.remove_unreferenced_resources()
        pdf.save(salida)


def resolucion_efectiva(archivo):
    """{número de objeto: ppp}, según el tamaño mayor con que se dibuja cada imagen."""
    ppp = {}
    doc = pymupdf.open(archivo)
    for page in doc:
        for info in page.get_image_info(xrefs=True):
            xref = info["xref"]
            if not xref:
                continue
            a, b, c, d = info["transform"][:4]
            ancho_pt, alto_pt = math.hypot(a, b), math.hypot(c, d)
            if ancho_pt < 1 or alto_pt < 1:
                continue
            r = min(info["width"] / (ancho_pt / 72), info["height"] / (alto_pt / 72))
            ppp[xref] = min(r, ppp.get(xref, r))
    doc.close()
    return ppp


def _reducir_resolucion(entrada, salida, ppp_bn, ppp_color, calidad_jpeg):
    ppp = resolucion_efectiva(entrada)
    pdf = pikepdf.open(entrada)
    for obj in tqdm(_imagenes(pdf), desc="Reduciendo resolución", unit="img"):
        if obj.get("/ImageMask", False) or "/Mask" in obj or obj.objgen[0] not in ppp:
            continue
        bn = int(obj.get("/BitsPerComponent", 8)) == 1
        objetivo = ppp_bn if bn else ppp_color
        actual = ppp[obj.objgen[0]]
        if actual <= objetivo * 1.1:
            continue
        try:
            im = PdfImage(obj).as_pil_image()
        except Exception:
            continue
        f = objetivo / actual
        nuevo = (max(1, round(im.width * f)), max(1, round(im.height * f)))
        if bn:
            im = im.convert("L").resize(nuevo, Image.LANCZOS)
            im = im.point(lambda v: 255 if v >= 128 else 0).convert("1")
            datos, filtro = codificar_bn(im)
            cs, bpc = Name.DeviceGray, 1
        else:
            modo = "L" if im.mode in ("1", "L", "LA", "I", "I;16") else "RGB"
            im = im.convert(modo).resize(nuevo, Image.LANCZOS)
            if str(obj.get("/Filter")) == "/JPXDecode":
                # JPEG 2000 comprime mejor que JPEG: se mantiene el formato
                datos, filtro = codificar_jpx(im, 40), Name.JPXDecode
            else:
                b = io.BytesIO()
                im.save(b, "JPEG", quality=calidad_jpeg, optimize=True)
                datos, filtro = b.getvalue(), Name.DCTDecode
            cs, bpc = (Name.DeviceGray if modo == "L" else Name.DeviceRGB), 8
        if len(datos) >= len(obj.read_raw_bytes()):
            continue
        obj.write(datos, filter=filtro)
        for k in ("/DecodeParms", "/Decode", "/Intent"):
            if k in obj:
                del obj[k]
        obj.Width, obj.Height = im.width, im.height
        obj.ColorSpace, obj.BitsPerComponent = cs, bpc
    pdf.save(salida)
    pdf.close()


def _subconjunto_fuentes(entrada, salida):
    with pymupdf.open(entrada) as doc:
        doc.subset_fonts()
        doc.save(salida, garbage=4, deflate=True, use_objstms=1)


def _jbig2(entrada, salida):
    if not JBIG2:
        print("  (jbig2 no encontrado: se omite la recodificación JBIG2)")
        shutil.copy(entrada, salida)
        return
    pdf = pikepdf.open(entrada)
    for obj in tqdm(_imagenes(pdf), desc="Recodificando a JBIG2", unit="img"):
        if int(obj.get("/BitsPerComponent", 8)) != 1 or obj.get("/ImageMask", False):
            continue
        if str(obj.get("/Filter")) == "/JBIG2Decode":
            continue
        try:
            datos, _ = codificar_bn(PdfImage(obj).as_pil_image())
        except Exception:
            continue
        if len(datos) >= len(obj.read_raw_bytes()):
            continue
        obj.write(datos, filter=Name.JBIG2Decode)
        for k in ("/DecodeParms", "/Decode"):
            if k in obj:
                del obj[k]
        obj.ColorSpace = Name.DeviceGray
        obj.BitsPerComponent = 1
    pdf.save(salida, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    pdf.close()


def verificar(original, nuevo):
    d1, d2 = pymupdf.open(original), pymupdf.open(nuevo)
    if len(d1) != len(d2):
        print("No se puede verificar: distinto número de páginas.")
        return
    distintas = [i + 1 for i in tqdm(range(len(d1)), desc="Verificando", unit="pág")
                 if d1[i].get_pixmap(dpi=150).samples != d2[i].get_pixmap(dpi=150).samples]
    print("Todas las páginas idénticas al original." if not distintas
          else f"Páginas con diferencias: {distintas}")


def comprimir(entrada, salida, perdida=False, ppp_bn=300, ppp_color=200,
              calidad_jpeg=85, comprobar=False):
    with tempfile.TemporaryDirectory() as tmp:
        paso = lambda n: os.path.join(tmp, f"{n}.pdf")
        print("Limpiando recursos no usados...")
        _limpiar(entrada, paso(1))
        if perdida:
            _reducir_resolucion(paso(1), paso(2), ppp_bn, ppp_color, calidad_jpeg)
        else:
            shutil.copy(paso(1), paso(2))
        print("Recortando fuentes...")
        _subconjunto_fuentes(paso(2), paso(3))
        _jbig2(paso(3), salida)
    informar(entrada, salida)
    if comprobar:
        if perdida:
            print("(con pérdida: no se verifica píxel a píxel)")
        else:
            verificar(entrada, salida)


# =====================================================================
#  5) PDF en capas (MRC): fondo
# =====================================================================

def _dibujos_de_imagen(page):
    """Lista de (índice de operador, nombre, objeto) de las imágenes que dibuja la página."""
    xobj = page.obj.get("/Resources", {}).get("/XObject", {})
    ops = pikepdf.parse_content_stream(page)
    res = []
    for i, (operandos, op) in enumerate(ops):
        if str(op) == "Do":
            nombre = str(operandos[0])
            o = xobj.get(nombre)
            if o is not None and o.get("/Subtype") == "/Image":
                res.append((i, nombre, o))
    return ops, res


def _capas_de_fondo(page):
    """En una página en capas, las imágenes de fondo son las opacas dibujadas
    antes de la primera imagen con máscara (/SMask o /ImageMask)."""
    ops, dibujos = _dibujos_de_imagen(page)
    con_mascara = [k for k, (_, _, o) in enumerate(dibujos)
                   if "/SMask" in o or o.get("/ImageMask", False)]
    if len(dibujos) < 2 or not con_mascara:
        return ops, []
    primera = con_mascara[0]
    fondos = [d for d in dibujos[:primera] if "/SMask" not in d[2] and not d[2].get("/ImageMask", False)]
    return ops, fondos


def fondo(entrada, salida, ppp=100, quitar=False, razon=40):
    pdf = pikepdf.open(entrada)
    tmp_ppp = resolucion_efectiva(entrada) if not quitar else {}
    tratadas = 0
    hechos = set()
    for page in tqdm(pdf.pages, desc="Quitando fondo" if quitar else "Reduciendo fondo", unit="pág"):
        ops, fondos = _capas_de_fondo(page)
        if not fondos:
            continue
        tratadas += 1
        if quitar:
            quitar_idx = {i for i, _, _ in fondos}
            ops = [x for k, x in enumerate(ops) if k not in quitar_idx]
            page.obj.Contents = pdf.make_stream(pikepdf.unparse_content_stream(ops))
            continue
        for _, _, o in fondos:
            num = o.objgen[0]
            if num in hechos or num not in tmp_ppp:
                continue
            hechos.add(num)
            actual = tmp_ppp[num]
            if actual <= ppp * 1.1:
                continue
            im = PdfImage(o).as_pil_image()
            im = im.convert("L" if im.mode in ("1", "L", "LA") else "RGB")
            f = ppp / actual
            im = im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))), Image.LANCZOS)
            datos = codificar_jpx(im, razon)
            if len(datos) >= len(o.read_raw_bytes()):
                continue
            o.write(datos, filter=Name.JPXDecode)
            for k in ("/DecodeParms", "/Decode"):
                if k in o:
                    del o[k]
            o.Width, o.Height = im.width, im.height
            o.ColorSpace = Name.DeviceGray if im.mode == "L" else Name.DeviceRGB
            o.BitsPerComponent = 8
    if tratadas == 0:
        print("Este PDF no parece estar en capas (MRC): no se generó ningún archivo.")
        return
    print(f"Páginas en capas tratadas: {tratadas} de {len(pdf.pages)}")
    pdf.remove_unreferenced_resources()
    pdf.save(salida, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    informar(entrada, salida)


# =====================================================================
#  6) PDF que son solo imágenes: escaneo
# =====================================================================

def _imagen_unica(page):
    """Si la página es solo una imagen (sin texto), la devuelve; si no, None."""
    ops, dibujos = _dibujos_de_imagen(page)
    if len(dibujos) != 1:
        return None
    if any(str(op) in ("Tj", "TJ", "'", '"') for _, op in ops):
        return None   # tiene texto (p. ej. OCR): no se toca
    return dibujos[0][2]


def tiene_color(im, umbral=0.001):
    """True si la imagen tiene color real (no solo el tono del papel)."""
    m = im.convert("RGB")
    m.thumbnail((400, 400))
    b = m.convert("HSV").tobytes()
    H, S, V = b[0::3], b[1::3], b[2::3]                 # 0-255 cada uno
    n = len(H)
    # ¿El papel tiene tinte? Se mira la mitad más clara de la página (el papel).
    v_medio = sorted(V)[n // 2]
    claros = [s_ for s_, v in zip(S, V) if v >= v_medio]
    papel_tenido = sum(1 for s_ in claros if s_ > 20) > 0.2 * len(claros)
    # Si lo tiene, su matiz típico (sepia, amarillento...) no cuenta como color.
    ref = None
    if papel_tenido:
        tinte = sorted(h for h, s_, v in zip(H, S, V) if s_ > 20 and v > 128)
        ref = tinte[len(tinte) // 2] * 360 / 255

    def es_color(h, s_, v):
        if s_ <= 64 or v <= 64:                         # poco saturado u oscuro
            return False
        if ref is None:                                 # papel neutro: todo tinte cuenta
            return True
        d = abs(h * 360 / 255 - ref) % 360
        return min(d, 360 - d) > 25                     # matiz distinto al del papel

    return sum(1 for t in zip(H, S, V) if es_color(*t)) / n > umbral


def escaneo(entrada, salida, modo="gris", ppp_real=300, color="auto", umbral=None, razon=40):
    pdf = pikepdf.open(entrada)
    n = len(pdf.pages)
    if color == "auto":
        forzar_color = None
    elif color in ("", "ninguna"):
        forzar_color = set()
    else:
        forzar_color = set(rangos(color, n))
    en_color, omitidas, medidas = [], [], None
    for i, page in enumerate(tqdm(pdf.pages, desc=f"Procesando ({modo})", unit="pág")):
        obj = _imagen_unica(page)
        if obj is None:
            omitidas.append(i + 1)
            continue
        W, H = int(obj.Width), int(obj.Height)
        w, h = W * 72 / ppp_real, H * 72 / ppp_real
        medidas = medidas or (w * 2.54 / 72, h * 2.54 / 72)
        nueva = obj
        if modo != "tamano":
            im = PdfImage(obj).as_pil_image()
            conservar = (tiene_color(im) if forzar_color is None else i in forzar_color) \
                and im.mode not in ("1", "L")
            if conservar:
                en_color.append(i + 1)          # se deja la imagen original
            elif modo == "gris":
                g = im.convert("L")
                nueva = nueva_imagen(pdf, g, codificar_jpx(g, razon), Name.JPXDecode)
            elif modo == "bn":
                b = binarizar(im, umbral)
                datos, filtro = codificar_bn(b)
                nueva = nueva_imagen(pdf, b, datos, filtro)
        page.obj.MediaBox = pikepdf.Array([0, 0, w, h])
        for k in ("/CropBox", "/TrimBox", "/BleedBox", "/ArtBox"):
            if k in page.obj:
                del page.obj[k]
        page.obj.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=nueva))
        page.obj.Contents = pdf.make_stream(b"q %.4f 0 0 %.4f 0 0 cm /Im0 Do Q" % (w, h))
    if len(omitidas) == n:
        print("Ninguna página es una imagen sola sin texto: no se generó ningún archivo.")
        return
    pdf.remove_unreferenced_resources()
    pdf.save(salida, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    if modo != "tamano":
        print("Páginas conservadas en color:", en_color if en_color else "ninguna")
    if omitidas:
        print(f"Páginas omitidas (no son una sola imagen o ya tienen texto): {omitidas}")
    if medidas:
        print(f"Tamaño de página corregido suponiendo {ppp_real} ppp "
              f"(primera página: {medidas[0]:.1f} x {medidas[1]:.1f} cm)")
    informar(entrada, salida)


# =====================================================================
#  Línea de comandos
# =====================================================================

def main():
    # Si la salida se redirige (a un archivo o a otro programa), se escribe en UTF-8;
    # en la consola de Windows los acentos ya se muestran bien.
    for flujo in (sys.stdout, sys.stderr):
        try:
            if not flujo.isatty():
                flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="pdftools", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version",
                    version=f"pdftools {VERSION} (jbig2: {'sí' if JBIG2 else 'no encontrado'})")
    sub = ap.add_subparsers(dest="comando", required=True, metavar="comando")

    def comun(p, sufijo):
        p.add_argument("entrada", help="PDF de entrada")
        p.add_argument("-o", "--salida", help=f"PDF de salida (por defecto: <entrada>_{sufijo}.pdf)")
        p.set_defaults(sufijo=sufijo)

    p = sub.add_parser("extraer", help="crear un PDF con algunas páginas")
    comun(p, "paginas")
    p.add_argument("-p", "--paginas", required=True, help='p. ej. "1-5, 10-15" o "20-" (hasta el final)')

    p = sub.add_parser("cortar", help="dividir cada página en dos")
    comun(p, "cortado")
    p.add_argument("--corte", type=float, default=0.5, help="posición del corte (por defecto 0.5)")
    p.add_argument("--rtl", action="store_true", help="libro de derecha a izquierda")

    p = sub.add_parser("ocr", help="agregar capa de texto (Tesseract)")
    comun(p, "ocr")
    p.add_argument("-l", "--idiomas", default="eng+spa+lat+rus",
                   help="idiomas de Tesseract unidos por '+' (por defecto eng+spa+lat+rus)")
    p.add_argument("--rehacer", action="store_true", help="reemplazar el OCR existente")

    p = sub.add_parser("comprimir", help="limpiar y comprimir")
    comun(p, "comprimido")
    p.add_argument("--perdida", action="store_true", help="reducir resolución de imágenes (pérdida sutil)")
    p.add_argument("--ppp-bn", type=int, default=300, help="máximo para imágenes B/N (por defecto 300)")
    p.add_argument("--ppp-color", type=int, default=200, help="máximo para gris/color (por defecto 200)")
    p.add_argument("--calidad", type=int, default=85, help="calidad JPEG 0-100 (por defecto 85)")
    p.add_argument("--verificar", action="store_true", help="comparar con el original píxel a píxel")

    p = sub.add_parser("fondo", help="PDF en capas: reducir o quitar el fondo")
    comun(p, "fondo")
    p.add_argument("--ppp", type=int, default=100, help="resolución del fondo (por defecto 100)")
    p.add_argument("--quitar", action="store_true", help="eliminar la capa de fondo")

    p = sub.add_parser("escaneo", help="PDF de solo imágenes: tamaño, grises o B/N")
    comun(p, "escaneo")
    p.add_argument("--modo", choices=["gris", "bn", "tamano"], default="gris",
                   help="gris (por defecto), bn = blanco y negro, tamano = solo corregir tamaño")
    p.add_argument("--ppp-real", type=int, default=300,
                   help="resolución supuesta del escaneo, para el tamaño de página (por defecto 300)")
    p.add_argument("--color", default="auto",
                   help='páginas que se conservan en color: "auto" (por defecto), "ninguna" o p. ej. "1, 5-6"')
    p.add_argument("--umbral", type=int, default=None,
                   help="modo bn: umbral 0-255 (por defecto automático; más bajo = letras más finas)")

    a = ap.parse_args()
    if not os.path.isfile(a.entrada):
        raise SystemExit(f"No existe el archivo: {a.entrada}")
    salida = a.salida or salida_por_defecto(a.entrada, a.sufijo)
    if os.path.abspath(salida) == os.path.abspath(a.entrada):
        raise SystemExit("La salida no puede ser el mismo archivo que la entrada.")

    if a.comando == "extraer":
        extraer(a.entrada, salida, a.paginas)
    elif a.comando == "cortar":
        cortar(a.entrada, salida, a.corte, a.rtl)
    elif a.comando == "ocr":
        ocr(a.entrada, salida, a.idiomas, a.rehacer)
    elif a.comando == "comprimir":
        comprimir(a.entrada, salida, a.perdida, a.ppp_bn, a.ppp_color, a.calidad, a.verificar)
    elif a.comando == "fondo":
        fondo(a.entrada, salida, a.ppp, a.quitar)
    elif a.comando == "escaneo":
        escaneo(a.entrada, salida, a.modo, a.ppp_real, a.color, a.umbral)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
