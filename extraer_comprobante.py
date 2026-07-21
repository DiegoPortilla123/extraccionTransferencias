"""
Extrae información de comprobantes de transferencia bancaria.
Usa EasyOCR (basado en redes neuronales, soporta español) para leer el texto
y luego extrae los campos clave con regex.

Instalación:
    pip install easyocr opencv-python

Uso:
    python extraer_comprobante.py
    python extraer_comprobante.py imagen.jpg
    python extraer_comprobante.py --carpeta ./comprobantes/
"""

import argparse
import glob
import os
import re
import sys

import cv2
import numpy as np

# EasyOCR se importa al usar (tarda en cargar el modelo la primera vez)
_reader = None


def _en_colab() -> bool:
    try:
        import google.colab  # noqa: F401
        return True
    except ImportError:
        return False


def seleccionar_imagen() -> str:
    if _en_colab():
        print("[i] Estás en Google Colab.")
        print("    Sube la imagen al panel de archivos o usa una ruta de Drive.")
        print()
        return input("Ingresa la ruta de la imagen: ").strip()

    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        ruta = filedialog.askopenfilename(
            title="Seleccionar comprobante",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp"), ("Todos", "*.*")]
        )
        root.destroy()
        return ruta
    except Exception:
        return input("Ingresa la ruta de la imagen: ").strip()


def obtener_reader():
    """Inicializa EasyOCR (solo la primera vez, después reutiliza)."""
    global _reader
    if _reader is None:
        try:
            import easyocr
            print("[...] Cargando modelo EasyOCR...")
            use_gpu = os.environ.get('USE_GPU', 'false').lower() == 'true'
            _reader = easyocr.Reader(['es', 'en'], gpu=use_gpu)
            print(f"[✓] EasyOCR listo (GPU: {use_gpu}).")
        except ImportError:
            print("[!] EasyOCR no instalado. Usar PaddleOCR en api_comprobante.py")
            return None
    return _reader


def preprocesar_imagen(ruta: str) -> np.ndarray:
    """Preprocesa la imagen para mejorar la lectura OCR."""
    img = cv2.imread(ruta)
    if img is None:
        return None

    # Si es muy grande, redimensionar (máximo 1500px de ancho)
    h, w = img.shape[:2]
    if w > 1500:
        escala = 1500 / w
        img = cv2.resize(img, (1500, int(h * escala)))

    return img


def extraer_texto_ocr(ruta: str) -> list:
    """
    Extrae todo el texto de la imagen usando EasyOCR.
    Retorna lista de (bbox, texto, confianza).
    """
    reader = obtener_reader()
    img = preprocesar_imagen(ruta)
    if img is None:
        print(f"[ERROR] No se pudo cargar: {ruta}")
        return []

    resultados = reader.readtext(img)
    return resultados


