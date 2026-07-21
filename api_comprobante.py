"""
API REST para extraer datos de comprobantes bancarios.
Reemplaza a Groq Vision — usa EasyOCR + regex parsing local.

Despliegue:
    - Local: python api_comprobante.py
    - Colab: Ejecutar con ngrok para obtener URL pública
    - Cloud Run / Railway / Render: Dockerfile incluido

Endpoint:
    POST /extraer
    Body JSON: { "image_base64": "..." }
    Response: { "status": "ok", "data": { campos... } }
"""

import base64
import io
import os
import re
import sys
import tempfile

import cv2
import numpy as np
from flask import Flask, request, jsonify

# Importar el parser de comprobantes
# (asegurarse de que extraer_comprobante.py está en el mismo directorio)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extraer_comprobante import parsear_comprobante, obtener_reader, preprocesar_imagen

app = Flask(__name__)


@app.route('/health', methods=['GET'])
def health():
    """Endpoint de salud para verificar que la API está activa."""
    return jsonify({"status": "ok", "message": "API Comprobantes activa"})


@app.route('/extraer', methods=['POST'])
def extraer():
    """
    Recibe una imagen en base64 y retorna los datos del comprobante.
    
    Request JSON:
    {
        "image_base64": "base64_encoded_image..."
    }
    
    Response JSON:
    {
        "status": "ok",
        "data": {
            "banco": "...",
            "tipo_transferencia": "...",
            "fecha_transaccion": "...",
            "hora_transaccion": "...",
            "monto": "...",
            "moneda": "USD",
            "cuenta_origen": "...",
            "titular_origen": "...",
            "cuenta_destino": "...",
            "titular_destino": "...",
            "referencia": "",
            "numero_comprobante": "...",
            "estado": "exitosa",
            "comisiones": "...",
            "detalles_adicionales": ""
        }
    }
    """
    try:
        data = request.get_json()
        if not data or 'image_base64' not in data:
            return jsonify({
                "status": "error",
                "message": "No se recibió la imagen. Envíe 'image_base64' en el body."
            }), 400

        image_base64 = data['image_base64']

        # Decodificar imagen base64
        # Quitar prefijo data:image/xxx;base64, si existe
        if ',' in image_base64:
            image_base64 = image_base64.split(',', 1)[1]

        image_bytes = base64.b64decode(image_base64)

        # Guardar temporalmente para procesarla con OpenCV
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        try:
            # Extraer texto con EasyOCR
            reader = obtener_reader()
            img = cv2.imread(tmp_path)

            if img is None:
                return jsonify({
                    "status": "error",
                    "message": "No se pudo decodificar la imagen. Verifique el formato."
                }), 400

            # Redimensionar si es muy grande
            h, w = img.shape[:2]
            if w > 1500:
                escala = 1500 / w
                img = cv2.resize(img, (1500, int(h * escala)))

            # OCR
            resultados_ocr = reader.readtext(img)

            if not resultados_ocr:
                return jsonify({
                    "status": "error",
                    "message": "No se detectó texto en la imagen."
                }), 200

            # Parsear campos del comprobante
            datos = parsear_comprobante(resultados_ocr)

            # Convertir al formato que espera el Google Apps Script
            response_data = formatear_para_gas(datos)

            return jsonify({
                "status": "ok",
                "message": "Datos extraídos correctamente",
                "data": response_data
            })

        finally:
            # Limpiar archivo temporal
            os.unlink(tmp_path)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error procesando la imagen: {str(e)}"
        }), 500


def formatear_para_gas(datos: dict) -> dict:
    """
    Convierte el output del parser al formato que espera google_apps_script_transferencias.js
    """
    # Mapear campos del parser → formato GAS
    monto = (datos.get("monto") or "").replace("$", "").strip()

    # Determinar tipo de transferencia
    tipo_raw = datos.get("tipo_transaccion") or ""
    if "interna" in tipo_raw.lower():
        tipo = "transferencia_nacional"
    elif "otra" in tipo_raw.lower() or "interbancaria" in tipo_raw.lower():
        tipo = "transferencia_nacional"
    elif "pago" in tipo_raw.lower():
        tipo = "pago_digital"
    else:
        tipo = "transferencia_nacional"

    # Formatear fecha a DD-MM-AAAA
    fecha = datos.get("fecha") or ""
    fecha_formateada = formatear_fecha(fecha)

    # Hora
    hora = datos.get("hora") or ""

    # Estado
    estado = "exitosa"

    # Comisiones
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
        "estado": estado,
        "comisiones": comisiones,
        "detalles_adicionales": ""
    }


def formatear_fecha(fecha_str: str) -> str:
    """Convierte fechas al formato DD-MM-AAAA."""
    if not fecha_str:
        return ""

    # Ya es DD/MM/YYYY o DD-MM-YYYY
    match = re.match(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})', fecha_str)
    if match:
        return f"{match.group(1).zfill(2)}-{match.group(2).zfill(2)}-{match.group(3)}"

    # Formato "18 Jun 2026" o "25 jun 2026"
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


# ═══════════════════════════════════════════════════════════════════════════════
# EJECUCIÓN LOCAL
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🏦 API Comprobantes iniciada en puerto {port}")
    print(f"   POST http://localhost:{port}/extraer")
    print(f"   GET  http://localhost:{port}/health")
    app.run(host='0.0.0.0', port=port, debug=False)
