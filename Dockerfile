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

# Instalar PyTorch CPU desde repositorio oficial y luego el resto
RUN pip install --no-cache-dir torch==2.2.0+cpu torchvision==0.17.0+cpu \
    --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# Pre-descargar modelos de EasyOCR (evita descarga en cada request)
RUN python -c "import easyocr; easyocr.Reader(['es', 'en'], gpu=False)"

# Copiar código
COPY extraer_comprobante.py .
COPY api_comprobante.py .

# Puerto
EXPOSE 10000

# Ejecutar con gunicorn
CMD ["gunicorn", "api_comprobante:app", "--bind", "0.0.0.0:10000", "--timeout", "120", "--workers", "1"]