def parsear_comprobante(textos_raw: list) -> dict:
    """
    Analiza los textos extraídos y extrae los campos del comprobante.
    textos_raw: lista de (bbox, texto, confianza) de EasyOCR.
    """
    # Construir lista de textos con posición Y para contexto espacial
    lineas_con_pos = []
    for bbox, texto, conf in textos_raw:
        y_pos = bbox[0][1]
        lineas_con_pos.append({"texto": texto.strip(), "y": y_pos, "conf": conf})

    # Ordenar por posición vertical
    lineas_con_pos.sort(key=lambda x: x["y"])

    lineas = [item["texto"] for item in lineas_con_pos]
    texto_junto = " ".join(lineas)

    datos = {
        "monto": None,
        "fecha": None,
        "hora": None,
        "nro_transaccion": None,
        "remitente": None,
        "cuenta_remitente": None,
        "destinatario": None,
        "cuenta_destinatario": None,
        "banco": None,
        "tipo_transaccion": None,
        "comision": None,
        "valor_debitado": None,
    }

    # --- Banco ---
    es_deuna = False
    for linea in lineas:
        if re.search(r'\bd[!1]\b|deuna|pagaste\s+a', linea, re.IGNORECASE):
            datos["banco"] = "Deuna (d!)"
            es_deuna = True
            break

    if not datos["banco"]:
        bancos_conocidos = [
            ("Produbanco", "produbanco"),
            ("Banco Guayaquil", "guayaquil"),
            ("Banco Pichincha", "pichincha"),
            ("Banco del Pacífico", "pacífico"),
            ("Banco Internacional", "internacional"),
            ("Banecuador", "banecuador"),
            ("Banco Bolivariano", "bolivariano"),
            ("Cooperativa JEP", "jep"),
        ]
        for linea in lineas:
            for nombre_banco, keyword in bancos_conocidos:
                if keyword in linea.lower():
                    datos["banco"] = nombre_banco
                    break
            if datos["banco"]:
                break

    # --- Monto principal ---
    for linea in lineas:
        monto_match = re.search(r'\$\s*(\d+[\.,]\d{2})', linea)
        if monto_match:
            datos["monto"] = "$" + monto_match.group(1).replace(",", ".")
            break

    if not datos["monto"]:
        for linea in lineas:
            if re.search(r'fecha|hora|transacci|comisi|debitado|comprobante|costo|nro', linea, re.IGNORECASE):
                continue
            monto_match = re.search(r'\b(\d{1,6}[\.,]\d{2})\b', linea)
            if monto_match:
                valor = monto_match.group(1).replace(",", ".")
                if not re.match(r'20\d{2}', valor.split(".")[0]):
                    datos["monto"] = "$" + valor
                    break

    # --- Corrección "$" leído como "8" (Deuna) o "5" (Pichincha) ---
    if datos["monto"]:
        monto_str = datos["monto"].replace("$", "")
        parte_entera = monto_str.split(".")[0]

        if es_deuna and monto_str.startswith("8") and len(parte_entera) >= 3:
            datos["monto"] = "$" + monto_str[1:]
        elif not es_deuna and monto_str.startswith("5") and len(parte_entera) >= 3:
            tiene_dolar_real = any(
                re.search(r'\$\s*' + re.escape(monto_str), l) for l in lineas
            )
            if not tiene_dolar_real:
                datos["monto"] = "$" + monto_str[1:]

    # --- Tipo de transacción ---
    tipo_keywords = ["TRANSFERENCIA", "PAGO DE SERVICIO", "DEPÓSITO", "DEPOSITO"]
    tipo_lineas = []
    for linea in lineas:
        if any(kw in linea.upper() for kw in tipo_keywords):
            tipo_lineas.append(linea)
        elif "exitosa" in linea.lower() and "transferencia" in linea.lower():
            tipo_lineas.append(linea)
    if tipo_lineas:
        datos["tipo_transaccion"] = " ".join(tipo_lineas)

    # --- Fecha y hora ---
    for linea in lineas:
        # DD/MM/YYYY HH:MM:SS
        fecha_hora = re.search(
            r'(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})\s*(\d{1,2}[:\.\s]\d{2}(?:[:\.\s]\d{2})?)',
            linea
        )
        if fecha_hora:
            datos["fecha"] = fecha_hora.group(1)
            datos["hora"] = fecha_hora.group(2).replace(".", ":").replace(" ", ":")
            break

        # Solo fecha DD/MM/YYYY
        if not datos["fecha"]:
            fecha_match = re.search(r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})', linea)
            if fecha_match:
                datos["fecha"] = fecha_match.group(1)

        # Fecha con nombre de mes y posible día de semana:
        # "Jueves 18 Jun. 2026 -" o "23 jun 2026" o "25 jun 2026"
        if not datos["fecha"]:
            fecha_texto = re.search(
                r'(?:\w+\s+)?(\d{1,2})\s+(\w{3,9})\.?\s+(\d{4})',
                linea, re.IGNORECASE
            )
            if fecha_texto:
                dia = fecha_texto.group(1)
                mes = fecha_texto.group(2)
                anio = fecha_texto.group(3)
                if anio.startswith("20"):
                    datos["fecha"] = f"{dia} {mes} {anio}"

    # Hora en línea separada: "08.24 am", "04:06 pm", "15:28:58"
    if not datos["hora"]:
        for linea in lineas:
            hora_match = re.search(
                r'(\d{1,2}[:.]\d{2}(?:[:.]\d{2})?)\s*([aApP]\.?[mM]\.?)?',
                linea
            )
            if hora_match:
                hora_candidata = hora_match.group(0).strip()
                # Verificar que no es un monto (no tiene $ ni , seguido de 2 dígitos)
                if datos["monto"] and hora_match.group(1).replace(":", ".").replace(".", "") in datos["monto"].replace("$", "").replace(".", ""):
                    continue
                # Debe contener : o . y parecer hora (<=24 la primera parte)
                partes = re.split(r'[:.]', hora_match.group(1))
                if len(partes) >= 2 and int(partes[0]) <= 24 and int(partes[1]) <= 59:
                    hora_final = hora_match.group(1).replace(".", ":")
                    if hora_match.group(2):
                        hora_final += " " + hora_match.group(2)
                    datos["hora"] = hora_final
                    break

    # Reconstruir fecha de fragmentos (Pichincha: "I1nov" + "'2025")
    if not datos["fecha"]:
        meses = {"ene": "01", "feb": "02", "mar": "03", "abr": "04", "may": "05",
                 "jun": "06", "jul": "07", "ago": "08", "sep": "09", "oct": "10",
                 "nov": "11", "dic": "12"}
        texto_limpio = texto_junto.lower()
        for mes_nombre in meses:
            patron = re.search(
                r'[Il1]?(\d{1,2})\s*' + mes_nombre + r'\w*\s*[\'"]?(\d{4})',
                texto_limpio
            )
            if patron:
                dia = patron.group(1)
                anio = patron.group(2)
                datos["fecha"] = f"{dia} {mes_nombre} {anio}"
                break

    # --- Número de transacción ---
    for linea in lineas:
        # "Comprobante Nro" seguido de número en siguiente detección
        nro_match = re.search(r'(?:No\.?|Nro\.?)\s*:?\s*(\d{5,})', linea, re.IGNORECASE)
        if nro_match:
            datos["nro_transaccion"] = nro_match.group(1)
            break
        nro_match2 = re.search(r'transacci[oó]n\s*:?\s*(\d{5,})', linea, re.IGNORECASE)
        if nro_match2:
            datos["nro_transaccion"] = nro_match2.group(1)
            break
        nro_match3 = re.search(r'[Cc]omprobante\s*:?\s*(\d{5,})', linea)
        if nro_match3:
            datos["nro_transaccion"] = nro_match3.group(1)
            break

    # Si no encontró, buscar números largos sueltos (>= 8 dígitos) que no sean cuentas
    if not datos["nro_transaccion"]:
        for linea in lineas:
            nro_match = re.search(r'^[,.\s]*(\d{8,})$', linea.strip())
            if nro_match:
                datos["nro_transaccion"] = nro_match.group(1)
                break

    # --- Remitente y Destinatario ---
    excluir = {"banco", "guayaquil", "pichincha", "transferencia", "instituciones",
               "financieras", "corriente", "ahorros", "industrial", "responder",
               "comisión", "comision", "valor", "debitado", "inmediata", "interna",
               "código", "codigo", "verificacion", "verificación", "pagaste",
               "produbanco", "grupo", "promierica", "promerica", "interbancaria",
               "comprobante", "exitosa", "nacional", "línea", "linea", "bolon",
               "compartir", "calificar", "experiencia", "electrónico", "correo",
               "registrada"}

    remitente_directo = None
    destinatario_directo = None
    nombres_detectados = []
    cuentas_detectadas = []

    # Estrategia 1: "Para:" y "De:" explícitos (Produbanco)
    for linea in lineas:
        para_match = re.search(r'[Pp]ara\s*:\s*(.+)', linea)
        if para_match:
            nombre = para_match.group(1).strip()
            if len(nombre) > 3:
                destinatario_directo = nombre

        de_match = re.search(r'^[Dd]e\s*:\s*(.+)', linea)
        if de_match:
            nombre = de_match.group(1).strip()
            if len(nombre) > 3:
                remitente_directo = nombre

    # Estrategia 2: nombres propios en líneas sueltas (Guayaquil, Deuna, Pichincha)
    i = 0
    while i < len(lineas):
        linea = lineas[i].strip()

        # Quitar caracteres basura al inicio: ', [, etc.
        linea_limpia = re.sub(r"^['\[\]\.\,\s]+", "", linea)

        nombre_match = re.match(
            r'^([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,5})[\s.]*$',
            linea_limpia
        )
        if nombre_match:
            nombre = nombre_match.group(1)
            palabras = nombre.lower().split()
            if not any(p in excluir for p in palabras):
                # Verificar si la siguiente línea es continuación del nombre
                if i + 1 < len(lineas):
                    sig = re.sub(r"^['\[\]\.\,\s]+", "", lineas[i + 1].strip())
                    sig_match = re.match(
                        r'^([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,3})[\s.]*$',
                        sig
                    )
                    if sig_match:
                        sig_palabras = sig.lower().split()
                        if not any(p in excluir for p in sig_palabras) and len(sig) < 25:
                            nombre = nombre + " " + sig_match.group(1)
                            i += 1
                nombres_detectados.append(nombre)
        i += 1

    # Detectar cuentas
    for linea in lineas:
        # Cuenta con X o *: "000XXX3495", "325XXX2204", "******3965"
        cuenta_match = re.search(r'(\d{2,3}[Xx*]{2,4}\d{3,4}|\*{4,}\d{3,4})', linea)
        if cuenta_match:
            cuentas_detectadas.append(cuenta_match.group(1))
        else:
            # Número de cuenta largo (>= 7 dígitos, no es nro de transacción)
            cuenta_larga = re.match(r'^(\d{7,10})$', linea.strip())
            if cuenta_larga and cuenta_larga.group(1) != datos.get("nro_transaccion"):
                cuentas_detectadas.append(cuenta_larga.group(1))
            # Solo 4 dígitos sueltos (últimos dígitos de cuenta)
            elif re.match(r'^\d{4}$', linea.strip()):
                valor = linea.strip()
                if not valor.startswith("20"):
                    cuentas_detectadas.append("******" + valor)

    # Detectar "Industrial Danec"
    for linea in lineas:
        if re.search(r'industrial\s+danec|danec\s+s\.?a', linea, re.IGNORECASE):
            if not destinatario_directo:
                destinatario_directo = "Industrial Danec S.A."
            break
        elif re.search(r's\.?a\.?\s+industrial', linea, re.IGNORECASE):
            if not destinatario_directo:
                destinatario_directo = "S.A. Industrial Danec"
            break

    # Asignar con prioridad a Para:/De:
    if remitente_directo:
        datos["remitente"] = remitente_directo
    elif len(nombres_detectados) >= 1:
        datos["remitente"] = nombres_detectados[0]

    if destinatario_directo:
        datos["destinatario"] = destinatario_directo
    elif len(nombres_detectados) >= 2:
        datos["destinatario"] = nombres_detectados[1]

    # Cuentas: asignar en orden
    if len(cuentas_detectadas) >= 2:
        datos["cuenta_remitente"] = cuentas_detectadas[0]
        datos["cuenta_destinatario"] = cuentas_detectadas[1]
    elif len(cuentas_detectadas) == 1:
        datos["cuenta_remitente"] = cuentas_detectadas[0]

    # --- Comisión ---
    for i, linea in enumerate(lineas):
        if re.search(r'comisi[oó]n|costo', linea, re.IGNORECASE):
            monto_c = re.search(r'\$?\s*(\d+[\.,]\d{2})', linea)
            if monto_c:
                datos["comision"] = "$" + monto_c.group(1).replace(",", ".")
            elif i + 1 < len(lineas):
                monto_c = re.search(r'\$?\s*(\d+[\.,]\d{2})', lineas[i + 1])
                if monto_c:
                    datos["comision"] = "$" + monto_c.group(1).replace(",", ".")
            break

    # --- Valor debitado ---
    for i, linea in enumerate(lineas):
        if re.search(r'valor\s+debitado', linea, re.IGNORECASE):
            monto_d = re.search(r'\$?\s*(\d+[\.,]\d{2})', linea)
            if monto_d:
                datos["valor_debitado"] = "$" + monto_d.group(1).replace(",", ".")
            elif i + 1 < len(lineas):
                monto_d = re.search(r'\$?\s*(\d+[\.,]\d{2})', lineas[i + 1])
                if monto_d:
                    datos["valor_debitado"] = "$" + monto_d.group(1).replace(",", ".")
            break

    return datos


