# TODO

Lista de tareas pendientes de `gestor-listas`. Marcadas por prioridad y con el
contexto necesario para retomarlas.

---

### Mejorar detección de BPM

- [x] Arreglado escritura BPM en `.opus` (usar `OggOpus` en lugar de `OggVorbis`)
- [x] Arreglada lectura de BPM en `.flac` y `.opus` (no leía la clave del tag)
- [x] **Rediseño del algoritmo (sin librosa):** sustituida la envolvente de energía
      RMS por **flujo espectral** (STFT) — detecta mucho mejor los kicks de EDM.
      Añadido **tempo prior log-normal** que resuelve errores de octava, con perfil
      según género (EDM ~155 BPM vs balanceado ~125), leyendo el género de los
      metadatos del fichero de forma transversal. Interpolación parabólica del pico
      para precisión sub-lag. Validado con señales sintéticas 90-175 BPM (±2 BPM).
- [x] **Sistema multi-familia de priors por género (sustituye el binario EDM):**
      9 familias (balada, hiphop_reggaeton, pop_rock, dance_pop, house_techno,
      trance, dnb, hardstyle_hardcore, unknown), cada una con su `TempoPrior`
      (`center/sigma/min_bpm/max_bpm`). Clasificación vía `classify_genre`: camino
      primario por **ID de Deezer** (`DEEZER_TO_FAMILY_MAP`, independiente del
      idioma) y fallback por keywords de texto con precedencia explícita
      (`FAMILY_KEYWORD_PRECEDENCE`). Cambio clave: la autocorrelación usa una
      **ventana ancha fija** (`BPM_SEARCH_WINDOW` 60-240) y el prior solo pondera
      (soft prior), así un tema mal etiquetado nunca queda fuera de rango. Sin tag
      → prior `unknown` ancho ~125 BPM. `_PRIOR_EDM`/`_PRIOR_DEFAULT`/`is_edm_genre`
      se mantienen como compatibilidad. Validado con señales sintéticas por familia
      (75-174 BPM, ±2 BPM). Falta validar con música real (ver abajo).

#### Validación pendiente del nuevo algoritmo de BPM

El rediseño está probado con **señales sintéticas** (kicks limpios generados por
código), lo que confirma que la matemática es correcta, pero **aún no se ha
validado con música real**. Pruebas necesarias antes de darlo por bueno:

- [ ] **Batería de referencia con BPM conocido.** Reunir 15-20 temas cuyo BPM real
      se conozca (de la carátula, Beatport, MixMeister o contando a mano),
      cubriendo: hardstyle/hardcore (150-180), techno (125-150), trance/remember
      (138-150), house (120-128), pop/rock (90-130) y alguna balada (70-90).
      Ejecutar `detect_bpm` en cada uno y anotar detectado vs real.
- [ ] **Medir tasa de acierto.** Objetivo: acierto exacto (±2 BPM) y detectar
      errores de octava (mitad/doble). Registrar % de aciertos por género para
      saber dónde falla.
- [ ] **Casos límite explícitos:**
      - Tema EDM **sin tag de género** → cae en el prior `unknown` (ancho, ~125,
        rango 60-220); verificar que aun así acierta o documentar si necesita el tag.
      - Género en el tag que **no** encaje en ninguna familia (subgéneros raros) →
        cae en `unknown`; ampliar `TEXT_TO_FAMILY_KEYWORDS`/`DEEZER_TO_FAMILY_MAP`
        si una familia concreta acierta mejor.
      - Temas con **intro larga sin percusión** (los primeros 60 s son ambient):
        `detect_bpm` solo analiza `max_duration=60` s desde el inicio. Evaluar si
        conviene saltar la intro o analizar un tramo central.
      - Temas con **cambios de tempo** o breakdowns → confirmar comportamiento.
- [ ] **Calibrar priors de familia con datos reales.** Ajustar los `TempoPrior` de
      `FAMILIES` (center, sigma, min/max_bpm) en `audio.py` según los resultados de
      la batería. Los valores actuales están fundamentados en distribuciones de
      tempo típicas pero solo validados con señales sintéticas.
- [ ] **Afinar `classify_genre`** con géneros reales: revisar la precedencia de
      `FAMILY_KEYWORD_PRECEDENCE` y ampliar `DEEZER_TO_FAMILY_MAP` con más IDs.
