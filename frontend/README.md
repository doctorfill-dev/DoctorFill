# Frontend DoctorFill

Application React + Tauri pour l'auto-remplissage de formulaires médicaux.

## Stack

| Technologie | Version | Usage |
|-------------|---------|-------|
| React | 19.1 | Framework UI |
| Vite | 7.0 | Build tool |
| TypeScript | 5.8 | Typage |
| Tailwind CSS | 3.4 | Styles |
| shadcn/ui | 4.0 | Composants UI |
| Tauri | 2.x | App desktop |
| Geist | Variable | Typographie |

## Commandes

```bash
# Installation des dépendances
npm install

# Développement web (http://localhost:5173)
npm run dev

# Build production (output: dist/)
npm run build

# Preview du build
npm run preview

# Développement desktop (Tauri)
npm run tauri dev

# Build desktop
npm run tauri build
```

## Configuration

### Variables d'environnement

L'interface appelle l'API sous `/api/*`, sur sa propre origine : en production
via la Pages Function `../functions/api/[[path]].ts` (qui ajoute la clé API côté
serveur), en développement via le proxy de Vite. Pour `npm run dev`, variables
du shell (jamais incluses dans le bundle) :

```bash
DOCTORFILL_API_URL=http://localhost:8080   # défaut
DOCTORFILL_API_KEY=...                     # seulement si l'API locale a une clé
```

La clé API n'est plus une variable `VITE_*` : tout ce qui porte ce préfixe finit
dans le bundle.

## Déploiement

### Cloudflare Pages

```bash
npm run build
# Le dossier dist/ est déployé automatiquement via Cloudflare Pages
```

Voir [Déploiement Frontend](../docs/wiki/Deploiement-Frontend-Cloudflare.md) pour la configuration complète.

### Mobile (expérimental)

```bash
npm run tauri android init    # Initialisation Android
npm run tauri ios init        # Initialisation iOS
npm run tauri android dev     # Dev Android
npm run tauri ios dev         # Dev iOS
```

## Design system

Voir [design.md](design.md) pour la documentation complète du design system "Zinc / Emerald".
