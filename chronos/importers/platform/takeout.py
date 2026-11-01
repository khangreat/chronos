"""Google Takeout inspector — inventory an export and decide who owns each part.

A Takeout is organised as `Takeout/<Product>/...`. This walks the archive (a
`.zip` or an extracted folder), groups entries by product, and classifies each
by which ecosystem app should own it: Chronos (browser bookmarks/history, saved
links, activity), ytman (YouTube), Command Center (calendar, contacts, tasks,
fitness, location), Nawishtar (Keep notes), or skip. It only *reads the listing*
— it computes a plan; it does not act.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

# normalized product-name substring -> (human category, owning app)
_ROUTES: List[Tuple[str, Tuple[str, str]]] = [
    ("youtube", ("YouTube & Music", "ytman")),
    ("chrome", ("Browser bookmarks & history", "chronos")),
    ("saved", ("Saved links", "chronos")),
    ("my activity", ("Activity log", "chronos")),
    ("bookmark", ("Bookmarks", "chronos")),
    ("calendar", ("Calendar", "cc")),
    ("contacts", ("Contacts", "cc")),
    ("tasks", ("Tasks", "cc")),
    ("fit", ("Fitness", "cc")),
    ("location history", ("Location history", "cc")),
    ("semantic location", ("Location history", "cc")),
    ("maps", ("Maps places", "cc")),
    ("keep", ("Notes (Keep)", "nawishtar")),
]
_SKIP_HINT = ("drive", "mail", "photos", "hangouts", "meet", "pay", "play",
              "voice", "groups")


@dataclass
class CategoryPlan:
    product: str            # the Takeout product folder name
    category: str           # human label
    owner: str              # chronos | ytman | cc | nawishtar | skip
    files: int
    bytes: int
    members: List[str] = field(default_factory=list)  # entry paths


@dataclass
class TakeoutPlan:
    source: str
    categories: List[CategoryPlan]

    def for_owner(self, owner: str) -> List[CategoryPlan]:
        return [c for c in self.categories if c.owner == owner]

    def summary(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for c in self.categories:
            out[c.owner] = out.get(c.owner, 0) + 1
        return out


def _classify(product: str) -> Tuple[str, str]:
    low = product.lower()
    for needle, (cat, owner) in _ROUTES:
        if needle in low:
            return cat, owner
    if any(h in low for h in _SKIP_HINT):
        return product, "skip"
    return product, "skip"


def _iter_entries(path: Path):
    """Yield (relative_path, size_bytes) for every file in a zip or folder."""
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if not info.is_dir():
                    yield info.filename, info.file_size
    elif path.is_dir():
        for f in path.rglob("*"):
            if f.is_file():
                yield str(f.relative_to(path)), f.stat().st_size


def _product_of(rel: str) -> str:
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if not parts:
        return ""
    # strip a leading "Takeout" wrapper if present
    if parts[0].lower() == "takeout" and len(parts) > 1:
        return parts[1]
    return parts[0]


def inspect_takeout(path) -> TakeoutPlan:
    path = Path(path)
    groups: Dict[str, CategoryPlan] = {}
    for rel, size in _iter_entries(path):
        product = _product_of(rel)
        if not product:
            continue
        if product not in groups:
            cat, owner = _classify(product)
            groups[product] = CategoryPlan(product, cat, owner, 0, 0, [])
        g = groups[product]
        g.files += 1
        g.bytes += size
        g.members.append(rel)
    cats = sorted(groups.values(), key=lambda c: (c.owner, -c.bytes))
    return TakeoutPlan(source=str(path), categories=cats)
