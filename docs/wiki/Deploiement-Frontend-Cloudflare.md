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

### API et clé

Le frontend appelle l'API sur sa propre origine, sous `/api/*`. La clé API
n'est plus dans le bundle (`VITE_API_KEY` n'est plus lu) :

- en production, la Pages Function `functions/api/[[path]].ts` relaie `/api/*`
  vers `https://api.doctorfill.ch` et ajoute la clé côté serveur, depuis le
  secret Pages `DOCTORFILL_API_KEY` ;
- en développement (`npm run dev`), Vite relaie `/api/*` vers l'orchestrateur
  local. Variables du shell, jamais incluses dans le bundle :

```bash
DOCTORFILL_API_URL=http://localhost:8080   # défaut
DOCTORFILL_API_KEY=...                     # seulement si l'API locale a une clé
```

`VITE_API_BASE_URL` permet encore de viser une autre URL (sans clé).

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

5. Ajouter le secret `DOCTORFILL_API_KEY` (*Settings → Variables and
   Secrets*, type *Secret*, environnement Production) : la clé de l'orchestrateur,
   lue par la Pages Function. Aucune variable `VITE_*` n'est nécessaire.

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

1. Le frontend fait un `fetch("/api/process-form", ...)` sur `doctorfill.ch`
   (derrière Cloudflare Access)
2. La Pages Function `functions/api/[[path]].ts` relaie vers
   `https://api.doctorfill.ch/process-form`, en flux (rien n'est mis en
   mémoire), avec l'en-tête `X-API-Key` tiré du secret `DOCTORFILL_API_KEY`
3. Cloudflare DNS résout `api.doctorfill.ch` vers le Tunnel, qui transmet à
   `localhost:8080` sur le DGX Spark

La fonction ne relaie que vers cet hôte fixe, ne sert que `doctorfill.ch` et
`www.doctorfill.ch`, ne transmet ni la clé envoyée par le client ni les
cookies, et ne journalise rien.

Limites Cloudflare qui s'appliquent (les mêmes qu'en appel direct à
`api.doctorfill.ch`, zone en plan Free) : corps de requête de 100 Mo au plus
par requête, réponse d'origine attendue 125 s au plus (erreur 524 au-delà).

## 7. Troubleshooting

| Problème | Solution |
|----------|----------|
| Build échoue | Vérifier Node.js 18+ dans les settings Cloudflare |
| API unreachable | Vérifier que le Tunnel cloudflared tourne sur le DGX |
| CORS errors | Vérifier `ALLOWED_ORIGINS` dans le `.env` backend |
| 404 sur les routes | Ajouter `_redirects` : `/* /index.html 200` dans `public/` |
| Variables non chargées | Préfixe `VITE_` obligatoire pour les variables Vite |
