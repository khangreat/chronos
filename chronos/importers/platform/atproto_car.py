"""Read a Bluesky repository export (.car) without any extra libraries.

Bluesky's "Export my data" gives a CAR v1 file: a header, then blocks keyed by
content ID (CID), each encoded as DAG-CBOR. The repository commit points at a
Merkle Search Tree whose keys are "<collection>/<record key>" — for example
"app.bsky.feed.post/3kq..." — and whose values are the CIDs of the records.

This module implements just enough of each format to list the records:
  varints, CIDs (v0 and v1), the DAG-CBOR subset atproto uses, CAR v1 framing,
  and an MST walk. It never executes or fetches anything.
"""

from __future__ import annotations

import struct
from typing import Dict, Iterator, Optional, Tuple

CID_TAG = 42


class CarError(ValueError):
    pass


class CID(bytes):
    """A content ID, kept as its binary form (hashable, comparable)."""
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CID({self.hex()[:16]}…)"


# -- primitives --------------------------------------------------------------- #
def read_varint(buf: bytes, pos: int) -> Tuple[int, int]:
    value = shift = 0
    while True:
        if pos >= len(buf):
            raise CarError("truncated varint")
        b = buf[pos]; pos += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise CarError("varint too long")


def read_cid(buf: bytes, pos: int) -> Tuple[CID, int]:
    start = pos
    if buf[pos:pos + 2] == b"\x12\x20":             # CIDv0: bare sha2-256 multihash
        return CID(buf[pos:pos + 34]), pos + 34
    version, pos = read_varint(buf, pos)
    if version != 1:
        raise CarError(f"unsupported CID version {version}")
    _codec, pos = read_varint(buf, pos)
    _code, pos = read_varint(buf, pos)
    length, pos = read_varint(buf, pos)
    pos += length
    if pos > len(buf):
        raise CarError("truncated CID")
    return CID(buf[start:pos]), pos


# -- DAG-CBOR ------------------------------------------------------------------ #
def _decode(buf: bytes, pos: int):
    if pos >= len(buf):
        raise CarError("truncated CBOR")
    ib = buf[pos]; pos += 1
    major, info = ib >> 5, ib & 0x1F
    if info < 24:
        arg = info
    elif info == 24:
        arg = buf[pos]; pos += 1
    elif info == 25:
        arg = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
    elif info == 26:
        if major == 7:
            return struct.unpack(">f", buf[pos:pos + 4])[0], pos + 4
        arg = struct.unpack(">I", buf[pos:pos + 4])[0]; pos += 4
    elif info == 27:
        if major == 7:
            return struct.unpack(">d", buf[pos:pos + 8])[0], pos + 8
        arg = struct.unpack(">Q", buf[pos:pos + 8])[0]; pos += 8
    else:
        raise CarError("indefinite-length CBOR is not valid DAG-CBOR")

    if major == 0:
        return arg, pos
    if major == 1:
        return -1 - arg, pos
    if major == 2:
        return bytes(buf[pos:pos + arg]), pos + arg
    if major == 3:
        return buf[pos:pos + arg].decode("utf-8", "replace"), pos + arg
    if major == 4:
        out = []
        for _ in range(arg):
            v, pos = _decode(buf, pos); out.append(v)
        return out, pos
    if major == 5:
        out = {}
        for _ in range(arg):
            k, pos = _decode(buf, pos)
            v, pos = _decode(buf, pos)
            out[k] = v
        return out, pos
    if major == 6:
        v, pos = _decode(buf, pos)
        if arg == CID_TAG and isinstance(v, bytes) and v[:1] == b"\x00":
            return CID(v[1:]), pos
        return v, pos
    if major == 7:
        return {20: False, 21: True, 22: None, 23: None}.get(arg), pos
    raise CarError("bad CBOR")


def decode_cbor(data: bytes):
    value, _ = _decode(data, 0)
    return value


# -- CAR ----------------------------------------------------------------------- #
def read_car(data: bytes) -> Tuple[list, Dict[CID, bytes]]:
    """Return (roots, {cid: block_bytes})."""
    hlen, pos = read_varint(data, 0)
    header = decode_cbor(data[pos:pos + hlen])
    pos += hlen
    if not isinstance(header, dict) or header.get("version") != 1:
        raise CarError("not a CAR v1 file")
    blocks: Dict[CID, bytes] = {}
    while pos < len(data):
        slen, pos = read_varint(data, pos)
        end = pos + slen
        if end > len(data):
            raise CarError("truncated block")
        cid, bpos = read_cid(data, pos)
        blocks[cid] = data[bpos:end]
        pos = end
    return list(header.get("roots") or []), blocks


def _walk_mst(cid: Optional[CID], blocks: Dict[CID, bytes],
              depth: int = 0) -> Iterator[Tuple[str, CID]]:
    if cid is None or cid not in blocks:
        return
    if depth > 64:
        raise CarError("tree too deep")
    node = decode_cbor(blocks[cid])
    yield from _walk_mst(node.get("l"), blocks, depth + 1)
    prev = b""
    for e in node.get("e") or []:
        key = prev[:e.get("p", 0)] + (e.get("k") or b"")
        prev = key
        if isinstance(e.get("v"), CID):
            yield key.decode("utf-8", "replace"), e["v"]
        yield from _walk_mst(e.get("t"), blocks, depth + 1)


def read_repo(data: bytes) -> Tuple[str, Dict[str, dict]]:
    """Return (did, {"collection/rkey": record}) from a repository CAR."""
    roots, blocks = read_car(data)
    if not roots or roots[0] not in blocks:
        raise CarError("the repository's commit is missing")
    commit = decode_cbor(blocks[roots[0]])
    did = commit.get("did", "") if isinstance(commit, dict) else ""
    records = {}
    for key, rcid in _walk_mst(commit.get("data"), blocks):
        raw = blocks.get(rcid)
        if raw is None:
            continue
        try:
            rec = decode_cbor(raw)
        except CarError:
            continue
        if isinstance(rec, dict):
            records[key] = rec
    return did, records
