import json
import os
import socket
import struct
import sys
import threading
import time
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mctui.core import download, probes

TMP = Path(__file__).resolve().parent / "tmp_net"
STATUS_JSON = {
    "version": {"name": "1.21.11", "protocol": 771},
    "players": {"max": 20, "online": 2, "sample": [{"name": "Notch"}, {"name": "Steve"}]},
    "description": {"text": "Hello ", "extra": [{"text": "World"}]},
    "enforcesSecureChat": True,
}


def _varint(value: int) -> bytes:
    out = b""
    value &= 0xFFFFFFFF
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out += bytes([byte | 0x80])
        else:
            out += bytes([byte])
            break
    return out


class FakeStatusServer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.connections = 0

    def run(self):
        while True:
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            try:
                conn.settimeout(3)
                try:
                    conn.recv(4096)
                except socket.timeout:
                    pass
                body = json.dumps(STATUS_JSON).encode()
                payload = _varint(0) + _varint(len(body)) + body
                conn.sendall(_varint(len(payload)) + payload)
            finally:
                conn.close()

    def stop(self):
        try:
            self.sock.close()
        except OSError:
            pass


def test_varint():
    for n in (0, 1, 127, 128, 255, 300, 771, 65535, 2097151):
        encoded = probes._varint(n)
        decoded, idx = probes._read_varint_from(encoded, 0)
        assert decoded == n and idx == len(encoded), (n, encoded, decoded)
    assert probes._varint(771) == bytes([0x83, 0x06])
    print("ok varint")


def test_java_ping():
    server = FakeStatusServer()
    server.start()
    try:
        res = probes.java_status_ping("127.0.0.1", server.port, timeout=5)
        assert res["ok"], res
        assert res["version"] == "1.21.11", res
        assert res["players_online"] == 2 and res["players_max"] == 20
        assert res["description"] == "Hello World", res["description"]
        assert res["sample"] == ["Notch", "Steve"]
        assert res["favicon"] is False
        assert server.connections >= 1
    finally:
        server.stop()
    down = probes.java_status_ping("127.0.0.1", 1, timeout=2)
    assert not down["ok"] and down["error"], down
    print(f"ok java status ping ({res['ms']}ms, refused: {down['error'][:40]})")


def test_raknet():
    res = probes.raknet_probe("127.0.0.1", 9, timeout=1.0)
    assert not res["ok"] and "no reply" in res["error"], res
    print(f"ok raknet (expected timeout: {res['error']})")


def test_mcstatus():
    # the probe targets are example hostnames: this test only checks the
    # wrapper returns a well-formed verdict (it is not an uptime check), and
    # the real public tunnel address of this deployment is never committed
    java_host = os.environ.get("MCTUI_TEST_JAVA_HOST", "example.tun.ply.gg")
    bedrock_host = os.environ.get("MCTUI_TEST_BEDROCK_HOST", "example.tun.ply.gg")
    java = probes.mcstatus_java(java_host, 25565, timeout=20)
    assert isinstance(java["ok"], bool) and "source" in java, java
    bedrock = probes.mcstatus_bedrock(bedrock_host, 19132, timeout=20)
    assert isinstance(bedrock["ok"], bool), bedrock
    print(f"ok mcstatus java={java['ok']}:{java.get('error','')[:30]} bedrock={bedrock['ok']}:{bedrock.get('error','')[:30]}")


def test_download_verified():
    TMP.mkdir(parents=True, exist_ok=True)
    versions = download.fetch_json(
        "https://api.modrinth.com/v2/project/luckperms/version?loaders=%5B%22paper%22%5D&limit=1",
        timeout=25,
    )
    version = versions[0]
    remote = version["files"][0]
    dest = TMP / "luckperms.jar"
    if dest.exists():
        dest.unlink()
    seen = []

    def progress(done, total):
        seen.append((done, total))

    res = download.download(
        remote["url"], dest,
        sha512=remote["hashes"]["sha512"],
        expected_size=remote["size"],
        on_progress=progress,
        timeout=60,
    )
    assert res["verified"] and dest.exists()
    assert dest.stat().st_size == remote["size"]
    assert download.sha512_file(dest) == remote["hashes"]["sha512"]
    assert seen and seen[-1][0] == remote["size"]
    print(f"ok download+sha512 ({res['size']} bytes, {len(seen)} progress ticks)")


def test_download_bad_hash():
    TMP.mkdir(parents=True, exist_ok=True)
    dest = TMP / "bad.jar"
    url = "https://cdn.modrinth.com/data/Vebnzrzj/versions/b0mk8uS6/LuckPerms-Bukkit-5.5.71.jar"
    try:
        download.download(url, dest, sha256="0" * 64, expected_size=1501521, timeout=60)
    except download.DownloadError as exc:
        assert "sha256 mismatch" in str(exc), exc
    else:
        raise AssertionError("expected DownloadError")
    assert not dest.exists()
    assert not (TMP / "bad.jar.part").exists()
    try:
        download.download("https://api.modrinth.com/v2/project/does-not-exist-xyz-404", dest, timeout=20)
    except download.DownloadError as exc:
        assert "HTTP 404" in str(exc) or "network" in str(exc), exc
    else:
        raise AssertionError("expected 404 DownloadError")
    print("ok download error paths")


def test_fetch_json_paper():
    query = (
        '{"query":"{ project(key: \\"paper\\") { versions(first: 5, orderBy: {direction: DESC}) '
        '{ edges { node { key } } } } }"}'
    )
    data = download.fetch_json(
        "https://fill.papermc.io/graphql",
        data=query.encode(),
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    keys = [e["node"]["key"] for e in data["data"]["project"]["versions"]["edges"]]
    assert keys and keys[0].startswith("26"), keys
    print(f"ok paper graphql ({', '.join(keys)})")


def main():
    try:
        test_varint()
        test_java_ping()
        test_raknet()
        test_fetch_json_paper()
        test_mcstatus()
        test_download_verified()
        test_download_bad_hash()
        print("PASS net/probes")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
