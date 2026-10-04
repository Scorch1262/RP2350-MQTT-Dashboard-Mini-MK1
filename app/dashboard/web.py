# HTTP-Server + WebSocket (RFC 6455) fuer MicroPython-asyncio

import asyncio
import binascii
import struct

try:
    from hashlib import sha1 as _sha1

    def sha1(data):
        return _sha1(data).digest()
except ImportError:
    def _rol(x, n):
        return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF

    def sha1(data):
        h = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0]
        ml = len(data) * 8
        data = bytes(data) + b"\x80"
        data += b"\x00" * ((56 - len(data) % 64) % 64)
        data += struct.pack(">Q", ml)
        for off in range(0, len(data), 64):
            w = list(struct.unpack(">16I", data[off:off + 64]))
            for i in range(16, 80):
                w.append(_rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1))
            a, b, c, d, e = h
            for i in range(80):
                if i < 20:
                    f = (b & c) | (~b & d)
                    k = 0x5A827999
                elif i < 40:
                    f = b ^ c ^ d
                    k = 0x6ED9EBA1
                elif i < 60:
                    f = (b & c) | (b & d) | (c & d)
                    k = 0x8F1BBCDC
                else:
                    f = b ^ c ^ d
                    k = 0xCA62C1D6
                t = (_rol(a, 5) + (f & 0xFFFFFFFF) + e + k + w[i]) & 0xFFFFFFFF
                e = d
                d = c
                c = _rol(b, 30)
                b = a
                a = t
            h = [(x + y) & 0xFFFFFFFF for x, y in zip(h, (a, b, c, d, e))]
        return struct.pack(">5I", *h)

# Lazy-Imports von asyncio sofort ausloesen (keine Allokation spaeter im Betrieb)
_Event = asyncio.Event
asyncio.Lock
asyncio.start_server
asyncio.wait_for

WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_CLIENTS = 6
MAX_QUEUE = 80
MAX_IN_FRAME = 16384


def _hdr(op, n):
    if n < 126:
        return struct.pack("!BB", 0x80 | op, n)
    if n < 65536:
        return struct.pack("!BBH", 0x80 | op, 126, n)
    return struct.pack("!BBQ", 0x80 | op, 127, n)


