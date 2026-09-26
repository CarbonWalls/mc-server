import hashlib
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

CHUNK = 65536
USER_AGENT = "mc-tui/1.0 (+self-hosted minecraft server manager)"
DEFAULT_TIMEOUT = 60
MAX_ATTEMPTS = 6          # a big jar on a flaky link often needs more than one go
RETRY_BACKOFF = 2.0       # seconds, doubled per attempt


class DownloadError(Exception):
    pass


def _request(url: str, timeout: int = DEFAULT_TIMEOUT, extra_headers=None) -> urllib.request.Request:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }
    if extra_headers:
        headers.update(extra_headers)
    return urllib.request.Request(url, headers=headers)


def open_stream(url: str, timeout: int = DEFAULT_TIMEOUT, range_header=None):
    ctx = ssl.create_default_context()
    extra = {"Range": range_header} if range_header else None
    try:
        resp = urllib.request.urlopen(_request(url, timeout, extra), timeout=timeout, context=ctx)
    except urllib.error.HTTPError as exc:
        raise DownloadError(f"HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise DownloadError(f"network error for {url}: {exc.reason}") from exc
    return resp


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha512_file(path) -> str:
    digest = hashlib.sha512()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _digest_existing(digests: list, part_path) -> None:
    """Feed the bytes already sitting in a .part file into the digests."""
    if not any(digests):
        return
    with open(part_path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            for digest in digests:
                if digest is not None:
                    digest.update(chunk)


def _backoff(attempt: int) -> None:
    """Sleep before a retry: 2s, 4s, 8s ... capped at 10s."""
    time.sleep(min(RETRY_BACKOFF * 2 ** (attempt - 1), 10.0))


def download(url: str, dest, sha256: str | None = None, sha512: str | None = None,
             expected_size: int | None = None, on_progress=None, timeout: int = 120,
             attempts: int = MAX_ATTEMPTS) -> dict:
    """Download ``url`` to ``dest`` atomically, verifying hashes and size.

    A big artifact on a flaky link is retried; when the server supports
    ranges, an interrupted transfer resumes from the bytes already in the
    ``.part`` file instead of starting over.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    total = expected_size
    attempt = 0
    while True:
        attempt += 1
        have = part.stat().st_size if part.is_file() else 0
        digest256 = hashlib.sha256() if sha256 else None
        digest512 = hashlib.sha512() if sha512 else None
        try:
            resp = open_stream(url, timeout=timeout,
                               range_header=(f"bytes={have}-" if have else None))
        except (DownloadError, OSError, ssl.SSLError) as exc:
            if attempt >= attempts:
                _cleanup(part)
                if isinstance(exc, DownloadError):
                    raise
                raise DownloadError(f"open failed: {exc}") from exc
            _backoff(attempt)
            continue
        done = 0
        mode = "wb"
        resumed = getattr(resp, "status", 200) == 206
        try:
            if have and resumed:
                # the server accepted the range: hash the bytes we already have
                _digest_existing([digest256, digest512], part)
                done = have
                mode = "ab"
            if total is None and not resumed:
                header_len = resp.headers.get("Content-Length") if resp.headers else None
                if header_len:
                    try:
                        total = int(header_len)
                    except ValueError:
                        total = None
            with open(part, mode) as out:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    if digest256:
                        digest256.update(chunk)
                    if digest512:
                        digest512.update(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total or 0)
        except (OSError, ssl.SSLError) as exc:
            if attempt >= attempts:
                _cleanup(part)
                raise DownloadError(f"write failed: {exc}") from exc
            _backoff(attempt)
            continue
        finally:
            try:
                resp.close()
            except OSError:
                pass
        if total and done < total:
            # the stream ended early (dropped connection): retry and resume
            if attempt >= attempts:
                _cleanup(part)
                raise DownloadError(f"short read: got {done} of {total} bytes")
            _backoff(attempt)
            continue
        break

    size = part.stat().st_size
    if total and size != total:
        _cleanup(part)
        raise DownloadError(f"size mismatch: got {size} bytes, expected {total}")
    if digest256:
        got = digest256.hexdigest()
        if got.lower() != sha256.lower():
            _cleanup(part)
            raise DownloadError(f"sha256 mismatch: expected {sha256}, got {got}")
    if digest512:
        got = digest512.hexdigest()
        if got.lower() != sha512.lower():
            _cleanup(part)
            raise DownloadError(f"sha512 mismatch: expected {sha512}, got {got}")
    os.replace(part, dest)
    return {
        "path": str(dest),
        "size": size,
        "sha256": digest256.hexdigest() if digest256 else None,
        "verified": bool(sha256 or sha512),
        "url": url,
    }


def probe_head(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            length = resp.headers.get("Content-Length")
            return {
                "ok": True,
                "status": resp.status,
                "size": int(length) if length and length.isdigit() else None,
                "type": resp.headers.get("Content-Type", ""),
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "size": None, "type": ""}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "status": 0, "size": None, "type": "", "error": str(exc)}


def fetch_text(url: str, timeout: int = 30) -> str:
    resp = open_stream(url, timeout=timeout)
    try:
        raw = b""
        while True:
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            raw += chunk
            if len(raw) > 8 * 1024 * 1024:
                raise DownloadError("response too large")
        return raw.decode("utf-8", "replace")
    finally:
        try:
            resp.close()
        except OSError:
            pass


def fetch_json(url: str, timeout: int = 30, data: bytes | None = None,
               headers: dict | None = None):
    import json

    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(500).decode("utf-8", "replace")
        except Exception:
            pass
        raise DownloadError(f"HTTP {exc.code} for {url}: {body[:200]}") from exc
    except urllib.error.URLError as exc:
        raise DownloadError(f"network error for {url}: {exc.reason}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise DownloadError(f"invalid JSON from {url}") from exc


def _cleanup(part) -> None:
    try:
        Path(part).unlink()
    except OSError:
        pass
