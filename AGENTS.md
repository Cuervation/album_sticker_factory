# AGENTS - album_sticker_factory

Regla madre: la IA planifica; Python ejecuta lo repetitivo.

Este repo construye, revisa y exporta candidatos de figuritas para un album virtual de San Lorenzo de Almagro, con enfoque SDD.

## Fuente de verdad

- `SPEC.md`: reglas funcionales y alcance del sistema.
- `AGENTS.md`: reglas operativas para agentes y Codex.
- `config.yaml`: comportamiento configurable del pipeline.
- `contracts/*.schema.json`: contratos de datos.
- `skills/*/SKILL.md`: procedimientos reutilizables.
- `tests/`: validacion dura del comportamiento esperado.

Antes de modificar codigo, leer como minimo:

```bash
README.md
SPEC.md
AGENTS.md
config.yaml
```

## Estado actual

- Prompt 2: `CuratorAgent` implementado.
- Prompt 3: `QueryBuilderAgent` implementado.
- Prompt 4: `SearchRouterAgent` implementado.
- Prompt 5: `SearchExecutorAgent` implementado para `local_folder`.
- Prompt 6: `WikimediaProvider` implementado para discovery de URLs.
- Prompt 7: variantes derivadas por provider sin modificar `search_queries`.
- Prompt 8: `CandidateEvaluatorAgent` implementado para evaluacion por metadata.
- Prompt 9: `ReviewAgent` implementado para revision manual local.
- Prompt 10: `DownloadAgent` implementado para descarga controlada.
- Prompt 11: `CandidatePreflightAgent` implementado para chequeo tecnico liviano.
- Prompt 12: review safety + `retry-preflight` implementados.
- Prompt 12+: `mark-for-retry` y `force-retry-now` implementados.
- Prompt 13: `image_search` pasa a ser provider multi-buscador, empezando por Google.

Internet solo puede usarse desde providers explicitamente habilitados en `config.yaml`.

## Regla general de pipeline

El pipeline correcto es:

```bash
python main.py init
python main.py plan
python main.py search
python main.py route-search
python main.py execute-routes --provider image_search --limit 5
python main.py evaluate-candidates --provider image_search
python main.py preflight-candidates --provider image_search --limit 10
```

Para flujo automatico:

```bash
python main.py build-sticker-candidates --provider auto --limit 20
```

Nunca saltar directamente de discovery a descarga sin evaluacion/preflight/review, salvo que el comando existente lo controle explicitamente.

## Principios duros

- No descargar imagenes durante discovery/search.
- No aprobar automaticamente candidatos encontrados por buscadores.
- No romper contratos existentes de SQLite/CSV.
- No cambiar nombres publicos de providers sin migracion.
- No agregar dependencias pesadas sin necesidad.
- No agregar Selenium, Playwright, browser automation ni scraping con navegador salvo pedido explicito.
- No versionar archivos runtime generados.
- Tests de red deben mockear llamadas externas.
- El sistema debe poder correr localmente.

## Archivos que no se deben commitear

No commitear:

```bash
metadata/*.sqlite
metadata/*.db
output/
input/local_images/*
data/image_candidates.csv
data/review_decisions.csv
reports/review_candidates.html
*.zip
__pycache__/
.pytest_cache/
```

Antes de commitear ejecutar:

```bash
git status --short
git diff --stat
git diff --check
```

## Orchestrator Agent

Responsabilidad: coordinar etapas del pipeline.

Reglas:

- No debe esconder errores criticos.
- Debe respetar el orden de etapas.
- No debe descargar ni aprobar candidatos por fuera de los agentes especializados.
- Si una etapa no tiene datos, debe devolver diagnostico claro.

## Curator Agent

Responsabilidad: generar `sticker_targets`.

Input:

- `data/chapters.csv`
- `data/curation_seed.json`
- Configuracion opcional de cantidad solicitada.

Output:

- `data/sticker_targets.csv`
- Tabla `stickers`.