class WSClient:
    def __init__(self, r, w):
        self.r = r
        self.w = w
        self.q = []
        self.ev = _Event()
        self.alive = True

    def send(self, text, droppable=False):
        if not self.alive:
            return
        q = self.q
        if len(q) >= MAX_QUEUE:
            # aelteste verwerfbare Nachricht entfernen
            for i in range(len(q)):
                if q[i][1]:
                    q.pop(i)
                    break
            else:
                if droppable:
                    return
        q.append((text, droppable, 0x1))
        self.ev.set()

    async def sender(self):
        try:
            while self.alive:
                await self.ev.wait()
                self.ev.clear()
                while self.q and self.alive:
                    text, _, op = self.q.pop(0)
                    if callable(text):
                        # erst beim Senden erzeugen (spart RAM bei vielen Clients)
                        text = text()
                        if text is None:
                            continue
                    if isinstance(text, list):
                        await self._write_parts(text)
                    else:
                        await self._write_frame(op, text.encode() if isinstance(text, str) else text)
        except Exception as e:
            print("[WS] Sendefehler:", e)
        self.alive = False

    async def _write_parts(self, parts):
        # Ein Text-Frame aus vielen kleinen Teilen - ohne grossen Gesamtstring
        n = 0
        for p in parts:
            n += len(p.encode()) if isinstance(p, str) else len(p)
        self.w.write(_hdr(0x1, n))
        k = 0
        for p in parts:
            self.w.write(p.encode() if isinstance(p, str) else p)
            k += 1
            if k % 16 == 0:
                await self.w.drain()
        await self.w.drain()

    async def _write_frame(self, op, data):
        n = len(data)
        w = self.w
        w.write(_hdr(op, n))
        mv = memoryview(data)
        for i in range(0, n, 4096):
            w.write(mv[i:i + 4096])
            await w.drain()
        if n == 0:
            await w.drain()

    async def read_message(self):
        # liefert str oder None (Verbindung zu)
        buf = b""
        while True:
            h = await self.r.readexactly(2)
            fin = h[0] & 0x80
            op = h[0] & 0x0F
            masked = h[1] & 0x80
            n = h[1] & 0x7F
            if n == 126:
                n = struct.unpack("!H", await self.r.readexactly(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", await self.r.readexactly(8))[0]
            if n > MAX_IN_FRAME:
                return None
            mask = await self.r.readexactly(4) if masked else None
            data = bytearray(await self.r.readexactly(n)) if n else bytearray()
            if mask:
                for i in range(n):
                    data[i] ^= mask[i & 3]
            if op == 0x8:  # close
                return None
            if op == 0x9:  # ping -> pong
                self.q.insert(0, (bytes(data), False, 0xA))
                self.ev.set()
                continue
            if op == 0xA:
                continue
            buf += data
            if fin:
                return buf.decode()


class WebServer:
    def __init__(self, routes, on_ws_message, on_ws_open=None, on_ws_close=None):
        self.routes = routes      # path -> callable() -> (status, ctype, body_bytes, extra_headers)
        self.on_ws_message = on_ws_message
        self.on_ws_open = on_ws_open
        self.on_ws_close = on_ws_close
        self.clients = []

    def broadcast(self, text, droppable=False):
        for c in self.clients:
            c.send(text, droppable)

    async def start(self, port):
        await asyncio.start_server(self._handle, "0.0.0.0", port, backlog=8)
        print("[Web] Server laeuft auf Port", port)

    async def _handle(self, r, w):
        try:
            line = await asyncio.wait_for(r.readline(), 10)
            if not line:
                raise OSError("leer")
            parts = line.decode().split()
            method = parts[0] if parts else ""
            path = parts[1] if len(parts) > 1 else "/"
            headers = {}
            while True:
                h = await asyncio.wait_for(r.readline(), 10)
                if not h or h == b"\r\n":
                    break
                k, _, v = h.decode().partition(":")
                headers[k.strip().lower()] = v.strip()
            path = path.split("?")[0]
            if path == "/ws" and "websocket" in headers.get("upgrade", "").lower():
                await self._ws(r, w, headers)
                return
            fn = self.routes.get(path)
            if fn is None or method not in ("GET", "HEAD"):
                await self._resp(w, "404 Not Found", "text/plain", b"Nicht gefunden")
            else:
                status, ctype, body, extra = fn()
                await self._resp(w, status, ctype, body, extra, method == "HEAD")
        except Exception as e:
            if str(e) != "leer":
                print("[Web] Fehler:", repr(e))
        try:
            w.close()
            await w.wait_closed()
        except Exception:
            pass

    async def _resp(self, w, status, ctype, body, extra="", head=False):
        hdr = "HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\n%s\r\n" % (
            status, ctype, len(body), extra)
        w.write(hdr.encode())
        await w.drain()
        if head:
            return
        mv = memoryview(body)
        for i in range(0, len(body), 2048):
            w.write(mv[i:i + 2048])
            await w.drain()

    async def _ws(self, r, w, headers):
        if len(self.clients) >= MAX_CLIENTS:
            # aeltesten Client trennen
            old = self.clients.pop(0)
            old.alive = False
            old.ev.set()
            try:
                old.w.close()
            except Exception:
                pass
        key = headers.get("sec-websocket-key", "").encode()
        acc = binascii.b2a_base64(sha1(key + WS_GUID)).strip()
        w.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + acc + b"\r\n\r\n")
        await w.drain()
        c = WSClient(r, w)
        self.clients.append(c)
        task = asyncio.create_task(c.sender())
        try:
            if self.on_ws_open:
                self.on_ws_open(c)
            while c.alive:
                msg = await c.read_message()
                if msg is None:
                    break
                try:
                    self.on_ws_message(c, msg)
                except Exception as e:
                    print("[WS] Handler-Fehler:", repr(e))
        except Exception:
            pass
        c.alive = False
        c.ev.set()
        if c in self.clients:
            self.clients.remove(c)
        if self.on_ws_close:
            self.on_ws_close(c)
        try:
            task.cancel()
        except Exception:
            pass
