"""Entry point for the FTP server: python -m dftp.server"""

import argparse
import asyncio
import logging
import ssl
from functools import partial
from pathlib import Path

from aioquic.asyncio import serve
from aioquic.quic.configuration import QuicConfiguration

from .app import FtpServerProtocol


def main():
    parser = argparse.ArgumentParser(description="WebTransport FTP Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=4433, help="Bind port")
    parser.add_argument(
        "--cert", type=Path, default=Path("certs/cert.pem"), help="TLS certificate"
    )
    parser.add_argument(
        "--key", type=Path, default=Path("certs/key.pem"), help="TLS private key"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Root directory to serve (default: current directory)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    root_dir = args.root.resolve()
    if not root_dir.is_dir():
        parser.error(f"Root directory does not exist: {root_dir}")

    config = QuicConfiguration(
        is_client=False,
        alpn_protocols=["h3"],
        max_datagram_frame_size=65536,
    )
    config.load_cert_chain(str(args.cert), str(args.key))

    logging.info("Starting WebTransport FTP server on %s:%d", args.host, args.port)
    logging.info("Serving directory: %s", root_dir)

    loop = asyncio.new_event_loop()

    protocol_factory = partial(FtpServerProtocol, root_dir=root_dir)

    loop.run_until_complete(
        serve(
            args.host,
            args.port,
            configuration=config,
            create_protocol=protocol_factory,
        )
    )

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("Server shutting down")


if __name__ == "__main__":
    main()
