# services/orchestrator/Dockerfile
FROM nvcr.io/nvidia/pytorch:26.02-py3
WORKDIR /app

# [SEC-17] Dépendances pinnées via requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Le fichier VERSION est à la racine du dépôt, hors du contexte de build : la
# version est donc injectée au build. Sans elle, app.py retombe sur le fichier
# (utile en exécution locale depuis le dépôt) puis sur "inconnue".
ARG APP_VERSION=""
ENV APP_VERSION=${APP_VERSION}

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]