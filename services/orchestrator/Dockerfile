# services/orchestrator/Dockerfile
FROM nvcr.io/nvidia/pytorch:26.02-py3
WORKDIR /app
# Ajout de pypdf, pikepdf et lxml pour tes modules core
RUN pip install --no-cache-dir fastapi uvicorn httpx chromadb python-multipart pypdf pikepdf lxml
COPY . .
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]