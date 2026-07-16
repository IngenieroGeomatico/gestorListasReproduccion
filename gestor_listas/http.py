"""Sesiones HTTP con reintentos y backoff exponencial.

Las APIs no oficiales de Spotify y Deezer fallan de forma intermitente
(límites de tasa 429, errores 5xx transitorios). `make_session()` devuelve una
`requests.Session` que reintenta automáticamente esos casos con backoff.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_USER_AGENT = "Mozilla/5.0"

# Métodos idempotentes que es seguro reintentar. POST se incluye porque las
# APIs GW de Deezer/Spotify lo usan para operaciones de lectura idempotentes.
_RETRY_METHODS = frozenset({"GET", "POST", "HEAD", "OPTIONS"})
_RETRY_STATUS = (429, 500, 502, 503, 504)


def make_session(
    total_retries: int = 3,
    backoff_factor: float = 0.5,
    user_agent: str | None = None,
) -> requests.Session:
    """Crea una Session con reintentos automáticos y backoff exponencial.

    - total_retries: número máximo de reintentos por petición.
    - backoff_factor: espera base; el retraso crece como backoff_factor * 2**n.
    - user_agent: cabecera User-Agent (por defecto un UA de navegador genérico).
    """
    session = requests.Session()
    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        status=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=_RETRY_STATUS,
        allowed_methods=_RETRY_METHODS,
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": user_agent or DEFAULT_USER_AGENT})
    return session
