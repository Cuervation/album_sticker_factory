# album_sticker_factory

Herramienta 100% local para construir stickers de un album virtual de San Lorenzo de Almagro con enfoque SDD (Spec-Driven Development).

## Objetivo
Definir una base trazable y mantenible para planificar, revisar y exportar stickers sin depender de servicios cloud.

## Enfoque SDD
- `SPEC.md` es la fuente de verdad funcional.
- `AGENTS.md` define responsabilidades operativas.
- `contracts/*.json` define formatos de datos.
- `skills/*/SKILL.md` define politicas por etapa.

## Arquitectura local
- Python + SQLite (`sqlite3`) + CLI (`argparse`).
- Configuracion local en `config.yaml`.
- Estado persistido en `metadata/stickers.sqlite`.
- Salidas de archivos en `output/`.

## Estructura de carpetas
- `agents/`: agentes del pipeline.
- `core/`: utilidades base (DB, config, paths, slugs, logging).
- `providers/`: conectores de busqueda/extraccion (stubs).
- `skills/`: reglas operativas por capacidad.
- `contracts/`: JSON Schemas.
- `data/`: capitulos, semilla curatorial y sticker targets.
- `metadata/`: SQLite local.
- `output/`: archivos por estado.
- `reports/`: reportes.
- `tests/`: pruebas automaticas.

## Comandos
```bash
python main.py init
python main.py plan
python main.py status
python main.py list-chapters
python main.py search
python main.py route-search
python main.py execute-routes --provider local_folder
python main.py execute-routes --provider wikimedia --limit 20
python main.py evaluate-candidates --provider wikimedia
python main.py preflight-candidates --provider wikimedia --limit 50
python main.py retry-preflight --provider wikimedia --limit 20
python main.py review-candidates
python main.py apply-reviews
python main.py download-approved --provider wikimedia --limit 10
python main.py download
python main.py evaluate
python main.py crop
python main.py classify
python main.py review
python main.py export
python main.py report
python main.py run-all
```

## Plan curatorial (Prompt 2)
`python main.py plan`:
- valida `data/chapters.csv` (18 capitulos + total 600),
- genera `data/sticker_targets.csv` con 600 objetivos,
- persiste 600 registros en `stickers` (SQLite),
- es idempotente (no duplica al correr dos veces),
- muestra resumen por capitulo y total final.

Importante: este paso no busca ni descarga imagenes. Solo genera objetivos de busqueda.

## Query building local (Prompt 3)
`python main.py search`:
- lee los 600 stickers planificados,
- genera `max_queries_per_sticker` por sticker (default: 5),
- escribe `data/search_queries.csv`,
- persiste queries en SQLite (`search_queries`),
- es idempotente (si se corre dos veces, no duplica).

Importante: en este prompt `search` no consulta internet, no llama APIs externas y no usa providers reales. Solo prepara queries locales.

## Search routing local (Prompt 4)
`python main.py route-search`:
- lee queries desde SQLite (`search_queries`),
- decide providers candidatos por reglas deterministicas,
- escribe `data/search_routes.csv`,
- persiste rutas en SQLite (`search_routes`),
- respeta providers enabled/disabled y `max_routes_per_query`,
- es idempotente (no duplica al correr dos veces).

Importante: este paso no ejecuta busquedas reales ni consulta internet. Solo prepara routing local.

## Route execution local (Prompt 5)
`python main.py execute-routes --provider local_folder`:
- lee rutas de `search_routes` para `local_folder`,
- escanea `input/local_images`,
- intenta asociar archivos locales a queries por tokens del nombre de archivo,
- crea/actualiza `image_candidates` en SQLite,
- exporta `data/image_candidates.csv`,
- actualiza estado de rutas (`routed`, `skipped`, `failed`) para `local_folder`.

Importante: este paso no usa internet, no descarga nada y no modifica imagenes originales.

## Wikimedia discovery controlado (Prompt 6)
`python main.py execute-routes --provider wikimedia --limit 20`:
- ejecuta solo rutas `provider=wikimedia`,
- consulta API de Wikimedia Commons en forma controlada,
- guarda candidatos en `image_candidates` con `source_page` e `image_url`,
- exporta `data/image_candidates.csv`,
- actualiza rutas a `routed/skipped/failed`.

Importante: no descarga imagenes. Solo guarda URLs candidatas y metadata.

