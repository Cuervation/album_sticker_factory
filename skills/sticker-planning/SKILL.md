# sticker-planning

## Objetivo
Definir y mantener objetivos de stickers por capítulo para un álbum de 600 figuritas, con reglas editoriales consistentes.

## Cuándo usarlo
- Cuando se generan o ajustan `sticker_targets`.
- Cuando se revisa balance entre capítulos, rareza y categorías.

## Reglas para convertir capítulos en stickers
- Respetar los 18 capítulos oficiales.
- Respetar `target_count` por capítulo.
- Cada sticker debe mapear a un único `chapter_id`.
- Cada sticker debe tener `target_name` claro y verificable.

## Reglas de rareza
- Usar una escala explícita (por ejemplo: `common`, `rare`, `epic`, `legendary`).
- Mantener proporción estable entre capítulos.
- Reservar rarezas altas para hitos, ídolos y momentos excepcionales.

## Reglas de categorías
- Categorías sugeridas: `jugador`, `equipo`, `partido`, `estadio`, `trofeo`, `institucional`, `otros_deportes`, `mitica`.
- No mezclar categorías ambiguas; priorizar coherencia histórica.

## Reglas para no repetir targets
- `target_name` no puede duplicarse en el mismo capítulo.
- Evitar duplicados semánticos entre capítulos, salvo casos intencionales documentados.
- Registrar variantes con contexto (año, torneo, plantel) para evitar colisiones.

## Criterios de aceptación
- 18 capítulos válidos.
- Suma de `target_count` igual a 600.
- Sin duplicados obvios de `target_name`.
- Cada fila con `chapter_slug`, `category`, `rarity`, `priority` y `status` definido.