Reglas:

- IDs deterministas.
- Debe ser idempotente.
- No busca imagenes.
- No usa internet.
- No descarga archivos.

## Query Builder Agent

Responsabilidad: generar queries por sticker.

Input:

- Tabla `stickers`
- `config.yaml`

Output:

- `data/search_queries.csv`
- Tabla `search_queries`.

Reglas:

- No consulta internet.
- No genera URLs.
- No mete sitios especificos salvo que una regla futura lo pida.
- Mantiene contexto San Lorenzo.
- Puede generar queries por sticker o por capitulo cuando el flujo lo pida.
- Las queries originales son trazables y no deben ser modificadas por providers.

## Search Router Agent

Responsabilidad: decidir providers por query.

Input:

- `search_queries`
- contexto de sticker
- `search_routing` en `config.yaml`.

Output:

- `data/search_routes.csv`
- Tabla `search_routes`.

Reglas:

- Routing deterministico.
- Respetar providers enabled/disabled.
- Respetar prioridades de `config.yaml`.
- No ejecutar busquedas.
- No usar internet.
- No crear candidatos.

Providers actuales esperados:

```yaml
image_search
general_web
webpage
local_folder
wikimedia
manual_urls
```

## Search Executor Agent

Responsabilidad: ejecutar rutas de providers permitidos.

Input:

- `search_routes`
- configuracion de ejecucion
- provider solicitado.

Output:

- `data/image_candidates.csv`
- tabla `image_candidates`
- update de `search_routes`.

Reglas:

- Ejecuta solo providers permitidos por `config.yaml`.
- No descarga imagenes completas.
- Solo crea candidatos con metadata y URLs.
- Debe guardar `executed_query` para trazabilidad.
- Debe marcar routes como `routed`, `skipped` o `failed` con `reason` claro.
- Debe deduplicar candidatos por clave canonica.
- Debe ignorar archivos/documentos no imagen cuando sea detectable.
- Debe mantener compatibilidad con:

```bash
python main.py execute-routes --provider image_search
python main.py execute-routes --provider general_web
python main.py execute-routes --provider webpage
python main.py execute-routes --provider wikimedia
python main.py execute-routes --provider local_folder
python main.py execute-routes --provider auto
```

## Candidate Evaluator Agent

Responsabilidad: evaluar metadata de `image_candidates` sin descargar imagenes.

Input:

- `image_url`
- `source_page`
- `width`
- `height`
- `relevance_score`
- `license_status`
- `preflight_content_type` si existe.

Output:

- `status` actualizado:
  - `needs_review`
  - `technical_rejected`
  - `semantic_rejected`
- `metadata_score`
- `decision_reason`
- `evaluated_at`.

Reglas:

- No descarga imagenes.
- No aprueba candidatos.
- Rechaza extensiones/documentos obvios:
  - PDF
  - DJVU
  - TIFF si no esta soportado
  - HTML cuando se detecte como archivo final
- Candidatos de buscadores generales deben quedar como minimo en `needs_review`, nunca `approved`.

## Candidate Preflight Agent

Responsabilidad: validar tecnicamente `image_url` antes de review/download.

Input:

- `image_candidates` en estados configurados, normalmente:
  - `needs_review`
  - `approved`

Output:

- `preflight_status`
- `preflight_error`
- `preflight_content_type`
- `preflight_content_length`
- `preflight_checked_at`
- `preflight_retry_count`
- rechazo tecnico temprano cuando corresponde.

Reglas:

- No descarga imagen completa.
- Usar `HEAD` primero cuando este configurado.
- Usar fallback `GET Range` cuando este configurado.
- `image/*` puede pasar.
- PDF/HTML/no-imagen debe bloquearse.
- HTTP 429 debe tratarse como retryable si config lo indica.
- No aprobar candidatos.
- No modificar imagenes.
- Retry trazable:
  - `retry-preflight`
  - `mark-for-retry`
  - `force-retry-now`

