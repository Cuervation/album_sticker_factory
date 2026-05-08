"""Simple provider registry for multi-source discovery."""

from __future__ import annotations

from providers.local_folder_provider import LocalFolderProvider
from providers.manual_urls_provider import ManualUrlsProvider
from providers.wikimedia_provider import WikimediaProvider


PROVIDER_REGISTRY = {
    "manual_urls": ManualUrlsProvider,
    "local_folder": LocalFolderProvider,
    "wikimedia": WikimediaProvider,
}

