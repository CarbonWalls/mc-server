"""Tests for the download helper: retry, range-resume and hash verification.

A local stdlib HTTP server stands in for the internet, so these run offline.
The interesting case is a flaky link: the server drops the first transfer(s)
mid-stream and the client must resume from the bytes it already has.
"""
import hashlib
import http.server
import os
import shutil
import socketserver
import sys
import threading
from pathlib import Path

import mctui_test_env

ROOT = mctui_test_env.activate()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mctui.core import download  # noqa: E402

TMP = ROOT / "tmp_download"
BODY = bytes((i * 37 + 11) & 0xFF for i in range(1024 * 1024))   # 1 MiB, deterministic
SHA256 = hashlib.sha256(BODY).hexdigest()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/big":
            self.send_error(404, "nope")
            return
        srv = self.server
        rng = self.headers.get("Range")
        start = 0
        if rng and rng.startswith("bytes="):
            start = int(rng.split("=", 1)[1].split("-", 1)[0] or 0)
        if start > len(BODY):
            self.send_response(416)
            self.end_headers()
            return
        if srv.drop_remaining > 0:
            # flaky link: send only part of what was asked, then drop the
            # connection (the client sees a short read and retries/resumes)
            srv.drop_remaining -= 1
            srv.hits += 1
            wanted = len(BODY) - start
            send = min(wanted // 2, 200 * 1024)
            self.send_response(200)
            self.send_header("Content-Length", str(wanted))
            self.end_headers()
            self.wfile.write(BODY[start:start + send])
            self.close_connection = True
            return
        srv.hits += 1
        data = BODY[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        if start:
            self.send_header("Content-Range", f"bytes {start}-{len(BODY)-1}/{len(BODY)}")
        self.end_headers()
        self.wfile.write(data)


class FlakyServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, drops=0):
        self.drop_remaining = drops
        self.hits = 0
        super().__init__(("127.0.0.1", 0), Handler)


class GrumpyHandler(http.server.BaseHTTPRequestHandler):
    """Fails the first N requests outright, then serves the body once."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        srv = self.server
        if srv.fails_left > 0:
            srv.fails_left -= 1
            srv.hits += 1
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        srv.hits += 1
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)


class GrumpyServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, fails=0):
        self.fails_left = fails
        self.hits = 0
        super().__init__(("127.0.0.1", 0), GrumpyHandler)


def setup():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    # retries must not actually sleep while the tests run
    download._backoff = lambda attempt: None


def teardown():
    try:
        download.MAX_ATTEMPTS = _REAL_ATTEMPTS
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)


def _url(server):
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/big"


def test_resume_after_drops():
    srv = FlakyServer(drops=3)               # three dropped transfers, then clean
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        dest = TMP / "big.bin"
        res = download.download(_url(srv), dest, sha256=SHA256,
                                expected_size=len(BODY), timeout=30)
        assert res["verified"] and res["size"] == len(BODY), res
        assert dest.read_bytes() == BODY
        # it took more than one request to get there
        assert srv.hits >= 4, srv.hits
        print(f"ok resume after 3 drops ({srv.hits} requests, sha256 verified)")
    finally:
        srv.shutdown()
        srv.server_close()


def test_retry_on_server_errors():
    srv = GrumpyServer(fails=2)              # two 503s, then success
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        dest = TMP / "grumpy.bin"
        res = download.download(_url(srv), dest, sha256=SHA256,
                                expected_size=len(BODY), timeout=30)
        assert res["size"] == len(BODY) and res["verified"], res
        assert dest.read_bytes() == BODY
        assert srv.hits == 3, srv.hits
        print(f"ok retry past 2x HTTP 503 ({srv.hits} requests)")
    finally:
        srv.shutdown()
        srv.server_close()


def test_giving_up():
    srv = GrumpyServer(fails=99)             # always 503
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        dest = TMP / "never.bin"
        try:
            download.download(_url(srv), dest, sha256=SHA256, timeout=10)
        except download.DownloadError as exc:
            assert "503" in str(exc) or "HTTP" in str(exc), exc
        else:
            raise AssertionError("permanent failure should raise DownloadError")
        assert not dest.exists(), "a failed download must not leave a final file"
        print(f"ok gives up after MAX_ATTEMPTS ({srv.hits} 503s, no partial file)")
    finally:
        srv.shutdown()
        srv.server_close()


def test_bad_hash_still_rejected():
    srv = FlakyServer(drops=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        dest = TMP / "badhash.bin"
        try:
            download.download(_url(srv), dest, sha256="0" * 64, timeout=30)
        except download.DownloadError as exc:
            assert "sha256 mismatch" in str(exc), exc
        else:
            raise AssertionError("a wrong hash must be rejected")
        assert not dest.exists()
        print("ok sha256 mismatch rejected")
    finally:
        srv.shutdown()
        srv.server_close()


_REAL_ATTEMPTS = download.MAX_ATTEMPTS


def main():
    setup()
    try:
        test_resume_after_drops()
        test_retry_on_server_errors()
        test_giving_up()
        test_bad_hash_still_rejected()
        print("PASS download")
    finally:
        teardown()
        mctui_test_env.discard(ROOT)


if __name__ == "__main__":
    main()