def procesar_comprobante(ruta: str, verbose: bool = True) -> dict:
    """Procesa un comprobante completo: OCR + parsing."""
    if verbose:
        print(f"\n{'='*60}")
        print(f"Procesando: {os.path.basename(ruta)}")
        print(f"{'='*60}")

    # 1. Extraer texto con OCR
    resultados_ocr = extraer_texto_ocr(ruta)

    if not resultados_ocr:
        print("[!] No se detectó texto en la imagen.")
        return {}

    if verbose:
        print(f"\n[✓] Textos detectados ({len(resultados_ocr)}):")
        print("-" * 40)
        for bbox, texto, conf in resultados_ocr:
            print(f"  [{conf:.2f}] {texto}")

    # 2. Parsear campos del comprobante
    datos = parsear_comprobante(resultados_ocr)

    if verbose:
        print(f"\n{'─'*40}")
        print("📋 DATOS EXTRAÍDOS DEL COMPROBANTE:")
        print(f"{'─'*40}")
        campos = [
            ("Banco", datos.get("banco")),
            ("Tipo", datos.get("tipo_transaccion")),
            ("Monto", datos.get("monto")),
            ("Fecha", datos.get("fecha")),
            ("Hora", datos.get("hora")),
            ("Nro. Transacción", datos.get("nro_transaccion")),
            ("Remitente", datos.get("remitente")),
            ("Cuenta remitente", datos.get("cuenta_remitente")),
            ("Destinatario", datos.get("destinatario")),
            ("Cuenta destino", datos.get("cuenta_destinatario")),
            ("Comisión", datos.get("comision")),
            ("Valor debitado", datos.get("valor_debitado")),
        ]
        for nombre, valor in campos:
            if valor:
                print(f"  {nombre:<20}: {valor}")

    return datos