## Adaptacion de queries por provider (Prompt 7)
- Las 3000 queries originales de `data/search_queries.csv` no se modifican.
- Para Wikimedia se generan variantes derivadas mas cortas en tiempo de ejecucion.
- Cada candidato guarda `executed_query` para trazabilidad.
- Si no hay resultados: la route queda con `reason=no_results;tried_queries:N`.
- Si hay resultados: `reason=candidates_found:N;executed_query:<variante>`.

## Evaluacion por metadata (Prompt 8)
`python main.py evaluate-candidates --provider wikimedia`:
- lee candidatos existentes en `image_candidates` (SQLite),
- evalua metadata disponible sin descargar archivos,
- calcula `metadata_score` y `decision_reason`,
- actualiza `status` a `needs_review`, `technical_rejected` o `semantic_rejected`,
- reexporta `data/image_candidates.csv`.

Estados usados en esta etapa:
- `found` (sin evaluar o mantenido),
- `needs_review`,
- `technical_rejected`,
- `semantic_rejected`.

Importante: no descarga imagenes, no recorta y no aprueba automaticamente.

## Revision manual (Prompt 9)
- `python main.py review-candidates` genera:
  - `reports/review_candidates.html` con tarjetas de candidatos `needs_review`,
  - `data/review_decisions.csv` para decision manual.
- Editar `data/review_decisions.csv` con:
  - `approved`
  - `rejected`
  - `needs_more_info`
- Luego ejecutar `python main.py apply-reviews`.

Este paso no descarga imagenes. `approved` significa candidato aprobado para una proxima etapa controlada, no sticker final exportado.

## Descarga controlada approved-only (Prompt 10)
- `python main.py download-approved --provider wikimedia --limit 10`
- Descarga solo candidatos `image_candidates.status=approved`.
- Guarda originales en `output/raw/{chapter_slug}/{sticker_id}/{image_id}.{ext}`.
- Actualiza metadata local: `local_path`, `file_sha256`, `file_size_bytes`, `downloaded_at`.
- Si falla una descarga, mantiene status `approved` y registra `download_error`.

No recorta, no exporta stickers finales y no usa `output/approved`.

## Preflight tecnico (Prompt 11)
- `python main.py preflight-candidates --provider wikimedia --limit 50`
- Hace chequeo tecnico liviano sobre `image_url` (HEAD y fallback GET Range).
- No descarga imagenes completas.
- Guarda:
  - `preflight_status` (`passed`, `blocked`, `retryable`, `failed`, `skipped`)
  - `preflight_error`
  - `preflight_content_type`
  - `preflight_content_length`
  - `preflight_checked_at`
- Si detecta no-imagen (ej. `application/pdf`), puede marcar `technical_rejected` antes de revision/aprobacion.

## Safety review y retry (Prompt 12)
- `apply-reviews` ahora bloquea aprobaciones inseguras:
  - `preflight_status=blocked` -> no aprueba.
  - `preflight_status=retryable` -> no aprueba por defecto.
- Override manual disponible con `review_status=force_approved` + `notes` (trazable), excepto casos no-imagen bloqueados.
- Nuevo comando: `python main.py retry-preflight --provider wikimedia --limit 20 [--force]` para reintentar solo candidatos `retryable`.

## Retry manual trazable
- `python main.py mark-for-retry --provider wikimedia --limit 1 --reason "motivo"` marca candidatos `retryable` para reintento operativo.
- `mark-for-retry` no usa internet, no aprueba, no descarga y no cambia `image_candidates.status`.
- Guarda `retry_requested_at`, `retry_requested_reason` y `last_retry_mode=manual`.
- `python main.py force-retry-now --provider wikimedia --limit 5 --reason "motivo"` ejecuta preflight ahora, ignorando solo la ventana temporal.
- `force-retry-now` sigue respetando providers permitidos, content-type, no-imagen/PDF/HTML y `max_retry_attempts`.
- Guarda `retry_forced_at`, `retry_forced_reason` y `last_retry_mode=forced`.
- Diferencia clave: `retry-preflight` normal espera la ventana configurada; `force-retry-now` permite una intervencion puntual trazable.

## Carpeta de entrada local
- `input/local_images/` es el punto de entrada manual para imagenes.
- No hay imagenes versionadas en el repo; el usuario las agrega localmente.

## Como validar que hay 600 targets
```bash
python main.py init
python main.py plan
python main.py search
python main.py route-search
python main.py execute-routes --provider wikimedia --limit 20
python main.py evaluate-candidates --provider wikimedia
python main.py preflight-candidates --provider wikimedia --limit 50
python main.py review-candidates
# editar data/review_decisions.csv
python main.py apply-reviews
python main.py retry-preflight --provider wikimedia --limit 20
python main.py mark-for-retry --provider wikimedia --limit 1 --reason "manual retry"
python main.py force-retry-now --provider wikimedia --limit 5 --reason "manual retry"
python main.py download-approved --provider wikimedia --limit 10
python main.py status
python -m pytest
```

