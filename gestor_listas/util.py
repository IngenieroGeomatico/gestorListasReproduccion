"""Utilidades compartidas de gestor-listas."""

from __future__ import annotations

# Caracteres inválidos en nombres de fichero en Windows (y problemáticos en
# otros SO): además de la barra y el NUL, Windows prohíbe \ : * ? " < > | .
_INVALID_FILENAME_CHARS = '/\\:*?"<>|\0'
_INVALID_TABLE = {ord(c): "_" for c in _INVALID_FILENAME_CHARS}

# Nombres reservados de Windows (case-insensitive, con o sin extensión).
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def safe_filename(name: str, max_length: int = 200, fallback: str = "untitled") -> str:
    """Convierte un texto arbitrario en un nombre de fichero/carpeta seguro.

    - Reemplaza los caracteres inválidos en Windows/Unix por '_'.
    - Recorta espacios y puntos finales (Windows los descarta silenciosamente).
    - Evita colisionar con nombres reservados de Windows (CON, NUL, ...).
    - Trunca a `max_length` caracteres.
    - Si el resultado queda vacío, devuelve `fallback`.

    No incluye la extensión: pásala aparte al construir la ruta final.
    """
    cleaned = name.translate(_INVALID_TABLE).strip().rstrip(".")
    cleaned = cleaned[:max_length].strip().rstrip(".")

    # Un nombre compuesto solo de separadores ('_', espacios) no aporta
    # información: se trata como vacío y se usa el fallback.
    if not cleaned or not cleaned.strip("_ "):
        return fallback

    stem = cleaned.split(".", 1)[0]
    if stem.upper() in _WINDOWS_RESERVED:
        return f"_{cleaned}"

    return cleaned
