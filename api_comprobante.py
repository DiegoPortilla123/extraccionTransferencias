"""
API REST para extraer datos de comprobantes bancarios.
Usa EasyOCR + regex parsing.

Endpoint:
    POST /extraer
    GET  /health
"""

import base64
import os
import re
import sys
import tempfile

import cv2
import numpy as np
from flask import Flask, request, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extraer_comprobante import parsear_comprobante

app = Flask(__name__)

# OCR reader global
_reader = None


def obtener_reader():
    global _reader
    if _reader is None:
        import easyocr
        print("[...] Cargando EasyOCR...")
        _reader = easyocr.Reader(['es', 'en'], gpu=False)
        print("[✓] EasyOCR listo.")
    return _reader


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "message": "API Comprobantes activa"})


@app.route('/extraer', methods=['POST'])
def extraer():
    try:
        data = request.get_json()
        if not data or 'image_base64' not in data:
            return jsonify({"status": "error", "message": "No se recibió image_base64."}), 400

        image_base64 = data['image_base64']
        if ',' in image_base64:
            image_base64 = image_base64.split(',', 1)[1]

        image_bytes = base64.b64decode(image_base64)

        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        try:
            img = cv2.imread(tmp_path)
            if img is None:
                return jsonify({"status": "error", "message": "No se pudo decodificar la imagen."}), 400

            h, w = img.shape[:2]
            if w > 1500:
                escala = 1500 / w
                img = cv2.resize(img, (1500, int(h * escala)))

            reader = obtener_reader()
            resultados_ocr = reader.readtext(img)

            if not resultados_ocr:
                return jsonify({"status": "error", "message": "No se detectó texto en la imagen."}), 200

            # Convertir formato EasyOCR a lo que espera parsear_comprobante
            textos_raw = []
            for (bbox, texto, conf) in resultados_ocr:
                textos_raw.append((bbox, texto, conf))

            datos = parsear_comprobante(textos_raw)
            response_data = formatear_para_gas(datos)

            return jsonify({"status": "ok", "message": "Datos extraídos correctamente", "data": response_data})

        finally:
            os.unlink(tmp_path)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Error: {str(e)}"}), 500


def formatear_para_gas(datos: dict) -> dict:
    monto = (datos.get("monto") or "").replace("$", "").strip()
    tipo_raw = datos.get("tipo_transaccion") or ""
    if "interna" in tipo_raw.lower() or "otra" in tipo_raw.lower() or "interbancaria" in tipo_raw.lower():
        tipo = "transferencia_nacional"
    elif "pago" in tipo_raw.lower():
        tipo = "pago_digital"
    else:
        tipo = "transferencia_nacional"

    fecha = datos.get("fecha") or ""
    comisiones = (datos.get("comision") or "").replace("$", "").strip() or None

    return {
        "banco": datos.get("banco") or "",
        "tipo_transferencia": tipo,
        "fecha_transaccion": formatear_fecha(fecha),
        "hora_transaccion": datos.get("hora") or None,
        "monto": monto,
        "moneda": "USD",
        "cuenta_origen": datos.get("cuenta_remitente") or "",
        "titular_origen": datos.get("remitente") or "",
        "cuenta_destino": datos.get("cuenta_destinatario") or "",
        "titular_destino": datos.get("destinatario") or "",
        "referencia": "",
        "numero_comprobante": datos.get("nro_transaccion") or "",
        "estado": "exitosa",
        "comisiones": comisiones,
        "detalles_adicionales": ""
    }


def formatear_fecha(fecha_str: str) -> str:
    if not fecha_str:
        return ""
    match = re.match(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})', fecha_str)
    if match:
        return f"{match.group(1).zfill(2)}-{match.group(2).zfill(2)}-{match.group(3)}"
    meses = {"ene": "01", "feb": "02", "mar": "03", "abr": "04", "may": "05", "jun": "06",
             "jul": "07", "ago": "08", "sep": "09", "oct": "10", "nov": "11", "dic": "12"}
    match = re.match(r'(\d{1,2})\s+(\w{3,})\s+(\d{4})', fecha_str)
    if match:
        dia = match.group(1).zfill(2)
        mes_num = meses.get(match.group(2).lower()[:3], "00")
        return f"{dia}-{mes_num}-{match.group(3)}"
    return fecha_str


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"API en puerto {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
