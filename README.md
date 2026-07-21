# gestor-listas

Librería y CLI en Python para leer listas de reproducción desde servicios de
streaming (Spotify, Deezer, YouTube), almacenarlas en un modelo de datos local
en SQLite, descargar sus canciones con metadatos y BPM (cálculo automático),
y crear playlists en Spotify o YouTube.

## Estructura

```
gestor_listas/
├── model.py            # Modelo de datos propio (Playlist, Track)
├── storage.py          # Persistencia en SQLite
├── sync.py             # Importación desde sources.json a SQLite
├── cli.py              # Interfaz de línea de comandos (gestor-listas)
├── config.py           # Configuración centralizada (variables de entorno)
├── errors.py           # Jerarquía de excepciones de dominio
├── http.py             # Sesiones HTTP con reintentos y backoff
├── audio.py            # Etiquetado ID3 y detección de BPM (ffmpeg + scipy)
├── bpm_analyzer.py     # Análisis y escritura de BPM en un directorio
├── providers/
│   ├── base.py         # Clase abstracta Provider
│   ├── deezer.py       # Extracción desde Deezer (ARL / email / OAuth)
│   ├── spotify.py      # Extracción desde Spotify (scraping / API)
│   └── youtube.py      # Extracción desde YouTube (yt-dlp)
├── importers/
│   ├── spotify.py      # Creación de playlists en Spotify
│   └── youtube.py      # Creación de playlists en YouTube (Data API v3)
├── downloaders/
│   ├── manager.py      # Orquestador de descargas (Deezer → YouTube)
│   ├── deezer.py       # Descarga y descifrado desde Deezer
│   └── youtube.py      # Descarga desde YouTube (yt-dlp)
data/
├── gestor.db           # Base de datos SQLite (ignorada por git)
└── sources.json        # URLs de playlists a importar
```

> **ffmpeg** se usa para descargar audio y analizar BPM. **No hace falta
> instalarlo aparte**: se incluye vía el paquete `imageio-ffmpeg` (multiplataforma).
> Si ya tienes un `ffmpeg` en el `PATH`, se usa ese preferentemente. La descarga
> desde YouTube usa **yt-dlp** (se instala con el paquete).

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
gestor-listas sync -s spotify            # Importar solo Spotify
gestor-listas sync -s spotify youtube    # Importar Spotify y YouTube
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
gestor-listas sync                  # Todos los proveedores
gestor-listas sync -s spotify       # Solo Spotify
gestor-listas sync -s spotify deezer  # Spotify y Deezer
```

O desde Python:

```python
from gestor_listas import sync
sync.run()                                   # Todos los proveedores
sync.run(sources_filter=["spotify"])          # Solo Spotify
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

El BPM se calcula **automáticamente** durante la descarga de cada canción (tanto
desde Deezer como desde YouTube). Para archivos existentes (o externos) puedes
usar el CLI o la API:

```bash
gestor-listas bpm ./downloads            # Analizar todo el directorio
gestor-listas bpm ./downloads -f         # Forzar re-análisis aunque ya tengan BPM
gestor-listas bpm ./downloads -e mp3,flac  # Solo ciertas extensiones
```

El algoritmo:
1. Decodifica el audio con `ffmpeg` a mono 22 kHz
2. Calcula la envolvente de onset por **flujo espectral** (STFT), que detecta los
   transitorios (kicks) mucho mejor que la energía RMS
3. Aplica autocorrelación sesgada sobre una **ventana ancha fija (60–240 BPM)**
4. **Tempo prior por familia de género**: pondera los picos con una campana
   log-normal (en log2 del BPM) centrada en el tempo típico del género. El
   género se clasifica en familias (balada, pop/rock, hip-hop/reggaeton,
   house/techno, trance, dnb, hardstyle...) a partir del **ID de Deezer** (camino
   principal, independiente del idioma) o del tag de texto del fichero. Esto
   resuelve los errores de octava según el estilo (que un hardstyle de 150 BPM no
   se detecte como 75, ni un house de 128 como 256).
