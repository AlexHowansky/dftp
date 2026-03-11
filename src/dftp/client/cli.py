"""Interactive FTP-like CLI."""

import asyncio
import cmd
import os
import shlex
import sys
import threading

from .connection import FtpConnection


def _run_loop_in_thread(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


class FtpCli(cmd.Cmd):
    intro = "WebTransport FTP client. Type 'help' for commands."
    prompt = "ftp> "

    def __init__(self, connection: FtpConnection, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.conn = connection
        self.loop = loop

    def _run(self, coro):
        """Run an async coroutine from the sync cmd loop."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=60)
        except TimeoutError:
            print("Error: command timed out")
            return None
        except Exception as e:
            print(f"Error: {e}")
            return None

    def _print_response(self, resp: dict):
        if resp is None:
            return
        if resp.get("status") == "error":
            print(f"Error {resp.get('code', '')}: {resp.get('message', '')}")

    def do_ls(self, arg):
        """List directory contents: ls [path]"""
        kwargs = {}
        if arg.strip():
            kwargs["path"] = arg.strip()
        resp = self._run(self.conn.command("LIST", **kwargs))
        if resp is None:
            return
        if resp.get("status") != "ok":
            self._print_response(resp)
            return
        entries = resp["data"]["entries"]
        if not entries:
            print("(empty directory)")
            return
        # Format as table
        name_w = max(len(e["name"]) for e in entries)
        for e in entries:
            type_mark = "d" if e["type"] == "dir" else "-"
            size_str = str(e["size"]).rjust(10) if e["type"] == "file" else " " * 10
            print(f"{type_mark} {size_str} {e['modified']}  {e['name']}")

    def do_dir(self, arg):
        """Alias for ls"""
        self.do_ls(arg)

    def do_cd(self, arg):
        """Change directory: cd <path>"""
        path = arg.strip() or "/"
        resp = self._run(self.conn.command("CD", path=path))
        if resp is None:
            return
        if resp.get("status") == "ok":
            print(resp["data"]["path"])
        else:
            self._print_response(resp)

    def do_pwd(self, arg):
        """Print working directory"""
        resp = self._run(self.conn.command("PWD"))
        if resp is None:
            return
        if resp.get("status") == "ok":
            print(resp["data"]["path"])
        else:
            self._print_response(resp)

    def do_mkdir(self, arg):
        """Create directory: mkdir <path>"""
        if not arg.strip():
            print("Usage: mkdir <path>")
            return
        resp = self._run(self.conn.command("MKDIR", path=arg.strip()))
        if resp is None:
            return
        if resp.get("status") == "ok":
            print(resp.get("message", "OK"))
        else:
            self._print_response(resp)

    def do_rmdir(self, arg):
        """Remove directory: rmdir <path>"""
        if not arg.strip():
            print("Usage: rmdir <path>")
            return
        resp = self._run(self.conn.command("RMDIR", path=arg.strip()))
        if resp is None:
            return
        if resp.get("status") == "ok":
            print(resp.get("message", "OK"))
        else:
            self._print_response(resp)

    def do_rm(self, arg):
        """Delete file: rm <path>"""
        if not arg.strip():
            print("Usage: rm <path>")
            return
        resp = self._run(self.conn.command("DELETE", path=arg.strip()))
        if resp is None:
            return
        if resp.get("status") == "ok":
            print(resp.get("message", "OK"))
        else:
            self._print_response(resp)

    def do_delete(self, arg):
        """Alias for rm"""
        self.do_rm(arg)

    def do_get(self, arg):
        """Download file: get <remote_path> [local_path]"""
        parts = shlex.split(arg) if arg.strip() else []
        if not parts:
            print("Usage: get <remote_path> [local_path]")
            return
        remote = parts[0]
        local = parts[1] if len(parts) > 1 else os.path.basename(remote)
        print(f"Downloading {remote} -> {local}")
        nbytes = self._run(self.conn.download(remote, local))
        if nbytes is not None:
            print(f"Transferred {nbytes} bytes")

    def do_put(self, arg):
        """Upload file: put <local_path> [remote_path]"""
        parts = shlex.split(arg) if arg.strip() else []
        if not parts:
            print("Usage: put <local_path> [remote_path]")
            return
        local = parts[0]
        remote = parts[1] if len(parts) > 1 else os.path.basename(local)
        if not os.path.isfile(local):
            print(f"Local file not found: {local}")
            return
        print(f"Uploading {local} -> {remote}")
        nbytes = self._run(self.conn.upload(local, remote))
        if nbytes is not None:
            print(f"Transferred {nbytes} bytes")

    def do_quit(self, arg):
        """Disconnect and exit"""
        self._run(self.conn.command("QUIT"))
        print("Goodbye.")
        return True

    def do_exit(self, arg):
        """Alias for quit"""
        return self.do_quit(arg)

    def do_EOF(self, arg):
        """Handle Ctrl+D"""
        print()
        return self.do_quit(arg)