## Review Agent

Responsabilidad: preparar revision humana y aplicar decisiones.

Input:

- `image_candidates`
- `data/review_decisions.csv`

Output:

- `reports/review_candidates.html`
- tabla `reviews`
- update de `image_candidates.status`.

Estados permitidos desde revision:

```bash
approved
rejected
needs_more_info
force_approved
```

Reglas:

- No descargar imagenes.
- No recortar imagenes.
- No exportar stickers finales.
- Bloquear aprobaciones inseguras:
  - `preflight_status=blocked`
  - `preflight_status=retryable`
- Permitir `force_approved` solo si:
  - config lo permite;
  - hay nota manual;
  - no es caso no-imagen bloqueado.
- Toda decision manual debe quedar trazable.

## Download Agent

Responsabilidad: descargar originales de candidatos permitidos.

Input:

- `image_candidates`
- config de descarga.

Output:

- archivos originales en `output/raw/`
- update de:
  - `local_path`
  - `file_sha256`
  - `file_size_bytes`
  - `downloaded_at`
  - `download_error`
  - `status=downloaded` cuando corresponde.

Reglas:

- No descargar candidatos bloqueados.
- No descargar candidatos retryable.
- No saltar preflight si config lo exige.
- Validar content-type y extension.
- Respetar max file size.
- No recortar.
- No exportar sticker final.
- No descargar desde providers no permitidos.
- Mantener trazabilidad por `image_id`.

## Crop Agent

Responsabilidad: generar stickers cuadrados desde imagenes ya descargadas.

Input:

- candidatos `downloaded`
- archivo local en `local_path`.

Output:

- stickers cuadrados en `output/stickers/`
- manifest correspondiente.

Reglas:

- No descargar imagenes.
- No buscar internet.
- No aprobar candidatos.
- No modificar originales.
- Debe crear imagen final cuadrada segun `output.final_size_px`.
- Debe fallar de forma clara si Pillow no puede abrir la imagen.

## Providers

### LocalFolderProvider

Responsabilidad: escanear `input/local_images` y matchear filenames con query/target.

Output:

- matches locales con `relevance_score`.

Reglas:

- No usa red.
- No mueve archivos.
- No modifica originales.
- No descarga nada.
- Solo lee nombres/rutas locales.

### ManualUrlsProvider

Responsabilidad: leer URLs manuales desde CSV.

Input esperado:

```bash
data/manual_image_urls.csv
```

Reglas:

- No usa internet durante discovery.
- No descarga.
- Debe ignorar extensiones documentales no soportadas.
- Debe marcar licencias como `needs_manual_review` salvo que el CSV indique otra cosa valida.
- No aprobar automaticamente.

### WikimediaProvider

Responsabilidad: consultar API de Wikimedia Commons y devolver candidatos URL.

Output:

- `source_page`
- `image_url`
- dimensiones cuando existan
- licencia aproximada
- `executed_query`.

Reglas:

- Usa variantes derivadas por provider.
- No modifica `search_queries`.
- No descarga archivos.
- No sigue sitios externos.
- Debe filtrar documentos no imagen cuando sea detectable.
- Debe diagnosticar errores:
  - HTTP
  - URL
  - JSON
  - no results
  - unsupported mime.

### ImageSearchProvider

Responsabilidad: descubrir candidatos de imagen usando multiples motores de busqueda.

Nombre publico del provider:

```bash
image_search
```

Este nombre no debe cambiar porque el pipeline, rutas, tests y config dependen de el.

#### Orden de motores

El orden debe venir desde `config.yaml`:

```yaml
search_engines:
  image_search_order:
    - google
    - bing
    - duckduckgo
    - openverse
```

Reglas:

- Google debe ser el primer motor preferido.
- Si Google falla, bloquea, no devuelve resultados utiles o devuelve HTML no parseable, continuar con el siguiente motor habilitado.
- El provider debe intentar motores en orden configurado.
- No hardcodear solo Google.
- No romper fallback a Openverse.
- Debe devolver candidatos normalizados con la misma forma que el pipeline ya espera.

