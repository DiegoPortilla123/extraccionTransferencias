"""
═══════════════════════════════════════════════════════════════
EJECUTAR EN GOOGLE COLAB - Levanta la API de comprobantes
con una URL pública via ngrok.

Pasos:
1. Sube este archivo y extraer_comprobante.py a Colab/Drive
2. Ejecuta cada celda en orden
3. Copia la URL pública de ngrok
4. Pégala en google_apps_script_transferencias.js (variable API_URL)
═══════════════════════════════════════════════════════════════
"""

# ── CELDA 1: Instalar dependencias ──
# !pip install flask easyocr opencv-python-headless pyngrok

# ── CELDA 2: Configurar ngrok (registrarse gratis en ngrok.com) ──
# Obtén tu token en: https://dashboard.ngrok.com/get-started/your-authtoken
NGROK_AUTH_TOKEN = "TU_TOKEN_AQUI"  # ← REEMPLAZAR

# ── CELDA 3: Ejecutar API ──
import os
import sys
import threading

# Configurar path
sys.path.insert(0, '/content/drive/MyDrive/DetecciónImagenes')
os.chdir('/content/drive/MyDrive/DetecciónImagenes')

# Importar la API
from api_comprobante import app

# Configurar ngrok
from pyngrok import ngrok
ngrok.set_auth_token(NGROK_AUTH_TOKEN)

# Abrir túnel
public_url = ngrok.connect(5000)
print(f"\n{'='*60}")
print(f"🏦 API DE COMPROBANTES ACTIVA")
print(f"{'='*60}")
print(f"\n   URL PÚBLICA: {public_url}")
print(f"\n   Endpoint: {public_url}/extraer")
print(f"   Health:   {public_url}/health")
print(f"\n   ⚠️  Copia la URL y pégala en tu Google Apps Script")
print(f"   ⚠️  La API estará activa mientras este notebook esté abierto")
print(f"{'='*60}\n")

# Iniciar Flask en segundo plano
threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000)).start()
