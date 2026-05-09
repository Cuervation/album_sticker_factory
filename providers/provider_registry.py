"""Simple provider registry for multi-source discovery."""

from __future__ import annotations

from providers.local_folder_provider import LocalFolderProvider
from providers.manual_urls_provider import ManualUrlsProvider
from providers.wikimedia_provider import WikimediaProvider
from providers.general_web_provider import GeneralWebProvider
from providers.image_search_provider import ImageSearchProvider
from providers.webpage_provider import WebpageProvider


PROVIDER_REGISTRY = {
    "manual_urls": ManualUrlsProvider,
    "local_folder": LocalFolderProvider,
    "wikimedia": WikimediaProvider,
    "general_web": GeneralWebProvider,
    "image_search": ImageSearchProvider,
    "webpage": WebpageProvider,
}
