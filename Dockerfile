FROM python:3.11-slim

# Instalar dependencias del sistema para OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requirements primero (aprovecha cache de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-descargar modelos de EasyOCR (para que no descargue en cada request)
RUN python -c "import easyocr; easyocr.Reader(['es', 'en'], gpu=False)"

# Copiar código
COPY extraer_comprobante.py .
COPY api_comprobante.py .

# Puerto
EXPOSE 10000

# Ejecutar con gunicorn (producción)
CMD ["gunicorn", "api_comprobante:app", "--bind", "0.0.0.0:10000", "--timeout", "120", "--workers", "1"]
