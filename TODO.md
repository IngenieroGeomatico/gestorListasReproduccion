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
      - Tema EDM **sin tag de género** → debe caer en el prior balanceado; verificar
        que aun así acierta (rango 70-190) o documentar si necesita el tag.
      - Género en el tag que **no** contenga una palabra clave de `_EDM_GENRE_KEYWORDS`
        (p. ej. "Hard Dance" variantes, subgéneros raros) → ampliar la lista si falla.
      - Temas con **intro larga sin percusión** (los primeros 60 s son ambient):
        `detect_bpm` solo analiza `max_duration=60` s desde el inicio. Evaluar si
        conviene saltar la intro o analizar un tramo central.
      - Temas con **cambios de tempo** o breakdowns → confirmar comportamiento.
- [ ] **Calibrar priors con datos reales.** Ajustar `_PRIOR_EDM` / `_PRIOR_DEFAULT`
      (center, sigma, min/max_bpm) en `audio.py` según los resultados de la batería.
      Los valores actuales (EDM 155/0.45, default 125/0.55) son de partida.
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
