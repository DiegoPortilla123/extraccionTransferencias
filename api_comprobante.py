"""
API REST para extraer datos de comprobantes bancarios.
Usa PaddleOCR (más ligero que EasyOCR, cabe en 512MB RAM).

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

# OCR reader global (se carga en la primera petición)
_ocr = None


def obtener_ocr():
    """Inicializa PaddleOCR (solo la primera vez)."""
    global _ocr
    if _ocr is None:
        print("[...] Cargando PaddleOCR (descargando modelos si es la primera vez)...")
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(use_angle_cls=True, lang='latin', use_gpu=False, show_log=False)
        print("[✓] PaddleOCR cargado.")
    return _ocr


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "message": "API Comprobantes activa (PaddleOCR)"})


@app.route('/extraer', methods=['POST'])
def extraer():
    try:
        data = request.get_json()
        if not data or 'image_base64' not in data:
            return jsonify({
                "status": "error",
                "message": "No se recibió la imagen. Envíe 'image_base64' en el body."
            }), 400

        image_base64 = data['image_base64']

        # Quitar prefijo data:image/xxx;base64, si existe
        if ',' in image_base64:
            image_base64 = image_base64.split(',', 1)[1]

        image_bytes = base64.b64decode(image_base64)

        # Guardar temporalmente
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        try:
            # Leer imagen con OpenCV
            img = cv2.imread(tmp_path)
            if img is None:
                return jsonify({
                    "status": "error",
                    "message": "No se pudo decodificar la imagen."
                }), 400

            # Redimensionar si es muy grande
            h, w = img.shape[:2]
            if w > 1500:
                escala = 1500 / w
                img = cv2.resize(img, (1500, int(h * escala)))
                # Guardar redimensionada
                cv2.imwrite(tmp_path, img)

            # OCR con PaddleOCR
            ocr = obtener_ocr()
            result = ocr.ocr(tmp_path, cls=True)

            if not result or not result[0]:
                return jsonify({
                    "status": "error",
                    "message": "No se detectó texto en la imagen."
                }), 200

            # Convertir resultado de PaddleOCR al formato que espera parsear_comprobante
            # PaddleOCR retorna: [[[box], (text, conf)], ...]
            textos_raw = []
            for line in result[0]:
                bbox = line[0]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                texto = line[1][0]
                conf = line[1][1]
                textos_raw.append((bbox, texto, conf))

            # Parsear campos del comprobante
            datos = parsear_comprobante(textos_raw)

            # Formatear para GAS
            response_data = formatear_para_gas(datos)

            return jsonify({
                "status": "ok",
                "message": "Datos extraídos correctamente",
                "data": response_data
            })

        finally:
            os.unlink(tmp_path)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Error procesando la imagen: {str(e)}"
        }), 500


def formatear_para_gas(datos: dict) -> dict:
    """Convierte el output del parser al formato del Google Apps Script."""
    monto = (datos.get("monto") or "").replace("$", "").strip()

    tipo_raw = datos.get("tipo_transaccion") or ""
    if "interna" in tipo_raw.lower() or "otra" in tipo_raw.lower() or "interbancaria" in tipo_raw.lower():
        tipo = "transferencia_nacional"
    elif "pago" in tipo_raw.lower():
        tipo = "pago_digital"
    else:
        tipo = "transferencia_nacional"

    fecha = datos.get("fecha") or ""
    fecha_formateada = formatear_fecha(fecha)
    hora = datos.get("hora") or ""
    comisiones = (datos.get("comision") or "").replace("$", "").strip() or None

    return {
        "banco": datos.get("banco") or "",
        "tipo_transferencia": tipo,
        "fecha_transaccion": fecha_formateada,
        "hora_transaccion": hora or None,
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

    meses = {
        "ene": "01", "feb": "02", "mar": "03", "abr": "04",
        "may": "05", "jun": "06", "jul": "07", "ago": "08",
        "sep": "09", "oct": "10", "nov": "11", "dic": "12"
    }
    match = re.match(r'(\d{1,2})\s+(\w{3,})\s+(\d{4})', fecha_str)
    if match:
        dia = match.group(1).zfill(2)
        mes_nombre = match.group(2).lower()[:3]
        anio = match.group(3)
        mes_num = meses.get(mes_nombre, "00")
        return f"{dia}-{mes_num}-{anio}"

    return fecha_str


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"🏦 API Comprobantes en puerto {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
