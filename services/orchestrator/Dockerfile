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
# Le commit et l'horodatage complètent la version : entre deux releases, c'est
# le seul moyen de savoir quelle image tourne réellement. Voir services/build.sh.
ARG APP_VERSION=""
ARG APP_COMMIT=""
ARG APP_BUILT_AT=""
ENV APP_VERSION=${APP_VERSION} \
    APP_COMMIT=${APP_COMMIT} \
    APP_BUILT_AT=${APP_BUILT_AT}

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]