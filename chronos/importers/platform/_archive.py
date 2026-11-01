"""One way to open an account export, whatever shape it arrives in.

People pick whatever they have: the downloaded .zip, the unzipped folder, or a
single file from inside it. These helpers treat all three the same, so each
platform parser only says which files it wants.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Callable, Iterator, Tuple


def _norm(rel: str) -> str:
    return rel.replace("\\", "/")


def iter_files(path, want: Callable[[str], bool]) -> Iterator[Tuple[str, bytes]]:
    """Yield (relative_path, bytes) for every file whose lower-cased relative
    path satisfies `want`. Works for a .zip, a folder, or a single file."""
    path = Path(path)
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for name in sorted(zf.namelist()):
                if name.endswith("/"):
                    continue
                if want(_norm(name).lower()):
                    yield _norm(name), zf.read(name)
    elif path.is_dir():
        for f in sorted(path.rglob("*")):
            if f.is_file():
                rel = _norm(str(f.relative_to(path)))
                if want(rel.lower()):
                    yield rel, f.read_bytes()
    elif path.is_file():
        if want(path.name.lower()):
            yield path.name, path.read_bytes()


def basename(rel: str) -> str:
    return _norm(rel).rsplit("/", 1)[-1].lower()


def contains(path, suffix: str) -> bool:
    """True if the export holds any file ending in `suffix`."""
    return any(True for _ in iter_files(path, lambda r: r.endswith(suffix)))


def hash_path(path) -> str:
    """Stable identity for an export (so re-importing it changes nothing)."""
    path = Path(path)
    h = hashlib.sha256()
    if path.is_file():
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    else:
        for rel, data in iter_files(path, lambda r: True):
            h.update(rel.encode())
            h.update(hashlib.sha256(data).digest())
    return h.hexdigest()
