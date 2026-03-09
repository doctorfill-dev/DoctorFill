# DoctorFill - Microservice : Marker OCR

API FastAPI conteneurisée encapsulant la librairie `marker-pdf` pour extraire le texte et la mise en page (Markdown) de PDF médicaux.

## 🚀 Architecture & Performances

- **Isolation :** Tourne dans son propre conteneur (`df-services-marker_ocr`).
- **Optimisation VRAM :** Les modèles de vision (Surya/Texify) sont instanciés **une seule fois** au démarrage (`DocumentConverter()`) pour des extractions quasi instantanées.

## 🛠️ Installation & Démarrage

**1. Build de l'image (Temps estimé : ~10 min) :**
```bash
docker build --no-cache -t df-image-marker .
```

**2. Lancement du conteneur :**
```bash
docker run -d \
  --gpus all \
  -p 8082:8082 \
  --name df-services-marker_ocr \
  df-image-marker
```

## 🛰️ Endpoints

- `GET /health` : Vérifie le statut de l'API et la charge VRAM.
- `POST /extract` : Reçoit un PDF, retourne le Markdown.

*Exemple d'appel :*
```bash
curl -X POST -F "file=@mon_document.pdf" http://localhost:8082/extract
```

## 📝 Commandes utiles

```bash
# Voir les logs en temps réel
docker logs -f df-services-marker_ocr

# Lister les conteneurs (même arrêtés)
docker ps -a
```