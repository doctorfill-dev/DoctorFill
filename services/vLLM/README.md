# DoctorFill - Microservice : vLLM

Ce composant gère l'inférence du modèle de langage avec un haut niveau de concurrence grâce au continuous batching.

## ⚙️ Configuration de production

Le conteneur utilise l'image officielle NVIDIA (compatibilité ARM64 garantie) et charge le modèle quantifié `Qwen2.5-14B-Instruct-AWQ` :

```bash
docker run -d --gpus all \
  --ipc=host \
  -p 8000:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  --name df-services-vllm \
  nvcr.io/nvidia/vllm:26.02-py3 \
  vllm serve Qwen/Qwen2.5-14B-Instruct-AWQ \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.15
```

**Historique d'optimisation `--gpu-memory-utilization` :**
- `0.70` : Concurrence ~48x | VRAM : ~110 Go
- `0.30` : Concurrence ~16x | VRAM : ~50 Go
- `0.15` : Concurrence ~3.7x | VRAM : ~17 Go **(Configuration retenue)**

## 🔬 Notes cliniques
Le choix actuel de `Qwen2.5-14B-Instruct-AWQ` offre d'excellents résultats pour la précision des extractions médicales, validés par retour médical. D'autres itérations de LLM pourront être testées ultérieurement.