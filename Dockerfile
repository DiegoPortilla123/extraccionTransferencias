FROM python:3.11-slim

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar PyTorch CPU (ligero ~200MB) desde repo oficial
RUN pip install --no-cache-dir torch==2.2.0+cpu torchvision==0.17.0+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Instalar resto de dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-descargar modelos de EasyOCR (evita descarga en runtime)
RUN python -c "import easyocr; reader = easyocr.Reader(['es','en'], gpu=False); print('OK')"

# Copiar código
COPY extraer_comprobante.py .
COPY api_comprobante.py .

# Puerto
EXPOSE 10000

# Ejecutar - timeout alto para primera carga
CMD ["gunicorn", "api_comprobante:app", "--bind", "0.0.0.0:10000", "--timeout", "300", "--workers", "1"]
