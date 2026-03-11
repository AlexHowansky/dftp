"""Per-client WebTransport session handler."""

import asyncio
import logging
from pathlib import Path

from aioquic.h3.connection import H3Connection
from aioquic.quic.connection import QuicConnection

from ..protocol import CHUNK_SIZE, Command, MessageReader, encode_message, mark_wt_stream_bidi
from .filesystem import Filesystem, FilesystemError

logger = logging.getLogger(__name__)


class ClientSession:
    def __init__(
        self,
        h3_conn: H3Connection,
        quic_conn: QuicConnection,
        session_id: int,
        filesystem: Filesystem,
        transmit: callable,
    ):
        self.h3 = h3_conn
        self.quic = quic_conn
        self.session_id = session_id
        self.fs = filesystem
        self.transmit = transmit
        self.cwd = "/"
        self.control_stream_id: int | None = None
        self.reader = MessageReader()
        self._pending_uploads: dict[int, dict] = {}
        self._closed = False

    def _wt_send(self, stream_id: int, data: bytes, end_stream: bool = False):
        """Send raw data on a WebTransport stream via QUIC layer."""
        self.quic.send_stream_data(stream_id, data, end_stream=end_stream)
        self.transmit()

    def send_response(self, obj: dict):
        if self.control_stream_id is None:
            logger.warning("No control stream set, cannot send response")
            return
        data = encode_message(obj)
        self._wt_send(self.control_stream_id, data)

    def handle_stream_data(self, stream_id: int, data: bytes, stream_ended: bool):
        if self.control_stream_id is None:
            self.control_stream_id = stream_id

        if stream_id == self.control_stream_id:
            for msg in self.reader.feed(data):
                self._dispatch(msg)
            return

        # Data stream (file upload)
        if stream_id in self._pending_uploads:
            upload = self._pending_uploads[stream_id]
            upload["buf"].extend(data)
            if stream_ended:
                self._finish_upload(stream_id, upload)
        else:
            self._pending_uploads[stream_id] = {
                "path": None,
                "buf": bytearray(data),
            }
            if stream_ended:
                self._pending_uploads[stream_id]["ended"] = True

    def _register_upload_stream(self, stream_id: int, path: str):
        if stream_id in self._pending_uploads:
            self._pending_uploads[stream_id]["path"] = path
            if self._pending_uploads[stream_id].get("ended"):
                self._finish_upload(stream_id, self._pending_uploads[stream_id])
        else:
            self._pending_uploads[stream_id] = {
                "path": path,
                "buf": bytearray(),
            }

    def _finish_upload(self, stream_id: int, upload: dict):
        path = upload["path"]
        if path is None:
            upload["ended"] = True
            return
        try:
            real = self.fs.open_write(path, self.cwd)
            real.write_bytes(upload["buf"])
            self.send_response({
                "status": "ok",
                "message": f"Uploaded {len(upload['buf'])} bytes",
            })
        except FilesystemError as e:
            self.send_response({"status": "error", "code": e.code, "message": str(e)})
        finally:
            self._pending_uploads.pop(stream_id, None)

    def _dispatch(self, msg: dict):
        cmd = msg.get("cmd", "").upper()
        args = msg.get("args", {})

        try:
            if cmd == Command.QUIT:
                self.send_response({"status": "ok", "message": "Goodbye"})
                self._closed = True
                return

            if cmd == Command.PWD:
                self.send_response({"status": "ok", "data": {"path": self.cwd}})

            elif cmd == Command.CD:
                path = args.get("path", "/")
                if not self.fs.is_dir(path, self.cwd):
                    self.send_response({
                        "status": "error",
                        "code": 550,
                        "message": f"Not a directory: {path}",
                    })
                    return
                if path.startswith("/"):
                    new_cwd = path
                else:
                    new_cwd = str(Path(self.cwd) / path)
                parts = []
                for part in Path(new_cwd).parts:
                    if part == "/":
                        continue
                    elif part == "..":
                        if parts:
                            parts.pop()
                    else:
                        parts.append(part)
                self.cwd = "/" + "/".join(parts)
                self.send_response({"status": "ok", "data": {"path": self.cwd}})

            elif cmd == Command.LIST:
                path = args.get("path", self.cwd)
                entries = self.fs.listdir(path, self.cwd)
                self.send_response({"status": "ok", "data": {"entries": entries}})

            elif cmd == Command.MKDIR:
                path = args.get("path")
                if not path:
                    self.send_response({
                        "status": "error", "code": 501, "message": "Path required",
                    })
                    return
                self.fs.mkdir(path, self.cwd)
                self.send_response({
                    "status": "ok", "message": f"Directory created: {path}",
                })

            elif cmd == Command.RMDIR:
                path = args.get("path")
                if not path:
                    self.send_response({
                        "status": "error", "code": 501, "message": "Path required",
                    })
                    return
                self.fs.rmdir(path, self.cwd)
                self.send_response({
                    "status": "ok", "message": f"Directory removed: {path}",
                })

            elif cmd == Command.DELETE:
                path = args.get("path")
                if not path:
                    self.send_response({
                        "status": "error", "code": 501, "message": "Path required",
                    })
                    return
                self.fs.delete(path, self.cwd)
                self.send_response({
                    "status": "ok", "message": f"File deleted: {path}",
                })

            elif cmd == Command.GET:
                path = args.get("path")
                if not path:
                    self.send_response({
                        "status": "error", "code": 501, "message": "Path required",
                    })
                    return
                info = self.fs.stat_file(path, self.cwd)
                real = self.fs.open_read(path, self.cwd)

                stream_id = self.h3.create_webtransport_stream(
                    self.session_id, is_unidirectional=False
                )
                mark_wt_stream_bidi(self.h3, stream_id, self.session_id)
                self.send_response({
                    "status": "ok",
                    "data": {
                        "stream_id": stream_id,
                        "size": info["size"],
                        "name": info["name"],
                    },
                })

                asyncio.ensure_future(self._send_file(stream_id, real, info["size"]))

            elif cmd == Command.PUT:
                path = args.get("path")
                if not path:
                    self.send_response({
                        "status": "error", "code": 501, "message": "Path required",
                    })
                    return
                try:
                    self.fs.open_write(path, self.cwd)
                except FilesystemError as e:
                    self.send_response({
                        "status": "error", "code": e.code, "message": str(e),
                    })
                    return

                self.send_response({"status": "ok", "message": "Ready for upload"})

                stream_id = args.get("stream_id")
                if stream_id is not None:
                    self._register_upload_stream(stream_id, path)

            elif cmd == "UPLOAD_STREAM":
                stream_id = args.get("stream_id")
                path = args.get("path")
                if stream_id is not None and path:
                    self._register_upload_stream(stream_id, path)

            else:
                self.send_response({
                    "status": "error",
                    "code": 502,
                    "message": f"Unknown command: {cmd}",
                })

        except FilesystemError as e:
            self.send_response({
                "status": "error", "code": e.code, "message": str(e),
            })
        except Exception as e:
            logger.exception("Error handling command %s", cmd)
            self.send_response({
                "status": "error", "code": 500, "message": f"Internal error: {e}",
            })

    async def _send_file(self, stream_id: int, path: Path, size: int):
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    self._wt_send(stream_id, chunk)
                    await asyncio.sleep(0)
            self._wt_send(stream_id, b"", end_stream=True)
        except Exception:
            logger.exception("Error sending file on stream %d", stream_id)
