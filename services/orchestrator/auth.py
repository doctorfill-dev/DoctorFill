"""
Authentification des requêtes et identité de l'appelant (issue 36).

Fermé par défaut : sans configuration, l'orchestrateur refuse de démarrer
(`check_settings`), et toute requête protégée reçoit 503.

Deux mécanismes, cumulables : chacun de ceux qui sont configurés doit passer.

- OIDC (cible) : jeton du fournisseur d'identité dans `Authorization: Bearer`.
  Signature vérifiée par les clés publiques du fournisseur (JWKS), émetteur,
  audience et expiration contrôlés. L'identité (`user_id`) et le cabinet
  (`cabinet_id`) viennent des revendications du jeton.
- Clé d'API partagée (transitoire) : en-tête `X-API-Key`, ajouté par le relais
  du frontend. Elle ne dit pas qui appelle : tous les appels partagent une même
  identité, donc aucun cloisonnement entre cabinets. À retirer avec le relais.

Variables d'environnement :
    OIDC_ISSUER, OIDC_AUDIENCE, OIDC_JWKS_URL   jetons du fournisseur d'identité
    OIDC_USER_CLAIM (défaut « sub »)            revendication portant l'utilisateur
    OIDC_CABINET_CLAIM (défaut « cabinet_id »)  revendication portant le cabinet
    API_KEY                                     clé partagée transitoire
"""

from __future__ import annotations

import asyncio
import os
import secrets
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import jwt
from fastapi import HTTPException, Request

# Identité unique des appels authentifiés par la seule clé partagée.
SHARED_KEY_IDENTITY = "cle-partagee"

# Taille maximale d'un identifiant repris d'un jeton (journal d'audit compris).
_MAX_ID_LEN = 128


@dataclass(frozen=True)
class Principal:
    """Qui appelle : un utilisateur, rattaché à un cabinet."""
    user_id: str
    cabinet_id: str
    method: str  # "oidc" ou "api_key"


@dataclass(frozen=True)
class AuthSettings:
    api_key: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    user_claim: str = "sub"
    cabinet_claim: str = "cabinet_id"
    algorithms: tuple[str, ...] = ("RS256", "ES256")
    leeway_seconds: int = 30

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer)

    @property
    def configured(self) -> bool:
        return bool(self.api_key) or self.oidc_enabled

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "AuthSettings":
        def get(name: str, default: str = "") -> str:
            return (env.get(name) or default).strip()
        return cls(
            api_key=get("API_KEY"),
            oidc_issuer=get("OIDC_ISSUER"),
            oidc_audience=get("OIDC_AUDIENCE"),
            oidc_jwks_url=get("OIDC_JWKS_URL"),
            user_claim=get("OIDC_USER_CLAIM", "sub"),
            cabinet_claim=get("OIDC_CABINET_CLAIM", "cabinet_id"),
        )


class AuthConfigError(RuntimeError):
    """Configuration d'authentification absente ou incomplète : le service ne démarre pas."""


def check_settings(settings: AuthSettings) -> None:
    """Refuse une configuration qui laisserait l'API ouverte ou à moitié configurée."""
    if not settings.configured:
        raise AuthConfigError(
            "Authentification non configurée : définir OIDC_ISSUER, OIDC_AUDIENCE et "
            "OIDC_JWKS_URL, ou, à titre transitoire, API_KEY. L'API ne démarre pas ouverte.")
    if settings.oidc_enabled and not (settings.oidc_audience and settings.oidc_jwks_url):
        raise AuthConfigError("OIDC incomplet : OIDC_AUDIENCE et OIDC_JWKS_URL sont requis "
                              "avec OIDC_ISSUER.")


# Configuration en vigueur. Lue au chargement ; les tests la remplacent.
settings = AuthSettings.from_env()

# token -> clé de vérification. Par défaut, les clés publiques du fournisseur
# (JWKS, mises en cache par PyJWT) ; les tests en injectent une autre.
KeyResolver = Callable[[str], Any]
key_resolver: KeyResolver | None = None
_jwks_clients: dict[str, jwt.PyJWKClient] = {}


def _default_resolver(current: AuthSettings) -> KeyResolver:
    client = _jwks_clients.get(current.oidc_jwks_url)
    if client is None:
        client = jwt.PyJWKClient(current.oidc_jwks_url, cache_keys=True, lifespan=300, timeout=10)
        _jwks_clients[current.oidc_jwks_url] = client
    return lambda token: client.get_signing_key_from_jwt(token).key


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _identifier(value: Any) -> str | None:
    """Identifiant lisible d'une revendication : chaîne non vide, ou liste d'un seul élément."""
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, (str, int)) and str(value).strip():
        return str(value).strip()[:_MAX_ID_LEN]
    return None


def verify_oidc_token(token: str, current: AuthSettings, resolver: KeyResolver) -> Principal:
    """Vérifie un jeton OIDC et en tire l'identité. Bloquant (JWKS) : à appeler dans un thread."""
    try:
        key = resolver(token)
        claims = jwt.decode(
            token, key,
            algorithms=list(current.algorithms),
            audience=current.oidc_audience,
            issuer=current.oidc_issuer,
            leeway=current.leeway_seconds,
            options={"require": ["exp", "iss", "aud", current.user_claim]},
        )
    except jwt.PyJWTError:
        # Signature, émetteur, audience, expiration ou clé inconnue : même réponse,
        # sans détail qui aiderait à forger un jeton.
        raise _unauthorized("Jeton d'authentification invalide ou expiré.")
    user_id = _identifier(claims.get(current.user_claim))
    if user_id is None:
        raise _unauthorized("Jeton d'authentification invalide ou expiré.")
    cabinet_id = _identifier(claims.get(current.cabinet_claim))
    if cabinet_id is None:
        raise HTTPException(status_code=403, detail="Compte rattaché à aucun cabinet.")
    return Principal(user_id=user_id, cabinet_id=cabinet_id, method="oidc")


def _check_api_key(request: Request, expected: str) -> bool:
    # Comparé en octets : compare_digest refuse une chaîne non ASCII.
    supplied = request.headers.get("X-API-Key", "").encode("utf-8")
    return secrets.compare_digest(supplied, expected.encode("utf-8"))


async def authenticate(request: Request) -> Principal:
    """Identité de l'appelant, ou HTTPException (401, 403, 503). Fermé par défaut."""
    current = settings
    if not current.configured:
        raise HTTPException(status_code=503, detail="Authentification non configurée.")
    if current.api_key and not _check_api_key(request, current.api_key):
        raise HTTPException(status_code=403, detail="API key invalide.")
    if not current.oidc_enabled:
        return Principal(user_id=SHARED_KEY_IDENTITY, cabinet_id=SHARED_KEY_IDENTITY, method="api_key")
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("Authentification requise.")
    resolver = key_resolver or _default_resolver(current)
    return await asyncio.to_thread(verify_oidc_token, token.strip(), current, resolver)


async def current_principal(request: Request) -> Principal:
    """Dépendance FastAPI des routes protégées."""
    return await authenticate(request)


async def optional_principal(request: Request) -> Principal | None:
    """Identité si la requête est authentifiée, None sinon (routes publiques)."""
    try:
        return await authenticate(request)
    except HTTPException:
        return None
