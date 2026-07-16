# TODO

Lista de tareas pendientes de `gestor-listas`. Marcadas por prioridad y con el
contexto necesario para retomarlas.

---

### Mejorar detección de BPM

- [x] Arreglado escritura BPM en `.opus` (usar `OggOpus` en lugar de `OggVorbis`)
- [x] Mejorada detección de contratiempo (autocorrelación negativa → doble BPM)
- [x] Ampliado rango de búsqueda a [60, 240] BPM con corrección armónica (2×, 3×, 4×)
- [ ] **Pendiente:** la autocorrelación de envolvente RMS falla en temas donde el pulso real no produce un pico positivo claro. Evaluar migrar a `librosa.beat.beat_track` (más preciso, pero añade dependencia pesada: numba, scikit-learn) o implementar detección por onset strength.

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
