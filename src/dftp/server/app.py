"""HTTP/3 server with WebTransport support for FTP."""

import logging
from pathlib import Path
from typing import Dict, Optional

from aioquic.asyncio import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import (
    H3Event,
    HeadersReceived,
    DataReceived,
    WebTransportStreamDataReceived,
)
from aioquic.quic.events import QuicEvent, ProtocolNegotiated

from ..protocol import WT_PATH
from .filesystem import Filesystem
from .session import ClientSession

logger = logging.getLogger(__name__)


class FtpServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, root_dir: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self.h3: Optional[H3Connection] = None
        self.root_dir = root_dir
        self.filesystem = Filesystem(root_dir)
        # session_id -> ClientSession
        self._sessions: Dict[int, ClientSession] = {}

    def quic_event_received(self, event: QuicEvent):
        if isinstance(event, ProtocolNegotiated):
            self.h3 = H3Connection(self._quic, enable_webtransport=True)

        if self.h3 is not None:
            for h3_event in self.h3.handle_event(event):
                self._h3_event_received(h3_event)

    def _h3_event_received(self, event: H3Event):
        if isinstance(event, HeadersReceived):
            headers = dict(event.headers)
            method = headers.get(b":method", b"").decode()
            path = headers.get(b":path", b"").decode()
            protocol = headers.get(b":protocol", b"").decode()

            if method == "CONNECT" and protocol == "webtransport" and path == WT_PATH:
                self._accept_session(event.stream_id)
            else:
                self.h3.send_headers(
                    event.stream_id,
                    [(b":status", b"404")],
                    end_stream=True,
                )
                self.transmit()

        elif isinstance(event, WebTransportStreamDataReceived):
            session_id = event.session_id
            if session_id in self._sessions:
                session = self._sessions[session_id]
                session.handle_stream_data(
                    event.stream_id, event.data, event.stream_ended
                )

    def _accept_session(self, stream_id: int):
        """Accept a WebTransport session."""
        self.h3.send_headers(
            stream_id,
            [(b":status", b"200")],
            end_stream=False,
        )
        self.transmit()

        session = ClientSession(
            h3_conn=self.h3,
            quic_conn=self._quic,
            session_id=stream_id,
            filesystem=self.filesystem,
            transmit=self.transmit,
        )
        self._sessions[stream_id] = session
        logger.info("WebTransport session accepted: %d", stream_id)
