# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FTP-like client and server using WebTransport (HTTP/3 over QUIC) instead of traditional FTP. Built with Python and aioquic.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Generate TLS certs (required before running server)
python -m claude_ftp.generate_cert

# Run server (serves current directory by default)
python -m claude_ftp.server --root /path/to/serve -v

# Run client
python -m claude_ftp.client localhost --port 4433 --insecure

# Run all tests
python -m pytest tests/ -v

# Run a single test
python -m pytest tests/test_integration.py::test_download -xvs
```

## Architecture

**Transport**: WebTransport over HTTP/3 (QUIC). Uses `aioquic` library. The CONNECT request establishes a WebTransport session, then a bidirectional WebTransport stream serves as the control channel. File transfers use additional WebTransport streams.

**Protocol** (`src/claude_ftp/protocol.py`): Length-prefixed JSON frames (4-byte big-endian uint32 + JSON payload). Commands: LIST, PWD, CD, MKDIR, RMDIR, DELETE, GET, PUT, QUIT.

**Key architectural pattern**: The control channel and data streams are WebTransport bidirectional streams (NOT the CONNECT stream itself). Data is sent via `_quic.send_stream_data()` (raw QUIC), not `h3.send_data()` (which wraps in HTTP/3 DATA frames and requires headers).

**aioquic workaround** (`mark_wt_stream_bidi` in protocol.py): `create_webtransport_stream()` doesn't register the stream in H3's internal `_stream` dict, so the H3 layer won't emit `WebTransportStreamDataReceived` for incoming data on locally-created bidirectional streams. The workaround manually creates the H3Stream entry with `frame_type=0x41` and `session_id` set.

**Server** (`src/claude_ftp/server/`):
- `app.py`: `FtpServerProtocol` subclasses `QuicConnectionProtocol`, handles QUIC/H3 events, accepts WebTransport sessions, routes `WebTransportStreamDataReceived` to per-client sessions
- `session.py`: `ClientSession` dispatches commands, manages virtual cwd, coordinates file transfers
- `filesystem.py`: Sandboxed filesystem ops; all paths resolve under a root directory with traversal prevention

**Client** (`src/claude_ftp/client/`):
- `connection.py`: `FtpClientProtocol` manages the WebTransport session and control stream; `FtpConnection` provides high-level command/download/upload methods
- `cli.py`: Interactive REPL using `cmd.Cmd`, bridges sync CLI with async connection via `asyncio.run_coroutine_threadsafe`
- `__main__.py`: Runs the asyncio event loop in a background thread, keeps the WebTransport connection alive while the CLI runs in the main thread

**QuicConfiguration**: Both client and server must set `max_datagram_frame_size=65536` for WebTransport support. Server needs `--insecure` or CA cert on client for self-signed certs.
