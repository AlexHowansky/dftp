"""Sandboxed filesystem operations for the FTP server."""

import os
import stat
import time
from pathlib import Path


class FilesystemError(Exception):
    def __init__(self, message: str, code: int = 550):
        super().__init__(message)
        self.code = code


class Filesystem:
    """All operations are sandboxed under root_dir."""

    def __init__(self, root_dir: Path):
        self.root = root_dir.resolve()

    def resolve(self, path: str, cwd: str) -> Path:
        """Resolve a virtual path to a real path, ensuring it stays under root."""
        if path.startswith("/"):
            virtual = Path(path)
        else:
            virtual = Path(cwd) / path
        # Walk parts and track depth to detect traversal above virtual root
        parts = []
        depth = 0
        for part in virtual.parts:
            if part == "/":
                continue
            elif part == "..":
                if depth > 0:
                    parts.pop()
                    depth -= 1
                # else: already at root, clamp (but this means traversal attempt)
            else:
                parts.append(part)
                depth += 1
        # Build real path
        real = self.root / Path(*parts) if parts else self.root
        real = real.resolve()
        # Final safety check: resolved path must be under root
        if not (real == self.root or str(real).startswith(str(self.root) + os.sep)):
            raise FilesystemError("Access denied: path outside root", 553)
        return real

    def listdir(self, path: str, cwd: str) -> list[dict]:
        real = self.resolve(path, cwd)
        if not real.is_dir():
            raise FilesystemError(f"Not a directory: {path}")
        entries = []
        for entry in sorted(real.iterdir()):
            st = entry.stat()
            entries.append({
                "name": entry.name,
                "type": "dir" if stat.S_ISDIR(st.st_mode) else "file",
                "size": st.st_size,
                "modified": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)
                ),
            })
        return entries

    def mkdir(self, path: str, cwd: str):
        real = self.resolve(path, cwd)
        if real.exists():
            raise FilesystemError(f"Already exists: {path}")
        real.mkdir(parents=False)

    def rmdir(self, path: str, cwd: str):
        real = self.resolve(path, cwd)
        if not real.is_dir():
            raise FilesystemError(f"Not a directory: {path}")
        if real == self.root:
            raise FilesystemError("Cannot remove root directory", 553)
        try:
            real.rmdir()
        except OSError as e:
            raise FilesystemError(str(e))

    def delete(self, path: str, cwd: str):
        real = self.resolve(path, cwd)
        if not real.is_file():
            raise FilesystemError(f"Not a file: {path}")
        real.unlink()

    def stat_file(self, path: str, cwd: str) -> dict:
        real = self.resolve(path, cwd)
        if not real.is_file():
            raise FilesystemError(f"Not a file: {path}")
        st = real.stat()
        return {"size": st.st_size, "name": real.name}

    def is_dir(self, path: str, cwd: str) -> bool:
        try:
            real = self.resolve(path, cwd)
            return real.is_dir()
        except FilesystemError:
            return False

    def open_read(self, path: str, cwd: str):
        """Return the resolved Path for reading."""
        real = self.resolve(path, cwd)
        if not real.is_file():
            raise FilesystemError(f"Not a file: {path}")
        return real

    def open_write(self, path: str, cwd: str):
        """Return the resolved Path for writing."""
        real = self.resolve(path, cwd)
        if real.is_dir():
            raise FilesystemError(f"Is a directory: {path}")
        return real
