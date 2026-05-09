# SPEC - album_sticker_factory

## 1) Proposito
Construir una herramienta local para planificar, rutear y ejecutar de forma controlada el pipeline de stickers de San Lorenzo de Almagro.

## 2) Alcance actual (Prompt 12+)
- `init`: estado local.
- `plan`: 600 stickers.
- `search`: 3000 queries locales.
- `route-search`: rutas de provider por query.
- `execute-routes`: ejecucion de `local_folder` (offline) y `wikimedia` (descubrimiento URL).
- `evaluate-candidates`: evaluacion por metadata (sin descarga).
- `build-sticker-candidates`: flujo automatico principal sin validacion manual.
- `review-candidates` y `apply-reviews`: revision manual local opcional / legacy.
- `download-ready`: descarga controlada de candidatos tecnicamente validos sin approval manual.
- `crop-ready`: recorte square final y manifiesto de stickers.
- `download-approved`: flujo legacy approved-only a `output/raw`.
- `preflight-candidates`: chequeo tecnico liviano de URL antes de review/download.
- `retry-preflight`: reintento controlado de candidatos `retryable`.
- `mark-for-retry`: marca retry manual sin red.
- `force-retry-now`: reintenta preflight ahora, saltando solo ventana temporal.

## 3) Fuera de alcance
- Scraping general web.
- Descarga remota de imagenes.
- Deploy / cloud.

## 4) Reglas duras
- Sistema 100% local.
- Sin Firebase/Render/Cloud Functions.
- Sin deploy.
- En Prompt 11 solo se permite internet para `wikimedia` y preflight/download controlado.
- Preflight no descarga imagenes completas.
- No descargar candidatos `blocked` o `retryable`.
- `force-retry-now` no aprueba, no descarga y no ignora PDF/HTML/no-imagen.
- `mark-for-retry` no cambia `image_candidates.status`.
- SQLite es fuente de estado.
- No se pisan ni modifican archivos de `input/local_images`.
- `license_status` inicial local: `needs_manual_review`.
- IDs estables para stickers/queries/routes/images.
- Las queries originales de `search_queries` no se pisan.
- Cada provider puede usar variantes derivadas trazables en ejecucion.
- Ningun candidato pasa a `approved` automaticamente en el flujo legacy.
- `output/approved` sigue reservado para export final de stickers, no para este paso.
- `output/raw` guarda originales descargados.
- `output/stickers` guarda stickers cuadrados listos para revision visual.
- El flujo automatico principal termina cuando el sticker ya esta descargado y recortado.

## 5) Flujo
1. `init`
2. `plan`
3. `search`
4. `route-search`
5. `execute-routes --provider local_folder`
6. `execute-routes --provider wikimedia --limit N`
7. `evaluate-candidates --provider wikimedia`
8. `review-candidates`
9. `apply-reviews`
10. `retry-preflight --provider wikimedia --limit N`
11. `mark-for-retry --provider wikimedia --limit N --reason "..."`
12. `force-retry-now --provider wikimedia --limit N --reason "..."`
13. `download-ready --provider auto --limit N`
14. `crop-ready --provider auto --limit N`
15. `build-sticker-candidates --provider auto --limit N`
16. `download-approved --provider wikimedia --limit N`
17. etapas legacy: review/apply-reviews

## 6) Estados permitidos
### Stickers
- planned
- query_ready
- searching
- candidates_found
- needs_review
- approved
- missing
- exported

### Search routes
- pending
- routed
- skipped
- failed

### Image candidates
- found
- downloaded
- technical_rejected
- duplicate_rejected
- semantic_rejected
- processed
- needs_review
- approved
- rejected
- exported

En Prompt 8 se usan activamente:
- found
- needs_review
- technical_rejected
- semantic_rejected

## 7) Persistencia SQLite
Tablas activas:
- `chapters`
- `stickers`
- `search_queries`
- `search_routes`
- `image_candidates`
- `reviews`
- `runs`

## 8) Contratos
- `sticker.schema.json`
- `image_candidate.schema.json`
- `review.schema.json`
- `run.schema.json`
- `search_route.schema.json`

## 9) Trazabilidad
- `sticker_id`: `SL-CC-NNN`
- `query_id`: `Q-SL-CC-NNN-XX`
- `route_id`: `R-{query_id}-{provider-slug}`
- `image_id`: `IMG-{sticker_id}-local-folder-{hash}`
- Retry manual: `retry_requested_at`, `retry_requested_reason`, `retry_forced_at`, `retry_forced_reason`, `last_retry_mode`.

## 9.1) Retry manual seguro
- `mark-for-retry` registra pedido operativo sobre candidatos `preflight_status=retryable`.
- `force-retry-now` reutiliza `CandidatePreflightAgent`, respeta `max_retry_attempts` y solo ignora el backoff temporal.
- Si el nuevo preflight detecta PDF/HTML/no-imagen, el candidato puede pasar a `technical_rejected`.
- Ningun comando de retry modifica `reviews.review_status` ni aprueba automaticamente.

## 10) Criterios de aceptacion Prompt 6
- `python main.py init` OK
- `python main.py plan` OK
- `python main.py search` OK
- `python main.py route-search` OK
- `python main.py execute-routes --provider local_folder` OK
- `python main.py execute-routes --provider wikimedia --limit 20` OK
- `python main.py evaluate-candidates --provider wikimedia` OK
- `python main.py preflight-candidates --provider wikimedia --limit 50` OK
- `python main.py status` refleja stickers/queries/routes/candidates
- `python -m pytest` OK
- internet solo para wikimedia, sin scraping general, sin descarga remota
