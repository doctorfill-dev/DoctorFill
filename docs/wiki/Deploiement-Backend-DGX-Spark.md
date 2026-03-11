# Déploiement Backend — NVIDIA DGX Spark

## Prérequis

| Composant | Version minimum |
|-----------|----------------|
| NVIDIA DGX Spark | Grace Blackwell, 128 Go VRAM |
| Docker | 24+ |
| Docker Compose | v2+ |
| NVIDIA Container Toolkit | Installé et configuré |
| Git | 2.x |

## 1. Cloner le repo

```bash
git clone https://github.com/doctorfill-dev/DoctorFill.git
cd DoctorFill/services
```

## 2. Configuration environnement

```bash
cp .env.example .env
```

Éditer `.env` avec les valeurs de production :

```env
# URLs des services (ne pas modifier si Docker Compose)
MARKER_URL=http://marker_ocr:8082
TEI_URL=http://tei:8081
VLLM_URL=http://vllm:8000/v1
VLLM_MODEL_NAME=Qwen/Qwen2.5-14B-Instruct-AWQ

# Modèles TEI
EMBED_MODEL_NAME=BAAI/bge-m3
RERANK_MODEL_NAME=BAAI/bge-reranker-v2-m3

# CORS — domaines autorisés en production
ALLOWED_ORIGINS=https://doctorfill.ch,https://www.doctorfill.ch

# Retention des jobs (secondes)
JOB_RETENTION_SECONDS=3600

# Clé API (générer une clé forte)
API_KEY=<votre-clé-api-secrète>
```

### Générer une clé API sécurisée

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 3. Pré-téléchargement des modèles

Les modèles sont téléchargés automatiquement au premier lancement, mais le cache HuggingFace est monté depuis le host pour persister entre les redémarrages :

```bash
# Créer le répertoire de cache si nécessaire
mkdir -p ~/.cache/huggingface

# Optionnel : pré-télécharger les modèles
pip install huggingface_hub
huggingface-cli download Qwen/Qwen2.5-14B-Instruct-AWQ
huggingface-cli download BAAI/bge-m3
huggingface-cli download BAAI/bge-reranker-v2-m3
```

## 4. Build et lancement

```bash
# Build des images custom (orchestrator, marker_ocr, tei)
docker compose build

# Lancement complet (mode détaché)
docker compose up -d

# Vérifier les logs de démarrage
docker compose logs -f
```

### Temps de démarrage

| Service | Temps approximatif |
|---------|-------------------|
| vLLM | ~5-8 min (chargement modèle 14B) |
| Marker OCR | ~3-5 min (modèles vision) |
| TEI | ~3-5 min (embedding + reranker) |
| Orchestrator | ~10s (attend les 3 services ci-dessus) |

> Le `start_period` des healthchecks est configuré à 600s (10 min) pour laisser le temps aux modèles de charger.

## 5. Vérification

```bash
# Santé globale
docker compose ps

# Test de l'API
curl -H "X-API-Key: <votre-clé>" http://localhost:8080/health

# Vérification VRAM
nvidia-smi
```

### VRAM attendue

| Service | VRAM |
|---------|------|
| vLLM (Qwen2.5-14B-AWQ) | ~17.7 Go |
| Marker OCR | ~3.8 Go |
| TEI (bge-m3 + bge-reranker-v2-m3) | ~4.5 Go |
| **Total** | **~40 Go / 128 Go** |

## 6. Cloudflare Tunnel (exposition API)

Le backend n'est accessible que sur `localhost:8080`. Pour l'exposer au frontend Cloudflare Pages, on utilise un **Cloudflare Tunnel** :

```bash
# Installer cloudflared
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared.deb

# Authentification
cloudflared tunnel login

# Créer le tunnel
cloudflared tunnel create doctorfill

# Configurer le tunnel
cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: api.doctorfill.ch
    service: http://localhost:8080
  - service: http_status:404
EOF

# Ajouter l'entrée DNS
cloudflared tunnel route dns doctorfill api.doctorfill.ch

# Lancer le tunnel en service
sudo cloudflared service install
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
```

## 7. Commandes utiles

```bash
# Rebuild un service spécifique
docker compose build orchestrator && docker compose up -d orchestrator

# Redémarrer tout
docker compose restart

# Voir les logs d'un service
docker compose logs -f orchestrator

# Arrêter tout
docker compose down

# Nettoyer les images non utilisées
docker system prune -f
```

## 8. Troubleshooting

| Problème | Solution |
|----------|----------|
| vLLM ne démarre pas | Vérifier VRAM avec `nvidia-smi`, réduire `--gpu-memory-utilization` |
| Healthcheck timeout | Augmenter `start_period` dans docker-compose.yml |
| OOM (Out of Memory) | Vérifier qu'aucun autre processus n'utilise le GPU |
| API 403 | Vérifier la clé API dans `.env` et dans le header `X-API-Key` |
| CORS errors | Vérifier `ALLOWED_ORIGINS` dans `.env` |
| Tunnel non connecté | `cloudflared tunnel info doctorfill` + vérifier les logs |
