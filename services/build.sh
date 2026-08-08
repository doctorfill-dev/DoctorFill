#!/usr/bin/env bash
# Construit et démarre la stack en y injectant l'identité du build.
#
# La version seule ne suffit pas à savoir ce qui tourne : entre deux releases,
# plusieurs images portent la même. On y ajoute donc le commit et l'horodatage,
# visibles ensuite dans /health et dans l'en-tête de l'application.
#
#   ./build.sh              # build + up -d
#   ./build.sh orchestrator # limité à un service
set -euo pipefail

cd "$(dirname "$0")"

APP_VERSION=$(cat ../VERSION)
# --dirty : une image construite depuis un arbre modifié n'est reproductible
# depuis aucun commit, et doit le dire.
APP_COMMIT=$(git describe --always --dirty --abbrev=7 2>/dev/null || echo "")
APP_BUILT_AT=$(date -u +%Y-%m-%dT%H:%MZ)
export APP_VERSION APP_COMMIT APP_BUILT_AT

echo "Build ${APP_VERSION}+${APP_COMMIT:-inconnu} (${APP_BUILT_AT})"
docker compose build "$@"
docker compose up -d "$@"
