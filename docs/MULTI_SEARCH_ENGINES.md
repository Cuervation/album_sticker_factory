# Multi buscador para `image_search`

Este cambio mantiene el provider existente `image_search`, pero deja de estar atado a un unico origen. Ahora puede buscar imagenes en varios buscadores configurables y arranca por Google.

## Orden por defecto

El orden queda en `config.yaml`:

```yaml
search_engines:
  enabled_order:
    - google
    - bing
    - duckduckgo
    - openverse
```

Con `stop_after_first_engine_with_results: true`, si Google devuelve candidatos, no consulta los siguientes motores para esa query. Si Google no devuelve candidatos parseables o falla, prueba Bing, DuckDuckGo y Openverse.

## Uso

Flujo normal:

```bash
python main.py init
python main.py plan
python main.py search
python main.py route-search
python main.py execute-routes --provider image_search --limit 20
python main.py evaluate-candidates --provider image_search
python main.py preflight-candidates --provider image_search --limit 50
python main.py download-ready --provider image_search --limit 10
python main.py crop-ready --provider image_search --limit 10
```

Flujo automatico:

```bash
python main.py build-sticker-candidates --provider auto --limit 20
```

Como `source_providers.enabled_order` tambien empieza por `image_search`, el modo `auto` intenta primero el multi-buscador.

## Agregar otro buscador

Se puede agregar un buscador HTML compatible sin tocar codigo:

```yaml
search_engines:
  enabled_order:
    - google
    - mi_buscador
    - bing
  providers:
    mi_buscador:
      enabled: true
      kind: html_image_search
      url_template: "https://example.com/search?q={query}"
      image_url_patterns:
        - '"imageUrl":"(?P<url>https?:\\/\\/[^"]+)"'
```

La regex debe tener un grupo llamado `url`.

## Notas operativas

- Este provider no descarga imagenes. Solo guarda candidatos con `image_url`, igual que el resto del pipeline.
- Las imagenes siguen pasando por evaluacion, preflight tecnico y descarga controlada.
- Google/Bing/DuckDuckGo pueden bloquear o cambiar HTML. Por eso Openverse queda como fallback estable.
- Las licencias de resultados de buscadores quedan como `needs_manual_review`; no se aprueban automaticamente.
