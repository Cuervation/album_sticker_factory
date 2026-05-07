"""Image search provider stub (local routing only, no network calls)."""

from __future__ import annotations


class ImageSearchProvider:
    """Provider contract stub for future image search."""

    name = "image_search"
    enabled = False

    def run(self, payload: dict | None = None) -> dict:
        return {
            "status": "not_implemented",
            "provider": self.name,
            "message": "Provider stub only. Real search will be implemented in a later prompt.",
        }
