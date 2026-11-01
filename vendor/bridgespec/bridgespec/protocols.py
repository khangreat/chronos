"""The capability protocols apps implement / consume.

Each capability is its own Protocol so an app can implement any subset. Adding a
capability = adding a new Protocol, never changing an existing signature — that
keeps an older consumer working against a newer provider.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .types import LinkRef


@runtime_checkable
class CitationProvider(Protocol):
    def resolve_citation(self, url: str) -> Optional[Dict[str, Any]]:
        """CSL-JSON item for a URL this app knows, or None."""
        ...


@runtime_checkable
class LinkProvider(Protocol):
    def find_links(self, pattern: str) -> List[LinkRef]:
        """Links whose URL matches a pattern."""
        ...


@runtime_checkable
class QuoteProvider(Protocol):
    def get_quote(self, quote_id: int) -> Optional[Dict[str, Any]]:
        """A single Quotation (as dict) by id, or None."""
        ...

    def list_quotes(self) -> List[Dict[str, Any]]:
        """All captured quotations (as dicts)."""
        ...


@runtime_checkable
class ResourceProvider(Protocol):
    def get_resource(self, url: str) -> Optional[Dict[str, Any]]:
        """A ResourceRef (as dict) for a URL this app knows — kind, CSL, and
        relationships — or None."""
        ...

    def resources_by_kind(self, kind: str) -> List[Dict[str, Any]]:
        """ResourceRefs (as dicts) of a given kind (social_post, thread, …)."""
        ...