#### Discovery solamente

`ImageSearchProvider` no debe descargar imagenes.

Solo puede devolver:

```bash
source_page
image_url
mime
width
height
license_status
author
relevance_score
executed_query
search_engine
```

Si un motor no provee dimensiones, usar `None`.

#### Licencias

Para resultados de buscadores generales:

```bash
license_status = needs_manual_review
```

No auto-aprobar resultados de:

- Google
- Bing
- DuckDuckGo
- otros buscadores HTML.

Openverse puede mapear licencias cuando la API lo devuelve, pero aun asi el flujo debe pasar por evaluacion/preflight/review.

#### Google

Google en este proyecto es best-effort.

Reglas:

- No usar Selenium/Playwright/browser automation.
- No intentar evadir captcha.
- No usar cookies ni sesiones.
- No agregar scraping agresivo.
- No hacer requests masivos sin limites.
- Si Google falla, fallback inmediato a Bing/DuckDuckGo/Openverse.
- Los tests no deben depender de respuestas reales de Google.

Si en el futuro se agrega Google Custom Search JSON API:

- Debe ser opcional.
- Debe estar deshabilitada por defecto.
- Debe configurarse por variables de entorno.
- No commitear API keys.
- Mantener fallback sin API.
- No romper uso local sin credenciales.

Variables sugeridas si se implementa API oficial en el futuro:

```bash
GOOGLE_CSE_API_KEY
GOOGLE_CSE_CX
```

#### Tests de ImageSearchProvider

Los tests deben mockear red.

No crear tests que dependan de:

- Google real.
- Bing real.
- DuckDuckGo real.
- Openverse real.

Validaciones minimas:

```bash
python -m pytest tests/test_image_search_provider.py
python -m pytest tests/test_search_executor_agent.py
```

Los tests deben cubrir:

- Google se intenta primero.
- Si Google no devuelve candidatos, se prueba fallback.
- Los candidatos quedan con provider publico `image_search`.
- `license_status` por buscadores generales queda en `needs_manual_review`.
- No se descarga ningun archivo.
- No se rompen contratos existentes.

### GeneralWebProvider

Responsabilidad: discovery web general.

Estado actual:

- Provider real liviano basado en busqueda de paginas con imagen principal.
- No descarga imagenes.
- Devuelve candidatos con `source_page` e `image_url`.

Reglas:

- Mantenerlo como discovery solamente.
- No aprobar automaticamente.
- No convertirlo en crawler general sin pedido explicito.
- No navegar paginas arbitrarias en profundidad salvo que una tarea futura lo pida.

### WebpageProvider

Responsabilidad: discovery de imagenes desde paginas candidatas o busqueda liviana.

Estado actual:

- Provider real liviano basado en imagenes principales de paginas.
- No descarga imagenes.
- Devuelve candidatos normalizados.

Reglas:

- Mantener discovery solamente.
- No descargar.
- No aprobar.
- No agregar crawling profundo sin pedido explicito.

## Query adaptation

Archivo principal:

```bash
core/provider_query_adapter.py
```

Reglas:

- Las queries originales de `search_queries` no se modifican.
- Cada provider puede generar variantes derivadas en runtime.
- Siempre guardar `executed_query`.
- Las variantes deben mantener contexto San Lorenzo.
- Para buscadores generales conviene agregar terminos como:
  - foto
  - imagen
  - archivo
  - historica
  - San Lorenzo
  - San Lorenzo de Almagro
- Evitar URLs dentro de queries.
- Evitar queries excesivamente largas.
- Deduplicar variantes.

## Configuracion

`config.yaml` controla el comportamiento operativo.

Secciones relevantes:

```yaml
search_routing
search_execution
source_providers
external_search
search_engines
candidate_evaluation
candidate_preflight
review_safety
download
```

