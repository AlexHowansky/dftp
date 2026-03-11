# dftp

An FTP-like file transfer client and server built on WebTransport (HTTP/3 over QUIC) instead of traditional FTP. Uses Python and [aioquic](https://github.com/aioquic/aioquic).

## Requirements

- Python 3.10+

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For development (includes pytest):

```bash
pip install -e ".[dev]"
```

## Quick Start

### 1. Generate TLS Certificates

A TLS certificate is required to run the server. Generate a self-signed cert:

```bash
python -m dftp.generate_cert
```

This creates `certs/cert.pem` and `certs/key.pem` in the current directory.

### 2. Start the Server

```bash
python -m dftp.server
```

This serves the current directory on port 4433. To serve a specific directory:

```bash
python -m dftp.server --root /path/to/serve
```

Server options:

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `4433` | Bind port |
| `--cert` | `certs/cert.pem` | TLS certificate path |
| `--key` | `certs/key.pem` | TLS private key path |
| `--root` | `.` | Root directory to serve |
| `-v` | off | Verbose (debug) logging |

### 3. Connect with the Client

```bash
python -m dftp.client localhost
```

By default the client accepts self-signed certificates. To verify against a specific CA:

```bash
python -m dftp.client myserver.example.com --ca-cert certs/cert.pem
```

Client options:

| Flag | Default | Description |
|------|---------|-------------|
| `host` | `localhost` | Server hostname |
| `--port` | `4433` | Server port |
| `--ca-cert` | none | CA certificate for verification |
| `-v` | off | Verbose (debug) logging |

## Client Commands

Once connected, you get an interactive `ftp>` prompt with these commands:

| Command | Description |
|---------|-------------|
| `ls [path]` | List directory contents |
| `cd <path>` | Change remote directory |
| `pwd` | Print current remote directory |
| `get <remote> [local]` | Download a file |
| `put <local> [remote]` | Upload a file |
| `mkdir <path>` | Create a directory |
| `rmdir <path>` | Remove a directory |
| `rm <path>` | Delete a file |
| `quit` | Disconnect and exit |

### Example Session

```
$ python -m dftp.client localhost
Connected to localhost:4433
WebTransport FTP client. Type 'help' for commands.
ftp> ls
d            2026-03-11T10:00:00  docs
-       1234 2026-03-11T09:30:00  notes.txt
ftp> cd docs
/docs
ftp> get report.pdf
Downloading report.pdf -> report.pdf
Transferred 54321 bytes
ftp> put ~/local-file.txt remote-file.txt
Uploading ~/local-file.txt -> remote-file.txt
Transferred 789 bytes
ftp> quit
Goodbye.
```

## Installed Scripts

After `pip install`, three console scripts are available:

- `dftp-server` — start the server
- `dftp-client` — start the client
- `dftp-gencert` — generate TLS certificates

## Running Tests

```bash
python -m pytest tests/ -v
```

## How It Works

dftp uses **WebTransport over HTTP/3 (QUIC)** as its transport layer. A WebTransport session is established via an HTTP/3 CONNECT request, then bidirectional QUIC streams carry commands and file data.

- **Control channel**: A bidirectional WebTransport stream carrying length-prefixed JSON frames (4-byte big-endian size + JSON payload).
- **Data transfers**: File uploads and downloads use separate WebTransport streams, allowing transfers to happen without blocking the control channel.
- **Security**: The server sandboxes all filesystem operations under the configured root directory, preventing path traversal attacks.
