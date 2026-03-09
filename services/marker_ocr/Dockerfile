# --- 1) Image de base officielle NVIDIA
FROM nvcr.io/nvidia/pytorch:26.02-py3

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