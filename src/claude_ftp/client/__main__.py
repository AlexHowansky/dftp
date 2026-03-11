"""Entry point for the FTP client: python -m claude_ftp.client"""

import argparse
import asyncio
import logging
import ssl
import threading
from pathlib import Path

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

from .cli import FtpCli, _run_loop_in_thread
from .connection import FtpClientProtocol, FtpConnection


def main():
    parser = argparse.ArgumentParser(description="WebTransport FTP Client")
    parser.add_argument("host", nargs="?", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=4433, help="Server port")
    parser.add_argument("--ca-cert", type=Path, help="CA certificate for verification")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS certificate verification",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = QuicConfiguration(
        is_client=True,
        alpn_protocols=["h3"],
        max_datagram_frame_size=65536,
    )

    if args.insecure:
        config.verify_mode = ssl.CERT_NONE
    elif args.ca_cert:
        config.load_verify_locations(str(args.ca_cert))

    # Create event loop in a background thread
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_loop_in_thread, args=(loop,), daemon=True)
    thread.start()

    # We need the connection to stay alive while the CLI runs,
    # so we use a long-lived coroutine that holds the context manager open
    cli_done = asyncio.Event()
    conn_holder: dict = {}

    async def run_session():
        async with connect(
            args.host,
            args.port,
            configuration=config,
            create_protocol=FtpClientProtocol,
        ) as protocol:
            await protocol.connect_session()
            conn_holder["conn"] = FtpConnection(protocol)
            conn_holder["ready"] = True
            # Keep connection alive until CLI is done
            await cli_done.wait()

    task = asyncio.run_coroutine_threadsafe(run_session(), loop)

    # Wait for connection to be ready
    import time
    for _ in range(150):  # 15 second timeout
        if conn_holder.get("ready"):
            break
        time.sleep(0.1)
    else:
        print("Failed to connect: timeout")
        loop.call_soon_threadsafe(loop.stop)
        return

    print(f"Connected to {args.host}:{args.port}")
    try:
        cli = FtpCli(conn_holder["conn"], loop)
        cli.cmdloop()
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        loop.call_soon_threadsafe(cli_done.set)
        try:
            task.result(timeout=5)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)


if __name__ == "__main__":
    main()
