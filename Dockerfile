FROM python:3.11-slim

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar e instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY extraer_comprobante.py .
COPY api_comprobante.py .

# Puerto
EXPOSE 10000

# Ejecutar con gunicorn
CMD ["gunicorn", "api_comprobante:app", "--bind", "0.0.0.0:10000", "--timeout", "300", "--workers", "1"]
