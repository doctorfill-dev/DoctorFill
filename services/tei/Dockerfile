# Base image stricte pour ARM64 Grace Blackwell
FROM nvcr.io/nvidia/pytorch:26.02-py3

WORKDIR /app

# [SEC-17] Dépendances pinnées via requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code
COPY app.py .

# Exposition du port
EXPOSE 8081

# Lancement de FastAPI
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8081"]