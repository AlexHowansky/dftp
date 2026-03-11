"""WebTransport client connection manager."""

import asyncio
import logging
from typing import Optional

from aioquic.asyncio import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import (
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from aioquic.quic.events import QuicEvent, ProtocolNegotiated

from ..protocol import CHUNK_SIZE, MessageReader, WT_PATH, encode_message, mark_wt_stream_bidi

logger = logging.getLogger(__name__)


class FtpClientProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.h3: Optional[H3Connection] = None
        self._session_id: Optional[int] = None
        self._control_stream_id: Optional[int] = None
        self._session_ready = asyncio.Event()
        self._reader = MessageReader()
        self._response_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._data_streams: dict[int, dict] = {}

    def quic_event_received(self, event: QuicEvent):
        if isinstance(event, ProtocolNegotiated):
            self.h3 = H3Connection(self._quic, enable_webtransport=True)

        if self.h3 is not None:
            for h3_event in self.h3.handle_event(event):
                self._h3_event_received(h3_event)

    def _h3_event_received(self, event: H3Event):
        if isinstance(event, HeadersReceived):
            headers = dict(event.headers)
            status = headers.get(b":status", b"").decode()
            if status == "200" and self._session_id is None:
                self._session_id = event.stream_id
                self._session_ready.set()
                logger.debug("WebTransport session established: %d", event.stream_id)

        elif isinstance(event, WebTransportStreamDataReceived):
            if event.stream_id == self._control_stream_id:
                for msg in self._reader.feed(event.data):
                    self._response_queue.put_nowait(msg)
            else:
                if event.stream_id not in self._data_streams:
                    self._data_streams[event.stream_id] = {
                        "data": bytearray(),
                        "done": asyncio.Event(),
                    }
                ds = self._data_streams[event.stream_id]
                ds["data"].extend(event.data)
                if event.stream_ended:
                    ds["done"].set()

    def _wt_send(self, stream_id: int, data: bytes, end_stream: bool = False):
        """Send raw data on a WebTransport stream via QUIC layer."""
        self._quic.send_stream_data(stream_id, data, end_stream=end_stream)
        self.transmit()

    async def connect_session(self):
        """Initiate the WebTransport session and open control stream."""
        await asyncio.sleep(0.1)
        if self.h3 is None:
            raise RuntimeError("H3 connection not established")

        stream_id = self._quic.get_next_available_stream_id()
        self.h3.send_headers(
            stream_id=stream_id,
            headers=[
                (b":method", b"CONNECT"),
                (b":scheme", b"https"),
                (b":path", WT_PATH.encode()),
                (b":authority", b"localhost"),
                (b":protocol", b"webtransport"),
            ],
            end_stream=False,
        )
        self.transmit()
        await asyncio.wait_for(self._session_ready.wait(), timeout=10)

        # Create a WebTransport bidirectional stream as the control channel
        self._control_stream_id = self.h3.create_webtransport_stream(
            self._session_id, is_unidirectional=False
        )
        mark_wt_stream_bidi(self.h3, self._control_stream_id, self._session_id)
        self.transmit()

    async def send_command(self, cmd: str, args: dict = None) -> dict:
        msg = {"cmd": cmd}
        if args:
            msg["args"] = args
        data = encode_message(msg)
        self._wt_send(self._control_stream_id, data)
        return await asyncio.wait_for(self._response_queue.get(), timeout=30)

    async def receive_data_stream(self, stream_id: int) -> bytes:
        if stream_id not in self._data_streams:
            self._data_streams[stream_id] = {
                "data": bytearray(),
                "done": asyncio.Event(),
            }
        ds = self._data_streams[stream_id]
        await asyncio.wait_for(ds["done"].wait(), timeout=300)
        data = bytes(ds["data"])
        del self._data_streams[stream_id]
        return data

    def send_data_on_stream(self, stream_id: int, data: bytes, end_stream: bool):
        self._wt_send(stream_id, data, end_stream)

    def create_data_stream(self) -> int:
        stream_id = self.h3.create_webtransport_stream(
            self._session_id, is_unidirectional=False
        )
        mark_wt_stream_bidi(self.h3, stream_id, self._session_id)
        self.transmit()
        return stream_id


class FtpConnection:
    """High-level FTP-over-WebTransport connection."""

    def __init__(self, protocol: FtpClientProtocol):
        self._protocol = protocol

    async def command(self, cmd: str, **kwargs) -> dict:
        args = kwargs if kwargs else None
        return await self._protocol.send_command(cmd, args)

    async def download(self, remote_path: str, local_path: str) -> int:
        resp = await self.command("GET", path=remote_path)
        if resp.get("status") != "ok":
            raise RuntimeError(resp.get("message", "Download failed"))
        stream_id = resp["data"]["stream_id"]
        data = await self._protocol.receive_data_stream(stream_id)
        with open(local_path, "wb") as f:
            f.write(data)
        return len(data)

    async def upload(self, local_path: str, remote_path: str) -> int:
        import os

        file_size = os.path.getsize(local_path)

        # Create the data stream first so we can include its ID in PUT
        stream_id = self._protocol.create_data_stream()

        resp = await self.command(
            "PUT", path=remote_path, size=file_size, stream_id=stream_id
        )
        if resp.get("status") != "ok":
            raise RuntimeError(resp.get("message", "Upload failed"))

        # Send file data on the data stream
        with open(local_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                self._protocol.send_data_on_stream(stream_id, chunk, end_stream=False)
                await asyncio.sleep(0)

        self._protocol.send_data_on_stream(stream_id, b"", end_stream=True)

        # Wait for server upload confirmation
        resp = await asyncio.wait_for(
            self._protocol._response_queue.get(), timeout=60
        )
        if resp.get("status") != "ok":
            raise RuntimeError(resp.get("message", "Upload failed"))
        return file_size
