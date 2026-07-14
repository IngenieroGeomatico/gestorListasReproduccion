# gestor-listas

Librería Python para leer listas de reproducción desde servicios de streaming
(Spotify, Deezer) y almacenarlas en un modelo de datos local en SQLite.

## Estructura

```
gestor_listas/
├── model.py            # Modelo de datos propio (Playlist, Track)
├── storage.py          # Persistencia en SQLite
├── sync.py             # Importación desde sources.json a SQLite
├── providers/
│   ├── base.py         # Clase abstracta Provider
│   ├── deezer.py       # Extracción desde Deezer (ARL / OAuth)
│   └── spotify.py      # Extracción desde Spotify (scraping / API)
├── importers/
│   └── spotify.py      # Importación de un modelo propio a Spotify
data/
├── gestor.db           # Base de datos SQLite (ignorada por git)
└── sources.json        # URLs de playlists a importar
```

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Modelo de datos

```python
from gestor_listas import Playlist, Track

track = Track(id="1", title="Song", artist="Artist", album="Album")
playlist = Playlist(id="pl1", name="Mi lista", tracks=[track])
```

- **Track**: `id`, `title`, `artist`, `album`, `duration_ms`, `isrc`, `uri`
- **Playlist**: `id`, `name`, `description`, `tracks`, `owner`, `public`,
  `created_at`, `updated_at`, `source`, `source_url`

## Cómo importar playlists a SQLite

### 1. Configura las fuentes en `data/sources.json`

```json
{
  "spotify": [
    "https://open.spotify.com/playlist/7jiU8AY3wG8kAHiWrSqEQL"
  ],
  "deezer": []
}
```

- **Spotify**: pega la URL completa de cada playlist pública que quieras importar.
- **Deezer**: si pones URLs las importa una a una; si el array está vacío
  importa **todas** tus playlists automáticamente (requiere ARL en `.env`).

### 2. Ejecuta la sincronización

```python
from gestor_listas import sync
sync.run()
```

Esto lee `sources.json`, obtiene las playlists de cada servicio y las guarda
en `data/gestor.db`. Es seguro ejecutarlo varias veces: actualiza los datos
si la playlist ya existe.

### 3. Consulta los datos

```python
from gestor_listas.storage import Storage

storage = Storage()
todas = storage.load_all_playlists()
de_spotify = storage.load_playlists_by_source("spotify")
pl = storage.load_playlist("id_de_la_playlist")
```

## Modos de autenticación

### Deezer

| Método | Cómo se configura |
|--------|-------------------|
| ARL (recomendado) | Poner `DEEZER_ARL` en `.env` (cookie del navegador) |
| Email + contraseña | Poner `DEEZER_EMAIL` y `DEEZER_PASSWORD` en `.env` (login automático) |
| OAuth | `DeezerProvider.authenticate(auto_save=True)` (requiere app en Deezer) |

El ARL se obtiene desde el navegador: DevTools → Application/Cookies →
`https://www.deezer.com` → copiar valor de la cookie `arl`.

### Spotify

La API oficial de Spotify exige que el propietario de la app tenga cuenta
Premium. Este proyecto ofrece alternativas que no lo requieren:

| Modo | Uso | Limitaciones |
|------|-----|-------------|
| **Scraping** (por defecto) | `SpotifyProvider(use_scraping=True)` | Solo lectura de playlists públicas por URL. Sin límites de tasa. |
| Bearer token | `SpotifyProvider(bearer_token="...")` o `SPOTIFY_BEARER_TOKEN` en `.env` | Token extraído del navegador (~1h de validez). Permite leer y escribir. |
| Client credentials | `SpotifyProvider(use_client_credentials=True)` | Usa credenciales de spotDL. Solo lectura pública. Sin límite de tasa tras 24h. |
| OAuth | `SpotifyProvider.authenticate()` | Requiere Premium. Bloqueado para cuentas Free. |

## Almacenamiento local

Los datos se guardan en `data/gestor.db` (SQLite) con tres tablas:

- **playlists**: metadatos de cada lista
- **tracks**: canciones de cada playlist
- **track_mappings**: relaciones entre IDs de Spotify y Deezer

## Tests

```bash
pytest -v
```

## Configuración

Copia `.env.example` a `.env` y completa las credenciales:

```bash
cp .env.example .env
```

Las variables más importantes:

| Variable | Descripción |
|----------|-------------|
| `DEEZER_ARL` | Cookie ARL de Deezer (lectura de playlists) |
| `SPOTIFY_BEARER_TOKEN` | Token Bearer de Spotify desde el navegador (opcional, para escritura) |

`.env` y `data/gestor.db` están en `.gitignore` para no subir credenciales ni
datos locales.
