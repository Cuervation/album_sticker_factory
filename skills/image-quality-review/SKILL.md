# image-quality-review

## Objetivo
Aplicar filtros técnicos y de utilidad antes de revisión manual final.

## Cuándo usarlo
- En la etapa `evaluate` sobre `image_candidates`.
- Al definir reglas automáticas de descarte.

## Reglas de calidad
- Mínimo 400x400.
- Preferir 800px o más.
- Detectar blur y marcar rechazo técnico cuando corresponda.
- Detectar duplicados y agruparlos.
- Rechazar capturas malas (compresión extrema, recortes pobres, overlays invasivos).
- Generar `quality_score`.
- No usar IA para imágenes claramente malas.

