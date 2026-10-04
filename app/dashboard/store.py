# Speicher fuer Topic-Zustaende und Diagramm-Historie (RAM, Ringpuffer)
#
# Statt 20000 Rohpunkten pro Topic (PC-Version) werden Werte in Zeit-Slots
# gemittelt abgelegt - zwei Stufen:
#   fein : 30 s Aufloesung, 720 Slots  ->  6 h
#   grob : 4 min Aufloesung, 720 Slots -> 48 h
# Pro Topic ~5,8 KB RAM, unabhaengig von der Nachrichtenrate.
# Die Puffer werden beim Start einmalig reserviert (Pool), damit der Heap
# im Dauerbetrieb nicht fragmentiert und spaeter keine grossen Bloecke fehlen.

import time
from array import array

import struct

NAN = float("nan")
_NAN4 = struct.pack("<f", NAN)

FINE_RES = 30
COARSE_RES = 240
SLOTS = 720

MAX_HIST = 24       # max. Topics mit Historie (Diagramme / virtuelle Topics), je ~5,8 KB
MAX_STATES = 400    # max. bekannte Topics (Topic-Liste, letzter Wert)
MAX_VALUE_LEN = 120 # gespeicherte Payload-Laenge fuer Anzeigen/Schalter


def time_ok():
    # Uhr gestellt (NTP oder Browser)?  1735689600 = 01.01.2025
    return time.time() > 1735689600


_pool = []


def init_pool():
    blk = _NAN4 * SLOTS
    for _ in range(MAX_HIST * 2):
        _pool.append(array("f", blk))


def _take():
    if _pool:
        return _pool.pop()
    return array("f", _NAN4 * SLOTS)


class Tier:
    __slots__ = ("res", "arr", "abs", "sum", "cnt")

    def __init__(self, res):
        self.res = res
        self.arr = _take()
        self._clear()
        self.abs = -1
        self.sum = 0.0
        self.cnt = 0

    def _clear(self):
        a = self.arr
        for i in range(SLOTS):
            a[i] = NAN

    def add(self, t, v):
        s = t // self.res
        if s != self.abs:
            if self.abs < 0 or s < self.abs or s - self.abs >= SLOTS:
                self._clear()
            else:
                a = self.arr
                k = self.abs + 1
                while k < s:
                    a[k % SLOTS] = NAN
                    k += 1
            self.abs = s
            self.sum = 0.0
            self.cnt = 0
        self.sum += v
        self.cnt += 1
        self.arr[s % SLOTS] = self.sum / self.cnt

    def export(self, parts):
        # haengt '{"t0":ms,"step":ms,"v":[...]}' an parts an
        if self.abs < 0:
            parts.append('null')
            return
        first = self.abs - SLOTS + 1
        parts.append('{"t0":%d000,"step":%d000,"v":[' % (first * self.res, self.res))
        a = self.arr
        out = []
        sep = ""
        for k in range(first, self.abs + 1):
            x = a[k % SLOTS]
            out.append(sep + ("null" if x != x else fmt(x)))
            sep = ","
            if len(out) >= 48:
                # in kleinen Stuecken zusammenfassen (spart RAM auf dem RP2350)
                parts.append("".join(out))
                out = []
        parts.append("".join(out))
        parts.append("]}")


def fmt(x):
    if x == int(x) and -1e9 < x < 1e9:
        return str(int(x))
    s = "%.4f" % x
    s = s.rstrip("0")
    if s.endswith("."):
        s = s[:-1]
    return s


class Hist:
    __slots__ = ("fine", "coarse")

    def __init__(self):
        self.fine = Tier(FINE_RES)
        self.coarse = Tier(COARSE_RES)

    def release(self):
        _pool.append(self.fine.arr)
        _pool.append(self.coarse.arr)

    def add(self, t, v):
        self.fine.add(t, v)
        self.coarse.add(t, v)

    def json_parts(self, topic):
        # Liste kleiner Teilstrings (wird ohne grossen Gesamtstring gesendet)
        import json
        parts = ['{"topic":', json.dumps(topic), ',"fine":']
        self.fine.export(parts)
        parts.append(',"coarse":')
        self.coarse.export(parts)
        parts.append("}")
        return parts

    def to_json(self, topic):
        return "".join(self.json_parts(topic))


def _prealloc_dict(n):
    # Dict einmalig auf volle Groesse bringen: MicroPython verkleinert Dicts beim
    # Loeschen nicht -> spaeter keine grossen Umkopier-Allokationen mehr.
    d = {}
    for i in range(n):
        d[i] = None
    for i in range(n):
        del d[i]
    return d


try:
    from binascii import crc32 as _crc32
except ImportError:
    _crc32 = None


def tkey(b):
    """30-Bit-Schluessel eines Topics (bytes) - kleine Ganzzahl, kein Heap-Objekt."""
    if _crc32:
        return _crc32(b) & 0x3FFFFFFF
    h = 0
    for c in b:
        h = (h * 31 + c) & 0x1FFFFFF
    return h


NAME_ARENA = 24576   # Bytes fuer alle Topic-Namen


class TopicNames:
    """Alle gesehenen Topic-Namen in einem einzigen, beim Start reservierten
    Puffer. Vermeidet hunderte langlebige String-Objekte im Heap."""

    def __init__(self):
        self.arena = bytearray(NAME_ARENA)
        self.used = 0
        self.index = _prealloc_dict(MAX_STATES + 40)   # key -> None
        self.count = 0

    def add(self, key, b):
        if key in self.index:
            return
        n = len(b)
        if self.count >= MAX_STATES or self.used + n + 1 > NAME_ARENA or b"\n" in b:
            return
        self.arena[self.used:self.used + n] = b
        self.arena[self.used + n] = 10
        self.used += n + 1
        self.index[key] = None
        self.count += 1

    def names(self):
        out = []
        mv = memoryview(self.arena)
        start = 0
        while start < self.used:
            end = self.arena.find(b"\n", start, self.used)
            out.append(str(mv[start:end], "utf-8"))
            start = end + 1
        return out

    def remove(self, b):
        key = tkey(b)
        if key not in self.index:
            return
        keep = [x for x in self.names() if x.encode() != b]
        self.used = 0
        self.count = 0
        for k in list(self.index.keys()):
            del self.index[k]
        for x in keep:
            xb = x.encode()
            self.add(tkey(xb), xb)


class Store:
    def __init__(self):
        self.names = TopicNames()
        self.states = {}       # nur beobachtete Topics: topic -> [value_str, source]
        self.hist = {}         # topic -> Hist
        self.watched = set()
        self.last_emit = _prealloc_dict(MAX_STATES + 40)  # key -> ticks_ms

    def ensure_hist(self, topic):
        if topic in self.hist:
            return True
        if len(self.hist) >= MAX_HIST:
            return False
        self.hist[topic] = Hist()
        return True

    def drop_unused_hist(self, used):
        for t in list(self.hist.keys()):
            if t not in used:
                self.hist.pop(t).release()

    def add_name(self, topic):
        b = topic.encode()
        self.names.add(tkey(b), b)

    def set_state(self, topic, value, source):
        if len(value) > MAX_VALUE_LEN:
            value = value[:MAX_VALUE_LEN]
        cur = self.states.get(topic)
        if cur is None:
            self.states[topic] = [value, source]
        else:
            cur[0] = value
            cur[1] = source

    def add_value(self, topic, v):
        h = self.hist.get(topic)
        if h is not None and time_ok():
            h.add(int(time.time()), v)