Reglas:

- No hardcodear comportamiento que ya esta en config.
- Si se agrega una opcion nueva, documentarla.
- Defaults seguros:
  - no descargar en discovery;
  - no aprobar automaticamente;
  - fallback activado;
  - tests sin red real.

## Contratos de datos

No romper columnas existentes de:

```bash
data/search_queries.csv
data/search_routes.csv
data/image_candidates.csv
data/review_decisions.csv
```

Columnas criticas de `image_candidates`:

```bash
image_id
sticker_id
query_id
provider
source_page
image_url
local_path
executed_query
width
height
quality_score
relevance_score
duplicate_group
license_status
status
metadata_score
decision_reason
evaluated_at
preflight_status
preflight_error
preflight_content_type
preflight_content_length
preflight_checked_at
download_error
downloaded_at
file_sha256
file_size_bytes
```

Si se agregan columnas, deben ser opcionales y compatibles hacia atras.

## Seguridad y derechos

Este proyecto puede descubrir imagenes de internet, pero eso no implica derecho de uso.

Reglas:

- Todo resultado de buscador general requiere revision manual.
- `needs_manual_review` es el default seguro.
- No asumir que una imagen es libre por aparecer en Google.
- No asumir que una imagen es libre por estar en Wikipedia/Wikimedia sin revisar.
- Mantener `source_page` para trazabilidad.
- Mantener `image_url` original.
- No remover metadata de origen.
- No auto-exportar sin aprobacion si `review.require_manual_approval` esta activo.

## Validacion obligatoria

Para cambios de providers/search:

```bash
python -m pytest tests/test_image_search_provider.py tests/test_search_executor_agent.py
python -m pytest
```

Para cambios de preflight/review/download:

```bash
python -m pytest tests/test_candidate_preflight_agent.py tests/test_review_agent.py tests/test_download_agent.py
python -m pytest
```

Para cambios de DB/contratos:

```bash
python -m pytest tests/test_db.py tests/test_contracts.py
python -m pytest
```

Validacion general antes de entregar:

```bash
python -m pytest
git diff --check
git status --short
```

## Criterios para cambios de Codex

Cuando Codex modifique este repo:

1. Leer `README.md`, `SPEC.md`, `AGENTS.md` y `config.yaml`.
2. Identificar etapa afectada.
3. Hacer cambios minimos.
4. Mantener contratos.
5. Agregar/ajustar tests.
6. Ejecutar tests relevantes.
7. No versionar runtime files.
8. Entregar resumen con:
   - archivos modificados;
   - comportamiento cambiado;
   - comandos ejecutados;
   - riesgos pendientes.

## Politica de uso de modelos

Objetivo: elegir modelo por tipo de tarea para balancear costo, velocidad y calidad.

Regla base:

- Usar el modelo principal de la sesion como default.
- Para tareas rapidas/repetitivas, usar modelo chico.
- Para arquitectura, seguridad de flujo y debugging dificil, usar modelo de mayor precision.
- Para codificacion mecanica grande, usar modelo code-first si el cambio esta bien acotado.

Regla de escalado:

- Empezar en default.
- Si hay 2 intentos fallidos o riesgo alto de regresion, escalar.
- Si la tarea es simple y masiva, bajar a modelo chico.

Nota:

- `config.yaml` controla el comportamiento del pipeline.
- Con `llm.enabled: false`, los agentes Python del repo no consumen LLM interno.

## Agentes pendientes o parcialmente implementados

Pueden existir como stubs o implementaciones parciales:

- ImageExtractorAgent
- QualityAgent
- DuplicateAgent
- SemanticVerifierAgent
- SourceRightsAgent
- ClassifierAgent
- ExportAgent
- ReportAgent

Reglas:

- No asumir que un stub hace trabajo real.
- Verificar implementacion antes de depender de un agente.
- Si se activa un agente pendiente, agregar tests y documentar comando.
