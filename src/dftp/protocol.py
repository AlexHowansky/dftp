"""Shared protocol definitions for WebTransport FTP."""

import json
import struct
from enum import Enum

# 4-byte big-endian length prefix
HEADER_FMT = "!I"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

# WebTransport endpoint path
WT_PATH = "/ftp"

# Transfer chunk size
CHUNK_SIZE = 65536


class Command(str, Enum):
    LIST = "LIST"
    PWD = "PWD"
    CD = "CD"
    MKDIR = "MKDIR"
    RMDIR = "RMDIR"
    DELETE = "DELETE"
    GET = "GET"
    PUT = "PUT"
    QUIT = "QUIT"


def mark_wt_stream_bidi(h3_conn, stream_id: int, session_id: int):
    """Mark a locally-created WebTransport bidirectional stream for receiving data.

    aioquic's create_webtransport_stream() doesn't register the stream in the
    H3 stream dict, so the H3 layer won't recognize incoming data as WebTransport.
    This workaround creates the H3Stream entry with the right frame_type and
    session_id so the receive path emits WebTransportStreamDataReceived events.
    """
    from aioquic.h3.connection import H3Stream

    if stream_id not in h3_conn._stream:
        h3_conn._stream[stream_id] = H3Stream(stream_id)
    s = h3_conn._stream[stream_id]
    s.frame_type = 0x41  # FrameType.WEBTRANSPORT_STREAM
    s.session_id = session_id


def encode_message(obj: dict) -> bytes:
    """Encode a dict as a length-prefixed JSON frame."""
    payload = json.dumps(obj).encode()
    return struct.pack(HEADER_FMT, len(payload)) + payload


class MessageReader:
    """Stateful buffer that accumulates bytes and yields complete JSON messages."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        self._buf.extend(data)
        messages = []
        while len(self._buf) >= HEADER_SIZE:
            length = struct.unpack(HEADER_FMT, self._buf[:HEADER_SIZE])[0]
            if len(self._buf) < HEADER_SIZE + length:
                break
            payload = self._buf[HEADER_SIZE : HEADER_SIZE + length]
            self._buf = self._buf[HEADER_SIZE + length :]
            messages.append(json.loads(payload))
        return messages