- [ ] **Comparar contra el algoritmo viejo** en los mismos temas, para confirmar
      que el nuevo mejora de verdad y no introduce regresiones en música normal.
- [ ] **Comando de validación reproducible.** Considerar un pequeño script o test
      `integration` que reciba una carpeta con un CSV `fichero,bpm_real` y reporte
      la tasa de acierto, para poder re-validar tras cada cambio de parámetros.
- [ ] **Verificar re-análisis con `-f`.** `gestor-listas bpm ./downloads -f` debe
      recalcular y sobreescribir BPMs viejos correctamente en todos los formatos
      (mp3/flac/opus/ogg/m4a).

## Verificación end-to-end pendiente

Estas partes están implementadas y con tests (mocks), pero **no se han probado
contra el servicio real** por falta de credenciales/binarios en el entorno.

- [ ] **Deezer: lectura real de playlists.** Configurar `DEEZER_ARL` en `.env` y
      ejecutar `pytest -m integration` (el test `TestDeezerReal` dejará de omitirse).
- [ ] **Deezer: descarga real de audio.** Requiere ARL válido + `ffmpeg` (ya viene
      con `imageio-ffmpeg`). Verificar descarga + descifrado + etiquetado ID3.
- [ ] **YouTube: creación real de playlists.** Configurar credenciales OAuth de
      Google Cloud (`YOUTUBE_CLIENT_ID/SECRET`), generar `YOUTUBE_REFRESH_TOKEN`
      con `YouTubeImporter.authenticate(auto_save=True)` y probar `import_playlist`.
- [ ] **Spotify: modo client-credentials.** En la prueba real se colgó (posible
      rate-limit o credenciales spotDL caducadas). Revisar timeout y fiabilidad;
      considerar deprecarlo si no es estable.

---

## Infraestructura (recomendado, alto ROI)

Bloque propuesto y aún no implementado. Multiplica la seguridad de los 184 tests.

- [ ] **CI con GitHub Actions.** Workflow que en cada push/PR ejecute `pytest`
      (umbral de cobertura 70% ya configurado) + lint. Es lo que más falta.
- [ ] **Linter + formateador (Ruff).** Configurar en `pyproject.toml`. El
      `.gitignore` ya prevé `.ruff_cache`.
- [ ] **Type checking (mypy o basedpyright).** El código ya tiene type hints por
      todas partes; falta verificarlos en CI.
- [ ] **pre-commit hooks.** Ejecutar ruff/mypy antes de cada commit local.
- [ ] **CHANGELOG.md.** Trackear versiones (el proyecto está en 0.1.0).

---

## Código / arquitectura

- [ ] **Importer CLI.** Exponer la creación de playlists (Spotify/YouTube) como
      subcomando de `gestor-listas` (hoy solo es API de Python).
- [ ] **Deezer: descarga con calidad configurable.** Ahora está fijo a MP3 128.
      Permitir MP3 320 / FLAC si la cuenta lo soporta.
- [ ] **`track_mappings`.** Se eliminó la tabla; si se quiere el emparejamiento
      Spotify↔Deezer por ISRC, implementarlo de verdad (modelo + persistencia).
- [ ] **Reintentos configurables por proveedor.** `http.make_session` usa valores
      fijos; permitir ajustarlos desde config.
- [ ] **Migrar BPM a Python puro (opcional).** Evaluado `miniaudio` para eliminar
      también la decodificación vía ffmpeg (hoy resuelta con `imageio-ffmpeg`).

---

## Tests / cobertura

- [ ] **Subir cobertura de `cli.py`** (excluido hoy del report) y de
      `providers/spotify.py` (64%).
- [ ] **Tests de integración para el importer de YouTube** (requieren credenciales
      reales; hoy solo hay tests con mocks).

---

## Documentación

- [ ] **Ejemplos de uso end-to-end** en el README (flujo completo: sync → download
      → crear playlist en otro servicio).
- [ ] **Guía de troubleshooting** (ARL caducado, cuota de YouTube agotada,
      ffmpeg no encontrado, etc.).

---

_Última actualización: revisar y podar según se completen tareas._