5. **Soft prior sobre búsqueda ancha**: el prior solo *pondera*, nunca recorta la
   búsqueda; un tema mal etiquetado (o sin tag) sigue detectando su tempo real si
   su pico es fuerte. Sin género, se usa un prior ancho centrado en ~125 BPM.
6. **Interpolación parabólica** del pico para precisión sub-lag.

### ¿Qué pasa con un género que no está en el código?

El género tiene dos usos distintos y ninguno falla ante un valor desconocido:

- **Etiqueta ID3 (solo descargas de Deezer):** el nombre se traduce del `GENRE_ID`
  con `DEEZER_GENRE_MAP`. Si el ID no está en el mapa, **no se inventa**: se omite
  el tag de género y se registra un `logging.info` con el ID para poder añadirlo.
- **Familia de tempo (para el prior de BPM):** `classify_genre` clasifica en cadena
  con degradación segura:
  1. **ID de Deezer → familia** (`DEEZER_TO_FAMILY_MAP`, independiente del idioma).
  2. Si el ID no está mapeado pero **sí tiene nombre**, se intenta por ese nombre
     vía palabras clave (`TEXT_TO_FAMILY_KEYWORDS`).
  3. Si aún no encaja → familia `unknown` (prior ancho ~125 BPM), registrando un
     `logging.debug` con el género no reconocido.

Por ejemplo, **flamenco** (ID 36) está mapeado a `unknown` *a propósito*: su compás
es demasiado variable (bulerías rápidas, soleá lenta) para un prior estrecho, así
que el prior ancho es la mejor opción. No es un olvido, es una decisión.

**Cómo añadir o reclasificar un género** (en `gestor_listas/audio.py`):

| Si viene como… | Edita… | Ejemplo |
|----------------|--------|---------|
| ID de Deezer | `DEEZER_TO_FAMILY_MAP` | `36: "hiphop_reggaeton"` |
| Nombre para el tag | `DEEZER_GENRE_MAP` | `210: "Nuevo Género"` |
| Tag de texto del usuario | `TEXT_TO_FAMILY_KEYWORDS[familia]` | añadir `"flamenco"` |

Activa `logging.basicConfig(level=logging.DEBUG)` para ver qué géneros caen en
`unknown` y decidir si merece la pena mapearlos.

Formatos soportados: `mp3`, `flac`, `ogg`, `opus`, `m4a`, `aac`, `wav`, `wma`.

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
| Client credentials | `SpotifyProvider(use_client_credentials=True)` | Usa credenciales públicas de spotDL (sobrescribibles con `SPOTDL_CLIENT_ID`/`SPOTDL_CLIENT_SECRET`). Solo lectura pública. Sin límite de tasa tras 24h. |
| OAuth | `SpotifyProvider.authenticate()` | Requiere Premium. Bloqueado para cuentas Free. |

### YouTube

No requiere credenciales para **leer** playlists públicas ni **descargar** audio
(usa `yt-dlp`). Si tienes `deno` instalado, se usa automáticamente como runtime de
JS para sortear algunas restricciones de extracción.

Para **crear** playlists en tu cuenta sí hace falta OAuth (ver más abajo).

## Crear playlists (importadores)

Además de leer, puedes volcar un modelo `Playlist` propio a Spotify o YouTube.
Esto **escribe** en tu cuenta, así que requiere autenticación.

### YouTube

Crear playlists usa la **YouTube Data API v3** (yt-dlp solo lee). Puesta en marcha
(una sola vez):

