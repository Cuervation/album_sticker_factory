"""Local-folder provider for offline image matching against routes."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any

class LocalFolderProvider:
    """Offline provider that matches route text against local filenames."""

    name = "local_folder"
    enabled = True
    stopwords = {
        "san",
        "lorenzo",
        "de",
        "almagro",
        "el",
        "la",
        "los",
        "las",
        "y",
        "del",
        "foto",
        "imagen",
    }

    def run(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        base_dir = Path(payload.get("base_dir", "."))
        allowed_extensions = payload.get("allowed_extensions", [".jpg", ".jpeg", ".png", ".webp"])
        route = payload.get("route", {})

        files = self.list_image_files(base_dir=base_dir, allowed_extensions=allowed_extensions)
        matches = self.match_route_to_files(route=route, files=files)
        return {
            "status": "ok",
            "provider": self.name,
            "message": "Local folder scan complete.",
            "files_found": len(files),
            "matches_found": len(matches),
            "matches": matches,
        }

    def list_image_files(self, base_dir: Path, allowed_extensions: list[str]) -> list[dict[str, Any]]:
        """List candidate files from local folder without modifying them."""
        base_dir = Path(base_dir)
        if not base_dir.exists():
            return []
        allowed = {ext.lower() for ext in allowed_extensions}
        files: list[dict[str, Any]] = []
        for path in sorted(base_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in allowed:
                continue
            stat = path.stat()
            files.append(
                {
                    "path": path,
                    "filename": path.name,
                    "extension": path.suffix.lower(),
                    "size_bytes": int(stat.st_size),
                }
            )
        return files

    def match_route_to_files(self, route: dict[str, Any], files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return matched files using deterministic token overlap."""
        query_tokens = self.tokenize(route.get("query", ""))
        target_tokens = self.tokenize(route.get("target_name", ""))
        route_tokens = query_tokens | target_tokens
        matches: list[dict[str, Any]] = []
        for file_info in files:
            file_tokens = self.tokenize(Path(file_info["filename"]).stem)
            shared = route_tokens & file_tokens
            if len(shared) < 2:
                continue
            denom = max(1, min(len(route_tokens), len(file_tokens)))
            relevance = min(1.0, len(shared) / denom)
            matches.append(
                {
                    "path": file_info["path"],
                    "filename": file_info["filename"],
                    "extension": file_info["extension"],
                    "size_bytes": file_info["size_bytes"],
                    "shared_tokens": sorted(shared),
                    "relevance_score": round(relevance, 4),
                    "file_hash": self.short_hash(str(file_info["path"]).lower()),
                }
            )
        matches.sort(key=lambda item: (-item["relevance_score"], item["filename"]))
        return matches

    def tokenize(self, text: str) -> set[str]:
        """Normalize and tokenize text for local matching."""
        normalized = (
            unicodedata.normalize("NFKD", str(text or ""))
            .encode("ascii", "ignore")
            .decode("ascii")
            .lower()
        )
        tokens = re.findall(r"[a-z0-9]+", normalized)
        filtered = {tok for tok in tokens if tok not in self.stopwords and len(tok) >= 2}
        return filtered

    @staticmethod
    def short_hash(text: str) -> str:
        """Return deterministic short hash."""
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]

    def search(self, payload: dict | None = None) -> dict:
        """Alias for run() to keep future interface flexible."""
        return self.run(payload)

    def stub(self) -> dict:
        """Explicit stub response for non-execution contexts."""
        return {
            "status": "not_implemented",
            "provider": self.name,
            "message": "Provider stub only. Real search will be implemented in a later prompt.",
        }
