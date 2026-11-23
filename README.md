# pdftools

Herramientas de línea de comandos para PDF escaneados: extraer páginas, cortar dobles páginas,
OCR, compresión sin pérdida y reducción de escaneos en capas o de solo imágenes.

## Comandos

```
pdftools extraer   libro.pdf -p "1-5, 10-15"      # "20-" = desde la 20 hasta el final
pdftools cortar    escaneo.pdf                    # --corte 0.52 si el lomo está corrido, --rtl
pdftools ocr       libro.pdf -l lat               # idiomas: eng, spa, lat, rus (o "spa+eng")
pdftools comprimir libro.pdf                      # sin pérdida; --verificar compara píxel a píxel
pdftools comprimir libro.pdf --perdida            # baja resolución: --ppp-bn 300 --ppp-color 200
pdftools fondo     libro.pdf                      # PDF en capas: fondo a 100 ppp (--ppp)
pdftools fondo     libro.pdf --quitar             # PDF en capas: eliminar el fondo
pdftools escaneo   libro.pdf                      # solo imágenes: tamaño + grises (color "auto")
pdftools escaneo   libro.pdf --modo bn            # solo imágenes: blanco y negro (--umbral)
```

- Si no se indica `-o salida.pdf`, el resultado se guarda como `<nombre>_<comando>.pdf`.
  El original nunca se modifica.
- Ayuda completa: `pdftools -h` y `pdftools <comando> -h`.
- Desde la propia carpeta del programa: en **PowerShell** escribe `.\pdftools ...`; en **cmd**, `pdftools ...`.
  El PDF puede estar en cualquier otra carpeta: `.\pdftools comprimir "C:\Libros\libro.pdf"`.
- Orden recomendado: `extraer` / `cortar` → `escaneo` o `fondo` → `ocr` → `comprimir`.

## Obtener el ejecutable (compilado por GitHub)

1. Crea una cuenta en GitHub (gratuita) y un repositorio nuevo (puede ser privado).
2. En el repositorio: **Add file → Upload files** y arrastra **todo el contenido** de esta carpeta,
   incluida la carpeta `.github`. Confirma con **Commit changes**.
3. Ve a la pestaña **Actions**. La compilación parte sola (tarda unos 10–15 minutos).
   Si no parte, elige *Compilar pdftools para Windows* → **Run workflow**.
4. Cuando termine con ✓ verde, abre la ejecución y descarga **pdftools-windows** (un .zip)
   desde la sección *Artifacts*.

Cada vez que subas un cambio a `pdftools.py`, se compila una versión nueva.

## Instalar en Windows

1. **Antes de descomprimir:** clic derecho en el .zip → Propiedades → marca **Desbloquear** →
   Aceptar. Así Windows no bloquea el programa por venir de internet.
2. Descomprime la carpeta `pdftools` en un lugar fijo, por ejemplo `C:\Herramientas\pdftools`,
   y ejecuta los comandos desde ahí (o agrégala al PATH, paso 3).
3. *(Opcional)* Agrégala al PATH para usarla desde cualquier carpeta: busca en Inicio
   *"Editar las variables de entorno de esta cuenta"* → **Path** → Editar → Nuevo →
   `C:\Herramientas\pdftools` → Aceptar. Abre una terminal nueva y prueba `pdftools --version`.
4. **No hace falta instalar nada más**: la carpeta incluye Python, jbig2 y Tesseract (OCR)
   con los idiomas inglés, español, latín y ruso. `pdftools --version` muestra los componentes.

Si el antivirus o SmartScreen avisan la primera vez, es habitual con programas no firmados
compilados con PyInstaller; el código fuente completo está en este repositorio.

## Archivos

| Archivo | Para qué |
|---|---|
| `pdftools.py` | El programa |
| `pdftools.spec` | Configuración de PyInstaller (qué incluir en el ejecutable) |
| `requirements.txt` | Versiones de las librerías de Python |
| `.github/workflows/compilar.yml` | Instrucciones de compilación para GitHub Actions. Ahí se eligen los idiomas de Tesseract (`IDIOMAS`) y la variante de modelos (`MODELOS_TESSERACT`: `tessdata_fast` o `tessdata_best`) |
| `pruebas/` | Pruebas automáticas que se ejecutan después de compilar |

Para usarlo sin compilar (con Python instalado): `pip install -r requirements.txt` y
`python pdftools.py <comando> ...`.
