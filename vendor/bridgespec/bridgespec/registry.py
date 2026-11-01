"""ProviderRegistry — the broker's book of providers.

Command Center (the broker) registers each app's provider here and routes
requests by capability. Apps depend on this spec, never on each other. A
citation lookup tries each registered citation provider until one answers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .protocols import (CitationProvider, LinkProvider, QuoteProvider,
                        ResourceProvider)
from .types import LinkRef


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: List[Any] = []

    def register(self, provider: Any) -> None:
        if provider not in self._providers:
            self._providers.append(provider)

    def unregister(self, provider: Any) -> None:
        if provider in self._providers:
            self._providers.remove(provider)

    # -- typed views -------------------------------------------------------- #
    def citation_providers(self) -> List[CitationProvider]:
        return [p for p in self._providers if isinstance(p, CitationProvider)]

    def link_providers(self) -> List[LinkProvider]:
        return [p for p in self._providers if isinstance(p, LinkProvider)]

    def quote_providers(self) -> List[QuoteProvider]:
        return [p for p in self._providers if isinstance(p, QuoteProvider)]

    def resource_providers(self) -> List[ResourceProvider]:
        return [p for p in self._providers if isinstance(p, ResourceProvider)]

    # -- brokered calls ----------------------------------------------------- #
    def resolve_citation(self, url: str) -> Optional[Dict[str, Any]]:
        for p in self.citation_providers():
            hit = p.resolve_citation(url)
            if hit is not None:
                return hit
        return None

    def find_links(self, pattern: str) -> List[LinkRef]:
        out: Dict[str, LinkRef] = {}
        for p in self.link_providers():
            for ref in p.find_links(pattern):
                out[ref.url] = ref
        return list(out.values())

    def all_quotes(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for p in self.quote_providers():
            out.extend(p.list_quotes())
        return out

    def get_resource(self, url: str) -> Optional[Dict[str, Any]]:
        for p in self.resource_providers():
            hit = p.get_resource(url)
            if hit is not None:
                return hit
        return None
