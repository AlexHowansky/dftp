"""End-to-end integration tests."""

import pytest


@pytest.mark.asyncio
async def test_pwd(client):
    resp = await client.command("PWD")
    assert resp["status"] == "ok"
    assert resp["data"]["path"] == "/"


@pytest.mark.asyncio
async def test_list_root(client):
    resp = await client.command("LIST")
    assert resp["status"] == "ok"
    names = {e["name"] for e in resp["data"]["entries"]}
    assert "hello.txt" in names
    assert "subdir" in names


@pytest.mark.asyncio
async def test_cd_and_pwd(client):
    resp = await client.command("CD", path="subdir")
    assert resp["status"] == "ok"
    assert resp["data"]["path"] == "/subdir"

    resp = await client.command("PWD")
    assert resp["data"]["path"] == "/subdir"


@pytest.mark.asyncio
async def test_cd_nonexistent(client):
    resp = await client.command("CD", path="nonexistent")
    assert resp["status"] == "error"


@pytest.mark.asyncio
async def test_mkdir_and_rmdir(client):
    resp = await client.command("MKDIR", path="newdir")
    assert resp["status"] == "ok"

    resp = await client.command("LIST")
    names = {e["name"] for e in resp["data"]["entries"]}
    assert "newdir" in names

    resp = await client.command("RMDIR", path="newdir")
    assert resp["status"] == "ok"

    resp = await client.command("LIST")
    names = {e["name"] for e in resp["data"]["entries"]}
    assert "newdir" not in names


@pytest.mark.asyncio
async def test_delete(client, server):
    # Create a test file
    (server["root"] / "deleteme.txt").write_text("bye")
    resp = await client.command("DELETE", path="deleteme.txt")
    assert resp["status"] == "ok"
    assert not (server["root"] / "deleteme.txt").exists()


@pytest.mark.asyncio
async def test_download(client, tmp_path):
    local = str(tmp_path / "downloaded.txt")
    nbytes = await client.download("hello.txt", local)
    assert nbytes == 13
    assert open(local).read() == "Hello, world!"


@pytest.mark.asyncio
async def test_upload(client, server, tmp_path):
    local = tmp_path / "upload_src.txt"
    local.write_text("uploaded content")
    nbytes = await client.upload(str(local), "uploaded.txt")
    assert nbytes == 16
    assert (server["root"] / "uploaded.txt").read_text() == "uploaded content"


@pytest.mark.asyncio
async def test_cd_dotdot(client):
    await client.command("CD", path="subdir")
    resp = await client.command("CD", path="..")
    assert resp["status"] == "ok"
    assert resp["data"]["path"] == "/"