1. Crea un proyecto en [Google Cloud Console](https://console.cloud.google.com/).
2. Habilita **YouTube Data API v3**.
3. Crea credenciales **OAuth** de tipo "Aplicación de escritorio".
4. Pon `YOUTUBE_CLIENT_ID` y `YOUTUBE_CLIENT_SECRET` en tu `.env`.
5. Autoriza una vez y guarda el refresh token:

```python
from gestor_listas.importers.youtube import YouTubeImporter
YouTubeImporter.authenticate(auto_save=True)  # abre el navegador, pega el código
```

Después ya puedes importar cualquier playlist:

```python
from gestor_listas.importers.youtube import YouTubeImporter
from gestor_listas.storage import Storage

with Storage() as storage:
    pl = storage.load_playlist("id_de_una_playlist")

importer = YouTubeImporter()
nueva = importer.import_playlist(pl, name="Copia en YouTube", public=False)
print(nueva.source_url)
```

Busca cada canción en YouTube (o usa su URL si ya la tiene) y la añade a la lista
creada. **Cuota:** la API da 10.000 unidades/día; crear + buscar + añadir consume
~150-200 por canción, así que listas grandes pueden agotar la cuota diaria (se
avisa con un error claro).

### Spotify

`SpotifyImporter` crea la playlist y añade las pistas (por URI o buscándolas).
Requiere un modo de escritura de Spotify (bearer token u OAuth, ver tabla arriba).

## Almacenamiento local

Los datos se guardan en `data/gestor.db` (SQLite, modo WAL) con dos tablas:

- **playlists**: metadatos de cada lista
- **tracks**: canciones de cada playlist (con `position` para preservar el orden)

`Storage` es un context manager, por lo que la conexión se cierra sola:

```python
from gestor_listas.storage import Storage

with Storage() as storage:
    playlists = storage.load_all_playlists()
```

## Manejo de errores

La librería lanza excepciones de dominio (en `gestor_listas.errors`), lo que
permite capturarlas con precisión:

```python
from gestor_listas import sync
from gestor_listas import AuthError, ProviderError, GestorListasError

try:
    sync.run()
except AuthError:
    ...   # credenciales inválidas o expiradas
except ProviderError:
    ...   # fallo al leer datos de un servicio
except GestorListasError:
    ...   # cualquier otro error de la librería
```

Jerarquía: `GestorListasError` → `ConfigError`, `ProviderError`
(→ `AuthError`, `PlaylistNotFoundError`), `DownloadError`.

## Logging

La librería no imprime a stdout: emite mensajes mediante el módulo `logging`
(los `print` quedan solo en la CLI). Para ver la actividad, configura logging
en tu aplicación:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

## Concurrencia

La sincronización y las descargas aceptan `max_workers` para paralelizar la
parte de red (I/O-bound). Las escrituras en SQLite se mantienen secuenciales.

```python
from gestor_listas import sync
sync.run(max_workers=4)          # importa varias playlists en paralelo

from gestor_listas.downloaders import DownloadManager
DownloadManager(max_workers=4)   # descarga varias pistas en paralelo
```

## Tests

Instala las dependencias de desarrollo y ejecuta la suite:

```bash
pip install -e ".[dev]"
pytest
```

La configuración de `pytest` (en `pyproject.toml`) mide la cobertura y exige un
mínimo del **70%** (`--cov-fail-under=70`). Para ver el informe detallado:

```bash
pytest --cov-report=term-missing
```

Las pruebas que necesitan red o binarios externos (`ffmpeg`, `yt-dlp`) están
marcadas como `integration` y **no** se ejecutan por defecto. Para incluirlas:

```bash
pytest -m integration
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
| `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` | Credenciales OAuth de Google (solo para **crear** playlists en YouTube) |
| `YOUTUBE_REFRESH_TOKEN` | Token de refresco de YouTube (lo genera `YouTubeImporter.authenticate`) |

Para **leer y descargar** de YouTube no hace falta ninguna variable; solo para
**crear** playlists.

### Cómo obtener cada credencial

#### Deezer — `DEEZER_ARL` (recomendado)

Es la cookie de sesión de tu navegador. La forma más rápida:

1. Abre <https://www.deezer.com> en Chrome/Firefox/Edge e inicia sesión.
2. Abre las DevTools con **F12**.
3. Ve a la pestaña **Application** (Chrome/Edge) o **Storage** (Firefox).
4. En el árbol de la izquierda: **Cookies → https://www.deezer.com**.
5. Busca la cookie llamada **`arl`** y copia su **Value** (una cadena larga).
6. Pégala en `.env`: `DEEZER_ARL=el_valor_copiado`.

> El ARL caduca cada cierto tiempo; si deja de funcionar, repite el proceso.

#### Deezer — `DEEZER_EMAIL` / `DEEZER_PASSWORD` (alternativa)

Simplemente tu email y contraseña de Deezer. La librería inicia sesión y obtiene
el ARL automáticamente. No funciona si Deezer pide CAPTCHA (en ese caso usa el
ARL manual de arriba).

#### Deezer — OAuth (`DEEZER_APP_ID` / `DEEZER_APP_SECRET` / `DEEZER_ACCESS_TOKEN`)

Solo si prefieres OAuth oficial:

1. Entra en <https://developers.deezer.com/myapps> y crea una aplicación.
2. Copia el **Application ID** → `DEEZER_APP_ID` y el **Secret Key** → `DEEZER_APP_SECRET`.
3. Genera el token ejecutando `DeezerProvider.authenticate(auto_save=True)` (abre
   el navegador y guarda `DEEZER_ACCESS_TOKEN` en `.env`).

#### Spotify — `SPOTIFY_BEARER_TOKEN` (para escritura, ~1h de validez)

Token temporal extraído del navegador:

1. Abre <https://open.spotify.com> con sesión iniciada y las DevTools (**F12**).
2. Ve a la pestaña **Network** y filtra por `api.spotify.com`.
3. Recarga la página y pincha en cualquier petición a `api.spotify.com`.
4. En **Request Headers** copia el valor de `authorization:` que va después de
   `Bearer ` (solo el token, sin la palabra "Bearer").
5. Pégalo en `.env`: `SPOTIFY_BEARER_TOKEN=el_token`.

> Caduca en ~1 hora; es la opción rápida para pruebas puntuales de escritura.

#### Spotify — OAuth (`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`)

1. Entra en <https://developer.spotify.com/dashboard> y crea una app.
2. Copia el **Client ID** → `SPOTIFY_CLIENT_ID` y el **Client Secret** →
   `SPOTIFY_CLIENT_SECRET`.
3. En *Settings* de la app añade el **Redirect URI** `http://localhost:8888/callback`.
4. Ejecuta `SpotifyProvider.authenticate(auto_save=True)` para generar el refresh
   token (requiere cuenta Premium para escritura completa).

#### YouTube — `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` / `YOUTUBE_REFRESH_TOKEN`

Solo para **crear** playlists. Se obtienen desde Google Cloud:

1. Entra en <https://console.cloud.google.com/> y crea (o elige) un proyecto.
2. En **APIs y servicios → Biblioteca**, busca y habilita **YouTube Data API v3**.
3. En **APIs y servicios → Pantalla de consentimiento OAuth**, configúrala (tipo
   *Externo* basta) y añádete como *usuario de prueba* con tu cuenta de Google.
4. En **APIs y servicios → Credenciales → Crear credenciales → ID de cliente
   OAuth**, elige el tipo **Aplicación de escritorio**.
5. Copia el **ID de cliente** → `YOUTUBE_CLIENT_ID` y el **Secreto de cliente** →
   `YOUTUBE_CLIENT_SECRET` en `.env`.
6. Genera el refresh token (una sola vez):

```python
from gestor_listas.importers.youtube import YouTubeImporter
YouTubeImporter.authenticate(auto_save=True)  # abre el navegador, pega el código
```

Esto guarda `YOUTUBE_REFRESH_TOKEN` en `.env` automáticamente.

`.env` y `data/gestor.db` están en `.gitignore` para no subir credenciales ni
datos locales.

## Aviso legal

La descarga de audio protegido por derechos de autor puede infringir los
términos de servicio de cada plataforma y la legislación aplicable. Usa estas
funciones únicamente con contenido sobre el que tengas derechos. El proyecto se
ofrece con fines educativos y de uso personal.
