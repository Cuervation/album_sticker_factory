"""Orchestrates high-level pipeline commands."""

from __future__ import annotations


class OrchestratorAgent:
    """Prompt 1 stub orchestrator."""

    def run(self, payload: dict | None = None) -> dict:
        command = (payload or {}).get("command", "run-all")
        return {"status": "stub", "message": f"{command} not implemented yet (Prompt 1)."}

