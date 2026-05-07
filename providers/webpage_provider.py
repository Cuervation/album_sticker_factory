"""Webpage provider stub (local routing only, no network calls)."""

from __future__ import annotations


class WebpageProvider:
    """Provider contract stub for future webpage extraction."""

    name = "webpage"
    enabled = False

    def run(self, payload: dict | None = None) -> dict:
        return {
            "status": "not_implemented",
            "provider": self.name,
            "message": "Provider stub only. Real search will be implemented in a later prompt.",
        }
