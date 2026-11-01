"""bridgespec — a neutral, versioned interop contract for local-first apps.

One source of truth for the citation / link / quote contracts that Chronos,
Command Center, Nawishtar, and ytman speak. Zero third-party dependencies.

Compatibility rule: CONTRACT_VERSION uses major.minor. Additive changes bump
minor and stay backward compatible; a breaking change (never taken lightly)
bumps major. `compatible(required, provided)` checks a consumer can talk to a
provider.
"""

from __future__ import annotations

__version__ = "1.1.0"
CONTRACT_VERSION = "1.1"

from .protocols import (  # noqa: E402,F401
    CitationProvider, LinkProvider, QuoteProvider, ResourceProvider,
)
from .registry import ProviderRegistry  # noqa: E402,F401
from .types import (  # noqa: E402,F401
    CSL_TYPES, LinkRef, Quotation, ResourceRef, validate_csl_item, validate_quotation,
)


def compatible(required: str, provided: str = CONTRACT_VERSION) -> bool:
    """True if a consumer needing `required` can use a `provided` contract:
    same major, and provided minor >= required minor."""
    try:
        rmaj, rmin = (int(x) for x in required.split(".")[:2])
        pmaj, pmin = (int(x) for x in provided.split(".")[:2])
    except (ValueError, TypeError):
        return False
    return rmaj == pmaj and pmin >= rmin
