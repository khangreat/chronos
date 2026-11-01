"""Native messaging framing.

Browsers speak to a native host over stdio using a simple frame: a 4-byte
length (native byte order) followed by that many bytes of UTF-8 JSON. These
helpers read and write that frame. Pure and testable against any binary stream.
"""

from __future__ import annotations

import json
import struct
from typing import Optional

HOST_NAME = "com.chronos.capture"
MAX_MESSAGE = 8 * 1024 * 1024  # guard against a runaway length prefix


def read_message(stream) -> Optional[dict]:
    raw_len = stream.read(4)
    if len(raw_len) < 4:
        return None  # EOF
    length = struct.unpack("@I", raw_len)[0]
    if length > MAX_MESSAGE:
        raise ValueError(f"message too large: {length}")
    data = stream.read(length)
    return json.loads(data.decode("utf-8"))


def write_message(stream, obj: dict) -> None:
    data = json.dumps(obj).encode("utf-8")
    stream.write(struct.pack("@I", len(data)))
    stream.write(data)
    stream.flush()
