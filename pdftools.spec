# Configuración de PyInstaller para pdftools.
# Compilar con:  pyinstaller pdftools.spec
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

datas, binaries, hiddenimports = [], [], []

for paquete in ("pikepdf", "ocrmypdf", "pypdfium2", "pypdfium2_raw", "uharfbuzz"):
    d, b, h = collect_all(paquete)
    datas += d; binaries += b; hiddenimports += h

for paquete in ("pdfminer", "fpdf"):
    datas += collect_data_files(paquete)

for dist in ("ocrmypdf", "pikepdf", "pypdfium2", "fpdf2", "pdfminer.six", "img2pdf", "pydantic"):
    datas += copy_metadata(dist)

# Partes de PyMuPDF que pdftools no usa (modelo de layout ~50 MB y archivos de desarrollo)
def util(entrada):
    ruta = entrada[0].replace("\\", "/")
    return not any(x in ruta for x in ("pymupdf/layout", "pymupdf/mupdf-devel"))

excluir = ["numpy", "pymupdf.layout", "onnxruntime", "cv2", "matplotlib", "pandas", "scipy",
           "tkinter", "IPython", "pytest"]

a = Analysis(
    ["pdftools.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=excluir,
)
a.datas = [x for x in a.datas if util(x)]
a.binaries = [x for x in a.binaries if util(x)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pdftools",
    console=True,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="pdftools", upx=False)
