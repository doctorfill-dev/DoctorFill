# Base image stricte pour ARM64 Grace Blackwell
FROM nvcr.io/nvidia/pytorch:26.02-py3

WORKDIR /app

# Installation des dépendances légères (PyTorch est déjà dans l'image de base)
RUN pip install --no-cache-dir fastapi uvicorn sentence-transformers

# Copie du code
COPY app.py .

# Exposition du port
EXPOSE 8081

# Lancement de FastAPI
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8081"]