def main():
    parser = argparse.ArgumentParser(description="Extraer datos de comprobantes bancarios")
    parser.add_argument("imagen", nargs="?", default=None,
                        help="Ruta a la imagen (si no se indica, abre selector)")
    parser.add_argument("--carpeta", type=str, default=None,
                        help="Procesar todas las imágenes de una carpeta")
    parser.add_argument("--gpu", action="store_true", default=True,
                        help="Usar GPU si está disponible (default: True)")
    args = parser.parse_args()

    # Recopilar imágenes
    rutas = []

    if args.carpeta:
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp"):
            rutas.extend(glob.glob(os.path.join(args.carpeta, ext)))
        if not rutas:
            print(f"[!] No se encontraron imágenes en: {args.carpeta}")
            sys.exit(1)
    elif args.imagen:
        rutas = [args.imagen]
    else:
        print("[...] Selecciona la imagen del comprobante...")
        ruta = seleccionar_imagen()
        if not ruta:
            print("[!] No se seleccionó imagen. Saliendo.")
            sys.exit(0)
        rutas = [ruta]

    # Verificar que existen
    for r in rutas:
        if not os.path.isfile(r):
            print(f"[ERROR] No existe: {r}")
            sys.exit(1)

    # Procesar
    print(f"\n🏦 EXTRACTOR DE COMPROBANTES BANCARIOS")
    print(f"   Imágenes a procesar: {len(rutas)}")

    todos_los_datos = []
    for ruta in rutas:
        datos = procesar_comprobante(ruta)
        datos["archivo"] = os.path.basename(ruta)
        todos_los_datos.append(datos)

    # Resumen si son múltiples
    if len(todos_los_datos) > 1:
        print(f"\n\n{'='*60}")
        print("📊 RESUMEN")
        print(f"{'='*60}")
        print(f"{'Archivo':<35} {'Monto':<12} {'Remitente'}")
        print("-" * 60)
        for d in todos_los_datos:
            print(f"{d.get('archivo','?'):<35} {d.get('monto','?'):<12} {d.get('remitente','?')}")


if __name__ == "__main__":
    main()