`status` debe mostrar `Stickers: 600`, `planned: 600` y `Search queries: 3000`.
Tambien debe mostrar `Search routes` con conteos por provider y status.
En PowerShell tambien podes verificar:
```powershell
(Import-Csv data/search_queries.csv).Count
(Import-Csv data/search_routes.csv).Count
(Test-Path data/image_candidates.csv)
(Import-Csv data/image_candidates.csv).Count
```
Debe devolver `3000`.

## Tests
```bash
python -m pytest
```

## Incluye Prompt 1
- Estructura completa del proyecto.
- Documentacion SDD (`SPEC.md`, `AGENTS.md`).
- Skills base.
- Contratos JSON Schema.
- Configuracion local.
- CSV de capitulos (18 capitulos, total 600).
- SQLite local + tablas + carga idempotente de capitulos.
- CLI funcional para `init`, `status`, `list-chapters`, `plan`.

## Incluye Prompt 2
- `CuratorAgent` implementado.
- Semilla curatorial en `data/curation_seed.json`.
- IDs deterministas `SL-CC-NNN`.
- Escritura de `data/sticker_targets.csv` con 600 filas.
- Persistencia idempotente en tabla `stickers`.
- Tests para curator, CSV, SQLite, categorias, rarezas, prioridades y `search_hint`.

## Incluye Prompt 3
- `QueryBuilderAgent` implementado sin LLM.
- Generacion deterministica de `query_id` con formato `Q-SL-CC-NNN-XX`.
- Export de `data/search_queries.csv`.
- Persistencia idempotente en tabla `search_queries`.
- Validaciones de calidad de query (sin URLs, sin sitios especificos, con contexto de San Lorenzo).
- Tests de queries, CSV, SQLite e integracion CLI basica.

## Incluye Prompt 4
- `SearchRouterAgent` implementado en modo local controlado.
- Tabla SQLite `search_routes`.
- Export de `data/search_routes.csv`.
- Comando `python main.py route-search`.
- Reglas de routing deterministicas por query/categoria.
- Providers como stubs (`local_folder`, `wikimedia`, `general_web`, `image_search`, `webpage`) sin acceso a internet.
- Tests de routing, CSV, SQLite, contratos y CLI.

## Incluye Prompt 5
- `SearchExecutorAgent` implementado para `local_folder`.
- `LocalFolderProvider` implementado para matching local por filename.
- Carpeta `input/local_images/` para ingreso manual.
- Export de `data/image_candidates.csv`.
- Actualizacion de status de `search_routes` para `local_folder`.
- CLI `python main.py execute-routes --provider local_folder [--limit N]`.
- Tests de provider local, ejecutor, CLI y persistencia idempotente.

## Incluye Prompt 6
- `WikimediaProvider` real usando `urllib` + API de Wikimedia Commons.
- Control por config (`external_search`) con limites de rutas/resultados/timeouts.
- `execute-routes` habilita `--provider wikimedia` ademas de `local_folder`.
- Candidatos Wikimedia con `source_page`, `image_url`, `width`, `height`, `license_status`.
- Sin descarga de archivos, sin scraping general web.

## Incluye Prompt 7
- `core/provider_query_adapter.py` para variantes de query por provider.
- Wikimedia prueba hasta 5 variantes por route (configurable).
- Opcion de cortar al primer exito (`stop_after_first_success`).
- `image_candidates` incluye `executed_query`.
- Las queries originales permanecen intactas.

## Incluye Prompt 8
- `CandidateEvaluatorAgent` para evaluacion local por metadata (sin descarga).
- Nuevas columnas opcionales en `image_candidates`:
  - `metadata_score`
  - `decision_reason`
  - `evaluated_at`
- Nuevo comando `python main.py evaluate-candidates [--provider ...] [--limit ...]`.
- Mejora de diagnostico de `execute-routes` para reasons de `failed/skipped`.

## No incluye todavia
- Descarga de imagenes.
- Recorte real.
- Aprobacion automatica.
- Busqueda general web.
- Deploy.
- Servicios cloud (Firebase/Render/Cloud Functions u otros).

## Proximos pasos
1. Priorizar variantes Wikimedia por categoria y epoca con heuristicas de precision.
2. Implementar `download` con metadata de origen y licencia.
3. Implementar evaluacion tecnica + deduplicacion.
4. Implementar recorte + revision manual + export.
