"""Jerarquía de excepciones de dominio de gestor-listas.

Permite a quien consume la librería capturar errores con precisión:

    try:
        sync.run()
    except AuthError:
        ...        # credenciales inválidas o expiradas
    except ProviderError:
        ...        # fallo al leer datos de un servicio
    except GestorListasError:
        ...        # cualquier error de la librería
"""

from __future__ import annotations


class GestorListasError(Exception):
    """Excepción base de la librería. Captúrala para atrapar cualquier error propio."""


class ConfigError(GestorListasError):
    """Configuración inválida o incompleta (variables de entorno, rutas, etc.)."""


class ProviderError(GestorListasError):
    """Fallo al interactuar con un proveedor de streaming (Spotify/Deezer/YouTube)."""


class AuthError(ProviderError):
    """Credenciales ausentes, inválidas o expiradas."""


class PlaylistNotFoundError(ProviderError, ValueError):
    """La playlist solicitada no existe, no es accesible o su URL es inválida.

    Hereda también de ValueError por compatibilidad con código que capturaba
    ValueError al parsear URLs de playlist.
    """


class DownloadError(GestorListasError):
    """Fallo al descargar o procesar una pista de audio."""
