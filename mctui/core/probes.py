import json
import socket
import struct
import time

from . import download

MAGIC = bytes.fromhex("00FFFF00FEFEFEFEFDFDFDFD12345678")
JAVA_PROTOCOL = 768


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


def _read_varint_from(buf: bytes, index: int) -> tuple:
    number = 0
    shift = 0
    while True:
        if index >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[index]
        index += 1
        number |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return number, index
        shift += 7
        if shift > 35:
            raise ValueError("varint too long")


def raknet_probe(host: str, port: int, timeout: float = 5.0) -> dict:
    started = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        stamp = int(time.time() * 1000) & 0xFFFFFFFFFFFFFFFF
        packet = b"\x01" + struct.pack(">Q", stamp) + MAGIC + struct.pack(">Q", 0x1234567890ABCDEF)
        sock.sendto(packet, (host, port))
        data, addr = sock.recvfrom(4096)
        return {
            "ok": True,
            "bytes": len(data),
            "from": f"{addr[0]}:{addr[1]}",
            "type": f"0x{data[0]:02x}",
            "ms": int((time.time() - started) * 1000),
            "error": "",
        }
    except socket.timeout:
        return {"ok": False, "bytes": 0, "from": "", "type": "", "ms": int((time.time() - started) * 1000),
                "error": f"no reply within {timeout}s"}
    except OSError as exc:
        return {"ok": False, "bytes": 0, "from": "", "type": "", "ms": 0, "error": str(exc)}
    finally:
        sock.close()


def java_status_ping(host: str, port: int, timeout: float = 8.0, protocol: int = JAVA_PROTOCOL) -> dict:
    started = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        host_bytes = host.encode()
        handshake = (
            _varint(0)
            + _varint(protocol)
            + _varint(len(host_bytes))
            + host_bytes
            + struct.pack(">H", port)
            + _varint(1)
        )
        sock.sendall(_varint(len(handshake)) + handshake)
        request = _varint(0)
        sock.sendall(_varint(len(request)) + request)
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline and len(buf) < 65536:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            if len(buf) > 8 and _complete(buf):
                break
        if not buf:
            return {"ok": False, "error": "connected but no response", "ms": 0}
        length, idx = _read_varint_from(buf, 0)
        packet_id, idx = _read_varint_from(buf, idx)
        if packet_id != 0:
            return {"ok": False, "error": f"unexpected packet id {packet_id}", "ms": 0}
        jlen, idx = _read_varint_from(buf, idx)
        payload = buf[idx:idx + jlen]
        data = json.loads(payload.decode("utf-8", "replace"))
        return {
            "ok": True,
            "error": "",
            "ms": int((time.time() - started) * 1000),
            "description": _motd_text(data),
            "version": (data.get("version") or {}).get("name", ""),
            "protocol": (data.get("version") or {}).get("protocol", ""),
            "players_online": (data.get("players") or {}).get("online", 0),
            "players_max": (data.get("players") or {}).get("max", 0),
            "sample": [p.get("name", "") for p in ((data.get("players") or {}).get("sample") or [])[:10]],
            "favicon": bool(data.get("favicon")),
            "raw": data,
        }
    except (ConnectionRefusedError, socket.gaierror, OSError) as exc:
        return {"ok": False, "error": str(exc), "ms": int((time.time() - started) * 1000)}
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"bad response: {exc}", "ms": int((time.time() - started) * 1000)}
    finally:
        sock.close()


def _complete(buf: bytes) -> bool:
    try:
        length, idx = _read_varint_from(buf, 0)
    except ValueError:
        return False
    if len(buf) < idx + length:
        return False
    try:
        _pid, idx2 = _read_varint_from(buf, idx)
        jlen, idx3 = _read_varint_from(buf, idx2)
    except ValueError:
        return False
    return len(buf) >= idx3 + jlen


def _motd_text(data: dict) -> str:
    desc = data.get("description")
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        if "text" in desc:
            parts = [str(desc.get("text", ""))]
            for extra in desc.get("extra") or []:
                if isinstance(extra, dict):
                    parts.append(str(extra.get("text", "")))
                else:
                    parts.append(str(extra))
            return "".join(parts)
        return json.dumps(desc)[:120]
    return ""


def mcstatus_java(host: str, port: int = 25565, timeout: int = 20) -> dict:
    url = f"https://api.mcstatus.io/v2/status/java/{host}?port={int(port)}"
    try:
        data = download.fetch_json(url, timeout=timeout)
    except download.DownloadError as exc:
        return {"ok": False, "error": str(exc), "source": "mcstatus.io"}
    if not data.get("online"):
        return {"ok": False, "error": data.get("error", "offline"), "source": "mcstatus.io",
                "ip": data.get("ip_address", "")}
    players = data.get("players") or {}
    return {
        "ok": True,
        "error": "",
        "source": "mcstatus.io",
        "online": True,
        "ip": data.get("ip_address", ""),
        "players_online": players.get("online", 0),
        "players_max": players.get("max", 0),
        "version": (data.get("version") or {}).get("name_raw", ""),
        "motd": _clean(data.get("motd")),
        "ms": int(data.get("retrieved_at", 0)),
    }


def mcstatus_bedrock(host: str, port: int = 19132, timeout: int = 20) -> dict:
    url = f"https://api.mcstatus.io/v2/status/bedrock/{host}:{int(port)}"
    try:
        data = download.fetch_json(url, timeout=timeout)
    except download.DownloadError as exc:
        return {"ok": False, "error": str(exc), "source": "mcstatus.io"}
    if not data.get("online"):
        return {"ok": False, "error": data.get("error", "offline"), "source": "mcstatus.io",
                "ip": data.get("ip_address", "")}
    return {
        "ok": True,
        "error": "",
        "source": "mcstatus.io",
        "online": True,
        "ip": data.get("ip_address", ""),
        "players_online": (data.get("players") or {}).get("online", 0),
        "players_max": (data.get("players") or {}).get("max", 0),
        "version": (data.get("version") or {}).get("name", ""),
        "motd": _clean(data.get("motd")),
        "server_id": data.get("server_id", ""),
    }


def _clean(motd) -> str:
    if isinstance(motd, dict):
        raw = motd.get("raw") or motd.get("clean") or ""
        if isinstance(raw, list):
            return "".join(str(x) for x in raw)
        return str(raw)
    return str(motd or "")
