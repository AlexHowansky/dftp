"""Tests for the sandboxed filesystem."""

import pytest
from pathlib import Path

from dftp.server.filesystem import Filesystem, FilesystemError


@pytest.fixture
def fs(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "file.txt").write_text("content")
    (root / "subdir").mkdir()
    (root / "subdir" / "inner.txt").write_text("inner")
    return Filesystem(root)


class TestResolve:
    def test_absolute_path(self, fs):
        result = fs.resolve("/file.txt", "/")
        assert result.name == "file.txt"

    def test_relative_path(self, fs):
        result = fs.resolve("file.txt", "/")
        assert result.name == "file.txt"

    def test_path_traversal_clamped(self, fs):
        # ../../etc/passwd from / clamps to /etc/passwd inside sandbox
        result = fs.resolve("../../etc/passwd", "/")
        # Result must still be under root (not the real /etc/passwd)
        assert str(result).startswith(str(fs.root))

    def test_dotdot_in_middle(self, fs):
        result = fs.resolve("subdir/../file.txt", "/")
        assert result.name == "file.txt"

    def test_dotdot_at_root(self, fs):
        # Should clamp to root, not escape
        result = fs.resolve("/..", "/")
        assert result == fs.root


class TestListdir:
    def test_list_root(self, fs):
        entries = fs.listdir("/", "/")
        names = {e["name"] for e in entries}
        assert "file.txt" in names
        assert "subdir" in names

    def test_list_subdir(self, fs):
        entries = fs.listdir("/subdir", "/")
        assert len(entries) == 1
        assert entries[0]["name"] == "inner.txt"

    def test_list_nonexistent(self, fs):
        with pytest.raises(FilesystemError):
            fs.listdir("/nope", "/")


class TestMkdir:
    def test_create(self, fs):
        fs.mkdir("newdir", "/")
        assert fs.is_dir("newdir", "/")

    def test_already_exists(self, fs):
        with pytest.raises(FilesystemError):
            fs.mkdir("subdir", "/")


class TestRmdir:
    def test_remove_empty(self, fs):
        fs.mkdir("empty", "/")
        fs.rmdir("empty", "/")
        assert not fs.is_dir("empty", "/")

    def test_remove_nonempty(self, fs):
        with pytest.raises(FilesystemError):
            fs.rmdir("subdir", "/")


class TestDelete:
    def test_delete_file(self, fs):
        fs.delete("file.txt", "/")
        with pytest.raises(FilesystemError):
            fs.stat_file("file.txt", "/")

    def test_delete_nonexistent(self, fs):
        with pytest.raises(FilesystemError):
            fs.delete("nope.txt", "/")
