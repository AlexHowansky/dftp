"""Shared test fixtures."""

import ssl
from functools import partial
from pathlib import Path

import pytest
import pytest_asyncio
from aioquic.asyncio import connect, serve
from aioquic.quic.configuration import QuicConfiguration

from dftp.generate_cert import generate
from dftp.server.app import FtpServerProtocol
from dftp.client.connection import FtpClientProtocol, FtpConnection


@pytest.fixture
def tmp_certs(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    generate(cert, key)
    return cert, key


@pytest.fixture
def server_root(tmp_path):
    root = tmp_path / "ftproot"
    root.mkdir()
    (root / "hello.txt").write_text("Hello, world!")
    (root / "subdir").mkdir()
    (root / "subdir" / "nested.txt").write_text("nested content")
    return root


@pytest_asyncio.fixture
async def server(tmp_certs, server_root):
    cert, key = tmp_certs
    config = QuicConfiguration(
        is_client=False,
        alpn_protocols=["h3"],
        max_datagram_frame_size=65536,
    )
    config.load_cert_chain(str(cert), str(key))

    factory = partial(FtpServerProtocol, root_dir=server_root)
    srv = await serve(
        "127.0.0.1",
        0,
        configuration=config,
        create_protocol=factory,
    )
    port = srv._transport.get_extra_info("sockname")[1]
    yield {"server": srv, "port": port, "root": server_root, "cert": cert}
    srv.close()


@pytest_asyncio.fixture
async def client(server, tmp_certs):
    cert, _ = tmp_certs
    config = QuicConfiguration(
        is_client=True,
        alpn_protocols=["h3"],
        max_datagram_frame_size=65536,
    )
    config.verify_mode = ssl.CERT_NONE

    async with connect(
        "127.0.0.1",
        server["port"],
        configuration=config,
        create_protocol=FtpClientProtocol,
    ) as protocol:
        await protocol.connect_session()
        yield FtpConnection(protocol)
