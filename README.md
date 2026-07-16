# gestor-listas

Librería y CLI en Python para leer listas de reproducción desde servicios de
streaming (Spotify, Deezer, YouTube), almacenarlas en un modelo de datos local
en SQLite, descargar sus canciones con metadatos y analizar su BPM.

## Estructura

```
gestor_listas/
├── model.py            # Modelo de datos propio (Playlist, Track)
├── storage.py          # Persistencia en SQLite
├── sync.py             # Importación desde sources.json a SQLite
├── cli.py              # Interfaz de línea de comandos (gestor-listas)
├── audio.py            # Etiquetado ID3 y detección de BPM (ffmpeg + scipy)
├── bpm_analyzer.py     # Análisis y escritura de BPM en un directorio
├── providers/
│   ├── base.py         # Clase abstracta Provider
│   ├── deezer.py       # Extracción desde Deezer (ARL / email / OAuth)
│   ├── spotify.py      # Extracción desde Spotify (scraping / API)
│   └── youtube.py      # Extracción desde YouTube (yt-dlp)
├── importers/
│   └── spotify.py      # Importación de un modelo propio a Spotify
├── downloaders/
│   ├── manager.py      # Orquestador de descargas (Deezer → YouTube)
│   ├── deezer.py       # Descarga y descifrado desde Deezer
│   └── youtube.py      # Descarga desde YouTube (yt-dlp)
data/
├── gestor.db           # Base de datos SQLite (ignorada por git)
└── sources.json        # URLs de playlists a importar
```

> Requisito externo: **ffmpeg** debe estar en el `PATH` para descargar audio y
> analizar BPM. La descarga desde YouTube usa **yt-dlp** (se instala con el paquete).

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

## Uso por línea de comandos (CLI)

Al instalar el paquete se registra el comando `gestor-listas`:

```bash
gestor-listas sync                       # Importar playlists de sources.json a SQLite
gestor-listas list                       # Listar playlists almacenadas
gestor-listas list -s spotify            # Filtrar por fuente (spotify/deezer/youtube)
gestor-listas download                   # Descargar canciones de todas las playlists
gestor-listas download -p <playlist_id>  # Descargar solo una playlist
gestor-listas download --prefer youtube  # Preferir YouTube sobre Deezer
gestor-listas download --limit 10        # Descargar solo los primeros 10 temas
gestor-listas bpm ./downloads            # Analizar y etiquetar BPM de un directorio
```

Opciones de `download`: `-o/--output` (carpeta destino, por defecto `downloads`),
`--no-subfolder`, `-f/--format` (`best`/`opus`/`mp3`/`m4a`). Opciones de `bpm`:
`-r/--recursive` (por defecto), `--no-recursive`, `-f/--force`, `-e/--extensions`.

## Cómo importar playlists a SQLite

### 1. Configura las fuentes en `data/sources.json`

```json
{
  "spotify": [
    "https://open.spotify.com/playlist/7jiU8AY3wG8kAHiWrSqEQL"
  ],
  "deezer": [],
  "youtube": [
    "https://www.youtube.com/playlist?list=PLxxxxxxxx"
  ]
}
```

- **Spotify**: pega la URL completa de cada playlist pública que quieras importar.
- **Deezer**: si pones URLs las importa una a una; si el array está vacío
  importa **todas** tus playlists automáticamente (requiere ARL en `.env`).
- **YouTube**: pega la URL de cada playlist que quieras importar (usa `yt-dlp`).

### 2. Ejecuta la sincronización

Desde la CLI:

```bash
gestor-listas sync
```

O desde Python:

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

## Descarga de canciones

El `DownloadManager` intenta descargar cada tema desde la fuente preferida y,
si falla, prueba la siguiente:

```python
from gestor_listas.downloaders import DownloadManager

manager = DownloadManager(output_dir="downloads", prefer="deezer", audio_format="best")
results = manager.download_from_storage(source="spotify", limit=10)
```

- **Deezer**: descarga y descifra el stream (requiere ARL válido) y escribe
  etiquetas ID3 completas (título, artista, álbum, año, carátula, género, BPM).
- **YouTube**: descarga con `yt-dlp` (audio nativo por defecto, o recodificado a
  `opus`/`mp3`/`m4a`) y calcula el BPM tras la descarga.

## Análisis de BPM

`bpm_analyzer.analyze_directory()` recorre una carpeta, calcula el BPM de cada
archivo de audio (vía `ffmpeg` + autocorrelación de energía) y lo escribe en sus
etiquetas. Formatos soportados: `mp3`, `flac`, `ogg`, `m4a`, `wav`, `opus`, `wma`.

```python
from pathlib import Path
from gestor_listas.bpm_analyzer import analyze_directory

stats = analyze_directory(Path("downloads"), recursive=True, force=False)
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

### YouTube

No requiere credenciales. Usa `yt-dlp` para leer playlists públicas y descargar
audio. Si tienes `deno` instalado, se usa automáticamente como runtime de JS para
sortear algunas restricciones de extracción.

## Almacenamiento local

Los datos se guardan en `data/gestor.db` (SQLite, modo WAL) con tres tablas:

- **playlists**: metadatos de cada lista
- **tracks**: canciones de cada playlist (con `position` para preservar el orden)
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
| `DEEZER_ARL` | Cookie ARL de Deezer (lectura y descarga de playlists) |
| `DEEZER_EMAIL` / `DEEZER_PASSWORD` | Credenciales de Deezer para login automático (alternativa al ARL) |
| `SPOTIFY_BEARER_TOKEN` | Token Bearer de Spotify desde el navegador (opcional, para escritura) |

YouTube no necesita ninguna variable de entorno.

`.env` y `data/gestor.db` están en `.gitignore` para no subir credenciales ni
datos locales.

## Aviso legal

La descarga de audio protegido por derechos de autor puede infringir los
términos de servicio de cada plataforma y la legislación aplicable. Usa estas
funciones únicamente con contenido sobre el que tengas derechos. El proyecto se
ofrece con fines educativos y de uso personal.
