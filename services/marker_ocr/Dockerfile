# --- 1) Image de base officielle NVIDIA
# DGX Spark = driver 580 = CUDA 13.0. Le driver 590 (CUDA 13.1) n'est pas
# encore en stable sur aarch64. Utiliser 25.11 (CUDA 13.0.2) max.
FROM nvcr.io/nvidia/pytorch:25.11-py3

# --- 2) Définition du répertoire de travail dans le conteneur
WORKDIR /app

# --- 3) Installation des dépendances système nécessaires pour l'OCR
RUN apt-get update && apt-get install -y \
    git \
    libgl1 \
    libglib2.0-0 \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

# --- 4) Copie du fichier des dépendances Python et installation
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- 5) Copie du script de l'API
COPY app.py .

# --- 6) Ouverture du port interne 8082
EXPOSE 8082

# --- 7) Commande de démarrage du serveur FastAPI
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8082"]