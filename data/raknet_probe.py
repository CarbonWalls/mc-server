#!/usr/bin/env python3
"""RakNet Unconnected Ping probe.

Wire format (order matters — magic does NOT come first):
  0x01 | 8-byte BE time | 16-byte MAGIC | 8-byte BE GUID
MAGIC = 00FFFF00FEFEFEFEFDFDFDFD12345678
"""
import socket, struct, sys, time

MAGIC = bytes.fromhex("00FFFF00FEFEFEFEFDFDFDFD12345678")

def probe(host: str, port: int, timeout: float = 5.0) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        t = int(time.time() * 1000) & 0xFFFFFFFFFFFFFFFF
        pkt = b"\x01" + struct.pack(">Q", t) + MAGIC + struct.pack(">Q", 0x1234567890ABCDEF)
        s.sendto(pkt, (host, port))
        data, addr = s.recvfrom(4096)
        print(f"REPLY {len(data)} bytes from {addr[0]}:{addr[1]}  id=0x{data[0]:02x}")
        return True
    except socket.timeout:
        print("NO REPLY (timeout)")
        return False
    finally:
        s.close()

if __name__ == "__main__":
    host = sys.argv[1]
    port = int(sys.argv[2])
    timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
    sys.exit(0 if probe(host, port, timeout) else 1)
