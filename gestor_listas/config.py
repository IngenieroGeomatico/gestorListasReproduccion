"""Configuración centralizada de gestor-listas.

Toda la lectura de variables de entorno vive aquí, en un único sitio testeable.
`load_dotenv()` se invoca una sola vez al importar este módulo, en lugar de como
efecto secundario disperso por los providers.

Las funciones leen el entorno en el momento de llamarse (no al importar), para
que los tests puedan modificar `os.environ` y ver el cambio reflejado.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

# Carga el .env una única vez para toda la librería.
load_dotenv()

# Credenciales públicas de client-credentials que usa spotDL (no son secretas ni
# personales). Se pueden sobrescribir con SPOTDL_CLIENT_ID / SPOTDL_CLIENT_SECRET.
_DEFAULT_SPOTDL_CLIENT_ID = "5f573c9620494bae87890c0f08a60293"
_DEFAULT_SPOTDL_CLIENT_SECRET = "212476d9b0f3472eaa762d90b19b0ba8"

_DEFAULT_SPOTIFY_REDIRECT = "http://localhost:8888/callback"
_DEFAULT_DEEZER_REDIRECT = "https://example.com/"


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name, default)
    return value if value else default


@dataclass(frozen=True)
class SpotifyConfig:
    client_id: str = ""
    client_secret: str = ""
    bearer_token: Optional[str] = None
    refresh_token: Optional[str] = None
    redirect_uri: str = _DEFAULT_SPOTIFY_REDIRECT
    spotdl_client_id: str = _DEFAULT_SPOTDL_CLIENT_ID
    spotdl_client_secret: str = _DEFAULT_SPOTDL_CLIENT_SECRET

    @classmethod
    def from_env(cls) -> "SpotifyConfig":
        return cls(
            client_id=_env("SPOTIFY_CLIENT_ID", "") or "",
            client_secret=_env("SPOTIFY_CLIENT_SECRET", "") or "",
            bearer_token=_env("SPOTIFY_BEARER_TOKEN"),
            refresh_token=_env("SPOTIFY_REFRESH_TOKEN"),
            redirect_uri=_env("SPOTIFY_REDIRECT_URI", _DEFAULT_SPOTIFY_REDIRECT) or _DEFAULT_SPOTIFY_REDIRECT,
            spotdl_client_id=_env("SPOTDL_CLIENT_ID", _DEFAULT_SPOTDL_CLIENT_ID) or _DEFAULT_SPOTDL_CLIENT_ID,
            spotdl_client_secret=_env("SPOTDL_CLIENT_SECRET", _DEFAULT_SPOTDL_CLIENT_SECRET) or _DEFAULT_SPOTDL_CLIENT_SECRET,
        )


@dataclass(frozen=True)
class DeezerConfig:
    arl: Optional[str] = None
    access_token: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    app_id: str = ""
    app_secret: str = ""
    redirect_uri: str = _DEFAULT_DEEZER_REDIRECT

    @classmethod
    def from_env(cls) -> "DeezerConfig":
        return cls(
            arl=_env("DEEZER_ARL"),
            access_token=_env("DEEZER_ACCESS_TOKEN"),
            email=_env("DEEZER_EMAIL"),
            password=_env("DEEZER_PASSWORD"),
            app_id=_env("DEEZER_APP_ID", "") or "",
            app_secret=_env("DEEZER_APP_SECRET", "") or "",
            redirect_uri=_env("DEEZER_REDIRECT_URI", _DEFAULT_DEEZER_REDIRECT) or _DEFAULT_DEEZER_REDIRECT,
        )
