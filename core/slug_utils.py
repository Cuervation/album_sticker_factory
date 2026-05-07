"""Slug helpers."""

from __future__ import annotations

import re
import unicodedata


def slugify(text: str) -> str:
    """Return a stable ASCII slug using hyphens."""
    value = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip("-")
    return value

