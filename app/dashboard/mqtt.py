# Minimaler asynchroner MQTT-3.1.1-Client (QoS 0) fuer MicroPython-asyncio

import asyncio
import struct
import time

MAX_PAYLOAD = 2048


def _enc_len(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return out


def _str(s):
    if isinstance(s, str):
        s = s.encode()
    return struct.pack("!H", len(s)) + s


class MQTTClient:
    def __init__(self, client_id, on_message, on_state=None):
        self.client_id = client_id
        self.on_message = on_message
        self.on_state = on_state
        self.host = None
        self.port = 1883
        self.user = ""
        self.password = ""
        self.connected = False
        self._w = None
        self._lock = asyncio.Lock()
        self._restart = False
        self._last_rx = 0

    def configure(self, host, port=1883, user="", password=""):
        self.host = host or None
        self.port = int(port or 1883)
        self.user = user or ""
        self.password = password or ""
        self._restart = True
        self._close()

    def _set_state(self, c):
        if self.connected != c:
            self.connected = c
            if self.on_state:
                try:
                    self.on_state(c)
                except Exception as e:
                    print("[MQTT] on_state:", e)

    def _close(self):
        w = self._w
        self._w = None
        if w:
            try:
                w.close()
            except Exception:
                pass
        self._set_state(False)

    async def _send(self, data):
        w = self._w
        if not w:
            return False
        async with self._lock:
            try:
                w.write(data)
                await w.drain()
                return True
            except Exception as e:
                print("[MQTT] Sendefehler:", e)
                self._close()
                return False

    async def publish(self, topic, payload, retain=False):
        t = _str(topic)
        if isinstance(payload, str):
            payload = payload.encode()
        body = t + payload
        hdr = bytearray([0x31 if retain else 0x30]) + _enc_len(len(body))
        return await self._send(bytes(hdr) + body)

    async def _connect(self):
        print("[MQTT] Verbinde mit %s:%d" % (self.host, self.port))
        r, w = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), 10)
        flags = 0x02  # clean session
        payload = _str(self.client_id)
        if self.user:
            flags |= 0x80
            payload += _str(self.user)
            if self.password:
                flags |= 0x40
                payload += _str(self.password)
        var = _str("MQTT") + bytes([4, flags]) + struct.pack("!H", 60)
        body = var + payload
        w.write(bytes([0x10]) + bytes(_enc_len(len(body))) + body)
        await w.drain()
        resp = await asyncio.wait_for(r.readexactly(4), 10)
        if resp[0] != 0x20 or resp[3] != 0:
            w.close()
            raise OSError("CONNACK Fehler %d" % resp[3])
        self._w = w
        # SUBSCRIBE '#' QoS 0
        body = struct.pack("!H", 1) + _str("#") + b"\x00"
        w.write(bytes([0x82]) + bytes(_enc_len(len(body))) + body)
        await w.drain()
        self._last_rx = time.ticks_ms()
        self._set_state(True)
        print("[MQTT] Verbunden, abonniert: #")
        return r

    async def _read_loop(self, r):
        while True:
            b = await r.readexactly(1)
            self._last_rx = time.ticks_ms()
            typ = b[0] & 0xF0
            n = 0
            mul = 1
            while True:
                c = (await r.readexactly(1))[0]
                n += (c & 0x7F) * mul
                if not c & 0x80:
                    break
                mul *= 128
            if typ == 0x30:  # PUBLISH
                qos = (b[0] >> 1) & 3
                tl = struct.unpack("!H", await r.readexactly(2))[0]
                topic = await r.readexactly(tl)
                n -= 2 + tl
                if qos:
                    pid = await r.readexactly(2)
                    n -= 2
                if n > MAX_PAYLOAD:
                    # zu gross: verwerfen (in Bloecken lesen)
                    while n > 0:
                        k = min(n, 512)
                        await r.readexactly(k)
                        n -= k
                    payload = None
                else:
                    payload = await r.readexactly(n) if n else b""
                if qos == 1:
                    await self._send(b"\x40\x02" + pid)
                if payload is not None:
                    try:
                        self.on_message(topic, payload)
                    except Exception as e:
                        print("[MQTT] on_message:", e)
            else:
                if n:
                    await r.readexactly(n)

    async def _pinger(self):
        while True:
            await asyncio.sleep(20)
            if self._w:
                if time.ticks_diff(time.ticks_ms(), self._last_rx) > 90000:
                    print("[MQTT] Timeout")
                    self._close()
                else:
                    await self._send(b"\xc0\x00")

    async def run(self):
        asyncio.create_task(self._pinger())
        while True:
            if not self.host:
                await asyncio.sleep(1)
                continue
            self._restart = False
            r = None
            try:
                r = await self._connect()
                await self._read_loop(r)
            except Exception as e:
                if not self._restart:
                    print("[MQTT] Verbindung getrennt:", repr(e))
            self._close()
            if not self._restart:
                await asyncio.sleep(5)
