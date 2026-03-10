# services/orchestrator/Dockerfile
FROM nvcr.io/nvidia/pytorch:26.02-py3
WORKDIR /app

# [SEC-17] Dépendances pinnées via requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]