"""Interchange types shared by local-first apps.

These are the *data* every app agrees on. Keep them minimal and stable: add
fields, never remove or rename them (see CONTRACT_VERSION in __init__).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# CSL-JSON item types we expect from web sources (a subset of the CSL list).
CSL_TYPES = {
    "webpage", "article", "article-journal", "article-newspaper",
    "post", "post-weblog", "report", "book", "chapter", "dataset",
    "software", "broadcast", "motion_picture", "entry-encyclopedia",
}


@dataclass
class LinkRef:
    """A raw link one app surfaces to another (e.g. Chronos -> ytman)."""
    url: str
    title: str
    site: Optional[str] = None
    date_added: Optional[int] = None
    source_app: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LinkRef":
        keys = cls.__dataclass_fields__  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in keys})


@dataclass
class Quotation:
    """A captured quote plus the CSL-JSON of its source, for citing (Nawishtar)."""
    quote: str
    source: Optional[Dict[str, Any]] = None   # CSL-JSON item
    note: str = ""
    locator: Optional[str] = None
    source_app: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Quotation":
        keys = cls.__dataclass_fields__  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in keys})


@dataclass
class ResourceRef:
    """A resource surfaced with its structure: kind, citation, and how it
    relates to other resources (a thread, a reply, a quoted post). Lets a
    consumer (e.g. Nawishtar) insert a captured post or thread as a citable
    reference that keeps its shape, not just a bare URL.

    `relationships` is a list of {"rel": str, "url": str}.
    """
    url: str
    title: str = ""
    kind: str = "webpage"
    csl: Optional[Dict[str, Any]] = None
    author: Optional[str] = None
    site: Optional[str] = None
    relationships: List[Dict[str, str]] = field(default_factory=list)
    source_app: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ResourceRef":
        keys = cls.__dataclass_fields__  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in keys})


def validate_csl_item(item: Dict[str, Any]) -> List[str]:
    """Cheap structural check on a CSL-JSON item. Returns a list of problems
    (empty = valid). Catches a misbehaving provider before its data reaches a
    citation engine — no jsonschema dependency needed."""
    errors: List[str] = []
    if not isinstance(item, dict):
        return ["item is not an object"]
    t = item.get("type")
    if not t:
        errors.append("missing 'type'")
    elif t not in CSL_TYPES:
        errors.append(f"unknown CSL type: {t!r}")
    if not item.get("title"):
        errors.append("missing 'title'")
    issued = item.get("issued")
    if issued is not None:
        dp = issued.get("date-parts") if isinstance(issued, dict) else None
        if not (isinstance(dp, list) and dp and isinstance(dp[0], list)):
            errors.append("'issued' is not a valid date-parts structure")
    author = item.get("author")
    if author is not None and not isinstance(author, list):
        errors.append("'author' must be a list")
    return errors


def validate_quotation(q: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not q.get("quote"):
        errors.append("missing 'quote'")
    src = q.get("source")
    if src is not None:
        errors.extend(f"source: {e}" for e in validate_csl_item(src))
    return errors
