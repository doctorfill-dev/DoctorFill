# Déploiement Frontend — Cloudflare Pages

## Prérequis

| Composant | Requis |
|-----------|--------|
| Node.js | 18+ |
| npm | 9+ |
| Compte Cloudflare | Avec accès Pages |
| Domaine | doctorfill.ch (configuré sur Cloudflare DNS) |

## 1. Configuration locale

```bash
cd frontend
npm install
```

### Variables d'environnement

Créer un fichier `.env` à la racine du dossier `frontend/` :

```env
# URL de l'API backend (via Cloudflare Tunnel)
VITE_API_URL=https://api.doctorfill.ch
```

> En développement local, utiliser `VITE_API_URL=http://localhost:8080`

## 2. Build local (vérification)

```bash
npm run build
```

Le build produit un dossier `dist/` avec les fichiers statiques.

## 3. Déploiement sur Cloudflare Pages

### Option A : Via le dashboard Cloudflare

1. Aller sur [Cloudflare Dashboard](https://dash.cloudflare.com/) → Pages
2. Cliquer **"Create a project"** → **"Connect to Git"**
3. Sélectionner le repo `doctorfill-dev/DoctorFill`
4. Configurer le build :

| Paramètre | Valeur |
|-----------|--------|
| Production branch | `main` |
| Build command | `cd frontend && npm install && npm run build` |
| Build output directory | `frontend/dist` |
| Root directory | `/` |

5. Ajouter les variables d'environnement :
   - `VITE_API_URL` = `https://api.doctorfill.ch`
   - `NODE_VERSION` = `18`

6. Cliquer **"Save and Deploy"**

### Option B : Via Wrangler CLI

```bash
# Installer Wrangler
npm install -g wrangler

# Login
wrangler login

# Build
cd frontend && npm run build

# Déployer
wrangler pages deploy dist --project-name=doctorfill
```

## 4. Configuration du domaine custom

### DNS sur Cloudflare

1. Dashboard → DNS → Ajouter un enregistrement :

| Type | Nom | Contenu |
|------|-----|---------|
| CNAME | `doctorfill.ch` | `doctorfill.pages.dev` |
| CNAME | `www` | `doctorfill.pages.dev` |

2. Dashboard → Pages → `doctorfill` → Custom domains → Ajouter `doctorfill.ch`

### SSL/TLS

Cloudflare Pages fournit automatiquement un certificat SSL. Vérifier que le mode SSL est en **"Full (strict)"** dans les paramètres DNS.

## 5. Déploiements automatiques

Chaque push sur la branche `main` déclenche automatiquement un nouveau déploiement sur Cloudflare Pages.

```bash
git push origin main
# → Cloudflare Pages build automatiquement
```

### Preview deployments

Les branches autres que `main` génèrent des **preview URLs** :
- `feature-xyz` → `feature-xyz.doctorfill.pages.dev`

## 6. Architecture réseau

```
┌─────────────────────────────────────────────────┐
│                  Client (navigateur)             │
│                                                   │
│  doctorfill.ch ──→ Cloudflare Pages (frontend)  │
│  api.doctorfill.ch ──→ Cloudflare Tunnel ──→ DGX│
└─────────────────────────────────────────────────┘
```

### Flux des requêtes API

1. Le frontend fait un `fetch("https://api.doctorfill.ch/process-form", ...)`
2. Cloudflare DNS résout `api.doctorfill.ch` vers le Tunnel
3. Le Tunnel forwarde la requête vers `localhost:8080` sur le DGX Spark
4. L'orchestrator traite la requête et retourne le résultat

### Headers importants

Le frontend envoie systématiquement :
```
X-API-Key: <clé-api>
Content-Type: multipart/form-data
```

## 7. Troubleshooting

| Problème | Solution |
|----------|----------|
| Build échoue | Vérifier Node.js 18+ dans les settings Cloudflare |
| API unreachable | Vérifier que le Tunnel cloudflared tourne sur le DGX |
| CORS errors | Vérifier `ALLOWED_ORIGINS` dans le `.env` backend |
| 404 sur les routes | Ajouter `_redirects` : `/* /index.html 200` dans `public/` |
| Variables non chargées | Préfixe `VITE_` obligatoire pour les variables Vite |
