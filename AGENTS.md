# AGENTS - album_sticker_factory

Regla madre: la IA planifica; Python ejecuta lo repetitivo.

Estado actual:
- Prompt 2: `CuratorAgent` implementado.
- Prompt 3: `QueryBuilderAgent` implementado (queries locales).
- Prompt 4: `SearchRouterAgent` implementado (routing local).
- Prompt 5: `SearchExecutorAgent` implementado para `local_folder` (offline).
- Prompt 6: `WikimediaProvider` implementado para descubrimiento de URLs.
- Prompt 8: `CandidateEvaluatorAgent` implementado para evaluacion por metadata.
- Prompt 9: `ReviewAgent` implementado para revision manual local.
- Prompt 10: `DownloadAgent` implementado para descarga controlada approved-only.
- Prompt 11: `CandidatePreflightAgent` implementado para chequeo tecnico liviano.
- Prompt 12: review safety + `retry-preflight` implementados.
- Prompt 12+: `mark-for-retry` y `force-retry-now` implementados para retry manual trazable.
- Internet permitido solo para `wikimedia`; scraping general y descarga remota no implementados.

## Orchestrator Agent
- Responsabilidad: coordinar etapas del pipeline.
- Estado Prompt 5: stub.

## Curator Agent
- Responsabilidad: generar `sticker_targets`.
- Input: capitulos + seed.
- Output: `data/sticker_targets.csv` + tabla `stickers`.
- Estado Prompt 5: implementado.

## Query Builder Agent
- Responsabilidad: generar queries por sticker.
- Input: `stickers` + config.
- Output: `data/search_queries.csv` + tabla `search_queries`.
- Estado Prompt 5: implementado (sin internet).

## Search Router Agent
- Responsabilidad: decidir providers por query.
- Input: `search_queries` + contexto sticker + `search_routing`.
- Output: `data/search_routes.csv` + tabla `search_routes`.
- Estado Prompt 5: implementado (routing local).

## Search Executor Agent
- Responsabilidad: ejecutar rutas de providers permitidos.
- Input: `search_routes` + config de ejecucion.
- Output: `data/image_candidates.csv` + tabla `image_candidates` + update de `search_routes`.
- Restriccion Prompt 6: `local_folder` y `wikimedia` solamente.
- En Prompt 7 usa variantes derivadas por provider sin modificar `search_queries`.
- Estado Prompt 7: implementado.

## Candidate Evaluator Agent
- Responsabilidad: evaluar metadata de `image_candidates` sin descargar imagenes.
- Input: `image_url`, `source_page`, `width`, `height`, `relevance_score`, `license_status`.
- Output: `status` actualizado (`needs_review`, `technical_rejected`, `semantic_rejected`), `metadata_score`, `decision_reason`, `evaluated_at`.
- Estado Prompt 8: implementado.

## Review Agent
- Responsabilidad: preparar revision humana de candidatos `needs_review` y aplicar decisiones.
- Input: `image_candidates` + `data/review_decisions.csv`.
- Output:
  - `reports/review_candidates.html`,
  - upsert en tabla `reviews`,
  - update de `image_candidates.status` (`approved`, `rejected`, `needs_review`).
- Restriccion: no descarga imagenes, no modifica `output/raw` ni `output/approved`.
- Estado Prompt 12: implementado con validaciones de seguridad (`blocked/retryable`) y soporte `force_approved`.

## Download Agent
- Responsabilidad: descargar originales solo de candidatos `approved`.
- Input: `image_candidates` + config de descarga.
- Output:
  - archivos originales en `output/raw/{chapter_slug}/{sticker_id}/`,
  - update de `image_candidates` a `downloaded` cuando OK,
  - metadatos `file_sha256`, `file_size_bytes`, `downloaded_at`, `download_error`.
- Restriccion: no descarga candidatos no aprobados, ni `preflight_status=blocked/retryable`; no crop, no export final.
- Estado Prompt 12: implementado.

## Candidate Preflight Agent
- Responsabilidad: validar tecnicamente `image_url` antes de review/download.
- Input: `image_candidates` en `needs_review/approved`.
- Output:
  - `preflight_status`, `preflight_error`, `preflight_content_type`, `preflight_content_length`, `preflight_checked_at`,
  - rechazo tecnico temprano para no-imagen/PDF/HTML cuando corresponde.
- Restriccion: sin descarga completa del archivo.
- Estado Prompt 12: implementado con reintentos controlados (`retry-preflight`, retry count, backoff temporal).
- Estado Prompt 12+: soporta `mark-for-retry` (sin red) y `force-retry-now` (preflight inmediato, sin aprobacion ni descarga).
- Trazabilidad retry: `retry_requested_at`, `retry_requested_reason`, `retry_forced_at`, `retry_forced_reason`, `last_retry_mode`.

## Providers

### LocalFolderProvider
- Responsabilidad: escanear `input/local_images` y matchear filenames con query/target.
- Output: matches locales con `relevance_score`.
- No usa red, no mueve ni modifica archivos.
- Estado Prompt 5: implementado.

### WikimediaProvider
- Responsabilidad: consultar API de Wikimedia Commons y devolver candidatos URL.
- Output: candidatos con `source_page`, `image_url`, dimensiones y licencia aproximada.
- Usa `executed_query` para trazabilidad de variante.
- No descarga archivos ni sigue sitios externos.
- Estado Prompt 7: implementado.
- En Prompt 8 mantiene discovery sin descarga, con diagnostico de error mas claro para routes.

### GeneralWebProvider / ImageSearchProvider / WebpageProvider
- Responsabilidad: placeholders de provider.
- Estado Prompt 6: stubs, no ejecutables en esta etapa.

## Agentes pendientes (stubs)
- ImageExtractorAgent
- QualityAgent
- DuplicateAgent
- SemanticVerifierAgent
- SourceRightsAgent
- CropAgent
- ClassifierAgent
- ExportAgent
- ReportAgent
