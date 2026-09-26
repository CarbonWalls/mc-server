import socket, struct, sys
def varint(n):
    out=b''
    while True:
        b=n&0x7F; n>>=7
        if n: out+=bytes([b|0x80])
        else: out+=bytes([b]); break
    return out
def readvarint(buf, i):
    n=0; shift=0
    while True:
        b=buf[i]; i+=1
        n |= (b&0x7F)<<shift
        if not (b&0x80): break
        shift+=7
    return n,i
host=sys.argv[1]; port=int(sys.argv[2])
s=socket.socket(); s.settimeout(12)
s.connect((host,port))
# handshake: packet id 0, protocol -1, host string, port, next state 1
hostb=host.encode()
payload=varint(0)+varint(-1 & 0xFFFFFFFF if False else 0)+varint(len(hostb))+hostb+struct.pack('>H',port)+varint(1)
# note: protocol varint should be a valid varint; use 768 (1.21.11-ish)
payload=varint(0)+varint(768)+varint(len(hostb))+hostb+struct.pack('>H',port)+varint(1)
s.sendall(varint(len(payload))+payload)
# request: packet id 0
req=varint(0); s.sendall(varint(len(req))+req)
# read response
data=b''
while True:
    try:
        c=s.recv(4096)
    except socket.timeout:
        break
    if not c: break
    data+=c
    if len(data)>2000: break
s.close()
if not data:
    print("NO DATA / connection refused"); sys.exit(1)
i=0; length,i=readvarint(data,i); pid,i=readvarint(data,i)
jlen,i=readvarint(data,i)
js=data[i:i+jlen].decode('utf-8','replace')
print(js)
