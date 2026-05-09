---
name: album-sticker-factory-sdd
description: Work on album_sticker_factory with Gentle-AI/SDD. Use for repo analysis, agent pipeline changes, contracts, preflight, retry, Wikimedia-only discovery, validation, tests, and safe local-only modifications.
---

# album_sticker_factory - SDD Skill

## Objetivo

Guiar a Codex/Gentle-AI para trabajar en este repo sin romper el pipeline local de figuritas.

## Contexto del proyecto

Este proyecto construye una herramienta local para planificar, rutear y ejecutar de forma controlada el pipeline de stickers de San Lorenzo de Almagro.

Componentes actuales relevantes:

- CuratorAgent
- QueryBuilderAgent
- SearchRouterAgent
- SearchExecutorAgent
- CandidateEvaluatorAgent
- ReviewAgent
- DownloadAgent
- CandidatePreflightAgent

## Reglas duras

Antes de modificar código:

1. Leer SPEC.md.
2. Leer AGENTS.md.
3. Leer config.yaml.
4. Revisar contracts/.
5. Revisar tests/.
6. Detectar comandos disponibles.
7. Proponer plan antes de tocar archivos.

## Restricciones del proyecto

- Sistema local.
- Sin Firebase.
- Sin Render.
- Sin Cloud Functions.
- Sin deploy.
- SQLite es fuente de estado.
- Internet solo permitido para flujos controlados configurados, especialmente Wikimedia, preflight y download.
- No scraping general web.
- No aprobar candidatos automaticamente.
- No descargar candidatos blocked o retryable.
- No tocar .env, credenciales, tokens ni secretos.
- No modificar input/local_images.
- Mantener compatibilidad con Windows PowerShell.

## Flujo de trabajo esperado

1. Explore: entender estructura, agentes, contratos, tests y config.
2. Plan: proponer cambios minimos.
3. Apply: modificar solo lo necesario.
4. Verify: ejecutar validaciones.
5. Report: listar archivos modificados, comandos ejecutados, resultados y pendientes.

## Validaciones sugeridas

Primero inspeccionar comandos disponibles:

- python main.py --help
- python -m pytest

Comandos funcionales relevantes:

- python main.py init
- python main.py plan
- python main.py search
- python main.py route-search
- python main.py execute-routes --provider local_folder
- python main.py execute-routes --provider wikimedia --limit 20
- python main.py evaluate-candidates --provider wikimedia
- python main.py preflight-candidates --provider wikimedia --limit 50
- python main.py status
- python -m pytest

## Criterio de cierre

Una tarea esta terminada solo si:

- los cambios son minimos y auditables,
- se ejecutaron tests o se explico por que no se pudieron ejecutar,
- no se tocaron secretos ni datos sensibles,
- se reportaron archivos modificados,
- se reportaron riesgos o pendientes.