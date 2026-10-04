# MQTT Dashboard MK3 - Version fuer Seengreat RP2350-MINI(ETH)
# Portierung von mqtt_dashboard_v19.py (Flask/SocketIO) auf MicroPython:
#   Flask/SocketIO -> eigener HTTP- + WebSocket-Server (asyncio)
#   paho-mqtt      -> eigener asynchroner MQTT-Client
#   deque 20000    -> Ringpuffer mit 30 s / 4 min Slots (siehe store.py)

import asyncio
import gc
import json
import random
import time

from . import net
from .mqtt import MQTTClient
from .store import Store, time_ok, fmt, init_pool, tkey
from .web import WebServer

VERSION = "RP2350-1.0 (basiert auf V1.9)"
CONFIG_PATH = "/mqtt_dashboard_config.json"
EMIT_INTERVAL_MS = 1000
VT_VARS = "abcdef"
VT_ALLOWED = set("abcdef0123456789.+-*/()% ")

store = Store()
active_groups = {}
active_charts = {}    # cid -> {topic: color}
chart_names = {}
chart_formulas = {}
chart_groups = {}
active_widgets = {}
virtual_topics = {}
vt_by_source = {}     # topic -> [vid]
broker = {"ip": "", "port": 1883, "user": "", "password": ""}
netcfg = {}
ntp_ok = False
web = None
mqtt = None
_save_pending = False
_t_start = time.ticks_ms()


# ── Konfiguration ────────────────────────────────────────────────────────────
def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception as e:
        print("[Config] keine/ungueltige Konfiguration:", e)
    return {"broker": {"ip": ""}, "items": []}


def save_config():
    # verzoegert speichern (mehrere Aenderungen -> ein Flash-Schreibvorgang)
    global _save_pending
    _save_pending = True


def _write_config():
    items = []
    for g in active_groups.values():
        items.append(g)
    for v in virtual_topics.values():
        items.append(v)
    for cid, topics in active_charts.items():
        items.append({"id": cid, "type": "chart", "name": chart_names.get(cid, "Diagramm"),
                      "topics": topics, "formula": chart_formulas.get(cid, ""),
                      "group_id": chart_groups.get(cid, "default")})
    for w in active_widgets.values():
        items.append(w)
    cfg = {"broker": broker, "items": items}
    try:
        with open(CONFIG_PATH + ".tmp", "w") as f:
            json.dump(cfg, f)
        import os
        try:
            os.remove(CONFIG_PATH)
        except OSError:
            pass
        os.rename(CONFIG_PATH + ".tmp", CONFIG_PATH)
        print("[Config] gespeichert")
    except Exception as e:
        print("[Config] Speicherfehler:", e)


def config_json():
    try:
        with open(CONFIG_PATH) as f:
            return f.read()
    except Exception:
        return "{}"


def _parse_broker(s):
    s = (s or "").strip()
    host, port = s, 1883
    if s.count(":") == 1:
        host, p = s.split(":")
        try:
            port = int(p)
        except ValueError:
            port = 1883
    return host.strip(), port


def _rebuild_vt_index():
    vt_by_source.clear()
    for vid, vt in virtual_topics.items():
        for s in vt.get("sources", []):
            vt_by_source.setdefault(s, []).append(vid)
    _update_watched()


def _update_watched():
    w = set()
    for x in active_widgets.values():
        w.add(x.get("topic"))
    for vt in virtual_topics.values():
        w.add(vt["vname"])
        for s in vt.get("sources", []):
            w.add(s)
    store.watched = w
    for t in list(store.states.keys()):
        if t not in w:
            del store.states[t]


def _hist_topics():
    used = set()
    for topics in active_charts.values():
        for t in topics:
            used.add(t)
    for vt in virtual_topics.values():
        used.add(vt["vname"])
    return used


def _sync_hist():
    used = _hist_topics()
    store.drop_unused_hist(used)
    for t in used:
        if not store.ensure_hist(t):
            print("[Store] Historie-Limit erreicht, kein Verlauf fuer", t)


def restore():
    cfg = load_config()
    b = cfg.get("broker", {})
    broker["ip"] = b.get("ip", "")
    broker["port"] = int(b.get("port", 1883) or 1883)
    broker["user"] = b.get("user", "")
    broker["password"] = b.get("password", "")
    for w in cfg.get("items", cfg.get("widgets", [])):
        wid = w.get("id", "")
        wt = w.get("type")
        if not wid:
            continue
        if wt == "group":
            active_groups[wid] = w
        elif wt == "virtual":
            virtual_topics[wid] = w
            store.add_name(w["vname"])
        elif wt == "chart":
            active_charts[wid] = w.get("topics", {})
            chart_names[wid] = w.get("name", "Diagramm")
            chart_formulas[wid] = w.get("formula", "")
            chart_groups[wid] = w.get("group_id", "default")
        elif wt in ("button", "display", "slider"):
            active_widgets[wid] = w
    _rebuild_vt_index()
    _sync_hist()
    if broker["ip"]:
        print("[Config] Broker wiederhergestellt:", broker["ip"])


# ── Senden ───────────────────────────────────────────────────────────────────
def msg(e, d):
    return json.dumps({"e": e, "d": d})


def _parts(obj, out, depth):
    # JSON in kleinen Stuecken erzeugen (grosse Nachrichten ohne grossen Block)
    if depth and isinstance(obj, dict):
        out.append("{")
        sep = ""
        for k, v in obj.items():
            out.append(sep + json.dumps(k) + ":")
            _parts(v, out, depth - 1)
            sep = ","
        out.append("}")
    elif depth and isinstance(obj, list):
        out.append("[")
        sep = ""
        for v in obj:
            if sep:
                out.append(sep)
            _parts(v, out, depth - 1)
            sep = ","
        out.append("]")
    else:
        out.append(json.dumps(obj))


def msg_parts(e, d):
    out = ['{"e":', json.dumps(e), ',"d":']
    _parts(d, out, 3)
    out.append("}")
    return out


def emit(client, e, d):
    client.send(msg(e, d))


def emit_big(client, e, d):
    client.send(msg_parts(e, d))


def broadcast(e, d, droppable=False):
    if web and web.clients:
        web.broadcast(msg(e, d), droppable)


def send_hist(client, topic):
    if topic not in store.hist:
        return

    def data():
        h = store.hist.get(topic)
        if h is None:
            return None
        return ['{"e":"topic_hist","d":'] + h.json_parts(topic) + ["}"]
    if client is None:
        if web:
            web.broadcast(data)
    else:
        client.send(data)


def status_dict():
    ip = net.ifconfig()
    return {
        "mqtt": bool(mqtt and mqtt.connected),
        "broker": broker["ip"],
        "ip": ip[0],
        "time_ok": time_ok(),
        "ntp": ntp_ok,
        "mem": gc.mem_free(),
        "uptime": time.ticks_diff(time.ticks_ms(), _t_start) // 1000,
        "topics": store.names.count,
        "hist": len(store.hist),
        "version": VERSION,
    }


# ── MQTT ─────────────────────────────────────────────────────────────────────
def _emit_update(key, topic, value, numeric, source, now_ms):
    # max. 1 Update pro Topic und Sekunde an die Browser (wie PC-Version)
    now = time.ticks_ms()
    last = store.last_emit.get(key)
    if last is not None and time.ticks_diff(now, last) < EMIT_INTERVAL_MS:
        return
    if last is None and len(store.last_emit) >= 440 \
            and topic not in store.watched and topic not in store.hist:
        return
    store.last_emit[key] = now
    broadcast("mqtt_update", {"topic": topic, "ts": now_ms, "value": value,
                              "numeric": numeric, "source": source}, True)


def on_mqtt_message(topic_b, payload):
    try:
        topic = topic_b.decode()
        s = payload.decode()
    except Exception:
        return
    key = tkey(topic_b)
    store.names.add(key, topic_b)
    now_ms = time.time() * 1000
    val = None
    try:
        v = float(s)
        if v == v and v not in (float("inf"), float("-inf")):
            val = v
            store.add_value(topic, v)
    except ValueError:
        pass
    src = "remote"
    if topic in store.watched:
        old = store.states.get(topic)
        if old and old[1] == "self_pending":
            src = "self"
        store.set_state(topic, s, src)
    _emit_update(key, topic, s, val, src, now_ms)
    if topic in vt_by_source:
        _recompute_virtual(vt_by_source[topic], now_ms)


def _recompute_virtual(vids, now_ms):
    for vid in vids:
        vt = virtual_topics.get(vid)
        if not vt:
            continue
        vals = {}
        ok = True
        for i, src in enumerate(vt["sources"][:6]):
            st = store.states.get(src)
            try:
                vals[VT_VARS[i]] = float(st[0])
            except Exception:
                ok = False
                break
        if not ok:
            continue
        f = vt.get("formula", "")
        if not f or not set(f) <= VT_ALLOWED:
            continue
        try:
            result = float(eval(f, {}, vals))
        except Exception:
            continue
        vname = vt["vname"]
        store.add_value(vname, result)
        vs = fmt(result)
        store.set_state(vname, vs, "virtual")
        _emit_update(tkey(vname.encode()), vname, vs, result, "virtual", now_ms)


def on_mqtt_state(connected):
    if connected:
        net.led.set(0, 20, 0)
    else:
        net.led.set(20, 12, 0)
    broadcast("status", status_dict())


# ── WebSocket-Ereignisse (entspricht den SocketIO-Events der PC-Version) ───────
def ev_set_broker(c, d):
    if broker["ip"] and not d.get("force"):
        return
    host, port = _parse_broker(d.get("broker", ""))
    if not host:
        return
    broker["ip"] = host
    broker["port"] = port
    if "user" in d:
        broker["user"] = d.get("user", "")
    if "password" in d:
        broker["password"] = d.get("password", "")
    mqtt.configure(host, port, broker["user"], broker["password"])
    save_config()
    broadcast("status", status_dict())


def ev_request_topics(c, d):
    names = store.names.names()
    names.sort()
    emit_big(c, "topic_list", names)


def ev_add_virtual_topic(c, d):
    f = d.get("formula", "")
    if not set(f) <= VT_ALLOWED:
        emit(c, "error", "Formel enthaelt ungueltige Zeichen (erlaubt: a-f, Zahlen, + - * / % ( ))")
        return
    d["type"] = "virtual"
    virtual_topics[d["id"]] = d
    store.add_name(d["vname"])
    _rebuild_vt_index()
    _sync_hist()
    broadcast("init_virtual_topic", d)
    save_config()


def ev_remove_virtual_topic(c, d):
    vt = virtual_topics.pop(d["vid"], None)
    if vt:
        store.states.pop(vt["vname"], None)
        store.names.remove(vt["vname"].encode())
    _rebuild_vt_index()
    _sync_hist()
    broadcast("remove_virtual_topic", {"vid": d["vid"]})
    save_config()


def ev_add_group(c, d):
    active_groups[d["id"]] = d
    broadcast("init_group", d)
    save_config()


def ev_remove_group(c, d):
    gid = d["group_id"]
    active_groups.pop(gid, None)
    # Elemente der Gruppe wandern in "default" (wie in der Oberflaeche)
    for cid, g in chart_groups.items():
        if g == gid:
            chart_groups[cid] = "default"
    for w in active_widgets.values():
        if w.get("group_id") == gid:
            w["group_id"] = "default"
    broadcast("remove_group", {"group_id": gid})
    save_config()


def _chart_out(cid):
    return {"chart_id": cid,
            "datasets": [{"topic": t, "color": col} for t, col in active_charts[cid].items()],
            "name": chart_names.get(cid, "Diagramm"),
            "formula": chart_formulas.get(cid, ""),
            "group_id": chart_groups.get(cid, "default")}


def ev_add_topics(c, d):
    cid = d["chart_id"]
    chart_names[cid] = d.get("name", "Multi-Topic Diagramm")
    chart_formulas[cid] = d.get("formula", "")
    chart_groups[cid] = d.get("group_id", "default")
    topics = active_charts.setdefault(cid, {})
    for t in d.get("topics", []):
        topics[t] = "hsl(%d,70%%,50%%)" % random.randint(0, 360)
    _sync_hist()
    broadcast("init_chart", _chart_out(cid))
    for t in topics:
        send_hist(None, t)
    save_config()


def ev_add_widget(c, d):
    active_widgets[d["id"]] = d
    _update_watched()
    broadcast("init_widget", d)
    st = store.states.get(d.get("topic"))
    if st and st[0]:
        broadcast("mqtt_update", {"topic": d["topic"], "ts": time.time() * 1000,
                                  "value": st[0], "numeric": None, "source": st[1]})
    save_config()


def ev_remove_chart(c, d):
    cid = d["chart_id"]
    active_charts.pop(cid, None)
    chart_names.pop(cid, None)
    chart_formulas.pop(cid, None)
    chart_groups.pop(cid, None)
    _sync_hist()
    broadcast("remove_chart", {"chart_id": cid})
    save_config()


def ev_remove_widget(c, d):
    wid = d["widget_id"]
    active_widgets.pop(wid, None)
    _update_watched()
    broadcast("remove_widget", {"widget_id": wid})
    save_config()


def ev_publish_mqtt(c, d):
    t = d.get("topic", "")
    p = str(d.get("payload", ""))
    if not t or not mqtt.connected:
        emit(c, "error", "MQTT-Broker nicht verbunden")
        return
    if t in store.watched:
        store.set_state(t, p, "self_pending")
    asyncio.create_task(mqtt.publish(t, p))


def ev_request_state(c, d):
    emit_big(c, "restore_state", {
        "broker_set": bool(broker["ip"]),
        "groups": list(active_groups.values()),
        "virtual_topics": list(virtual_topics.values()),
        "charts": [_chart_out(cid) for cid in active_charts],
        "widgets": list(active_widgets.values()),
        "topic_states": {t: {"value": v[0], "source": v[1]} for t, v in store.states.items()
                         if v is not None and t in _state_topics_needed()},
    })
    for t in list(store.hist.keys()):
        send_hist(c, t)
    emit(c, "status", status_dict())


def _state_topics_needed():
    need = set()
    for w in active_widgets.values():
        need.add(w.get("topic"))
    return need


def ev_set_time(c, d):
    global ntp_ok
    if ntp_ok:
        return
    try:
        ms = int(d)
    except Exception:
        return
    if abs(ms // 1000 - time.time()) > 10:
        net.set_time_ms(ms)
        broadcast("status", status_dict())


def ev_get_settings(c, d):
    s = dict(netcfg)
    s["broker"] = broker["ip"] + ("" if broker["port"] == 1883 else ":%d" % broker["port"])
    s["mqtt_user"] = broker["user"]
    s["mqtt_password_set"] = bool(broker["password"])
    s["status"] = status_dict()
    emit(c, "settings", s)


def ev_save_settings(c, d):
    # MQTT-Broker
    host, port = _parse_broker(d.get("broker", ""))
    user = d.get("mqtt_user", "")
    pw = d.get("mqtt_password")
    if pw is None:
        pw = broker["password"]
    if (host, port, user, pw) != (broker["ip"], broker["port"], broker["user"], broker["password"]):
        broker.update({"ip": host, "port": port, "user": user, "password": pw})
        mqtt.configure(host, port, user, pw)
        save_config()
    # Netzwerk
    new = dict(netcfg)
    for k in ("dhcp", "ip", "mask", "gw", "dns", "hostname", "ntp"):
        if k in d:
            new[k] = d[k]
    reboot = False
    if new != netcfg:
        net_changed = any(new.get(k) != netcfg.get(k) for k in ("dhcp", "ip", "mask", "gw", "dns", "hostname"))
        netcfg.update(new)
        net.save_net(netcfg)
        reboot = net_changed
    emit(c, "settings_saved", {"reboot": reboot})
    if reboot:
        asyncio.create_task(_reboot_later())


async def _reboot_later():
    global _save_pending
    await asyncio.sleep(1)
    if _save_pending:
        _write_config()
        _save_pending = False
    net.reboot(200)


def ev_reboot(c, d):
    asyncio.create_task(_reboot_later())


EVENTS = {
    "set_broker": ev_set_broker,
    "request_topics": ev_request_topics,
    "add_virtual_topic": ev_add_virtual_topic,
    "remove_virtual_topic": ev_remove_virtual_topic,
    "add_group": ev_add_group,
    "remove_group": ev_remove_group,
    "add_topics": ev_add_topics,
    "add_widget": ev_add_widget,
    "remove_chart": ev_remove_chart,
    "remove_widget": ev_remove_widget,
    "publish_mqtt": ev_publish_mqtt,
    "request_state": ev_request_state,
    "set_time": ev_set_time,
    "get_settings": ev_get_settings,
    "save_settings": ev_save_settings,
    "reboot": ev_reboot,
}


def on_ws_message(c, text):
    try:
        m = json.loads(text)
    except Exception:
        return
    fn = EVENTS.get(m.get("e"))
    if fn:
        fn(c, m.get("d") or {})


# ── HTTP-Routen ──────────────────────────────────────────────────────────────
def _route_index():
    from .assets import INDEX_GZ
    return ("200 OK", "text/html; charset=utf-8", INDEX_GZ,
            "Content-Encoding: gzip\r\nCache-Control: no-cache\r\n")


def _route_chartjs():
    from .assets import CHARTJS_GZ
    return ("200 OK", "application/javascript", CHARTJS_GZ,
            "Content-Encoding: gzip\r\nCache-Control: max-age=604800\r\n")


def _route_config():
    if _save_pending:
        _write_config_now()
    return ("200 OK", "application/json; charset=utf-8", config_json().encode(),
            "Content-Disposition: attachment; filename=mqtt_dashboard_config.json\r\n")


def _route_status():
    return ("200 OK", "application/json", json.dumps(status_dict()).encode(), "")


def _route_favicon():
    return ("204 No Content", "image/x-icon", b"", "")


def _write_config_now():
    global _save_pending
    _save_pending = False
    _write_config()


# ── Hintergrund-Aufgaben ─────────────────────────────────────────────────────
async def _housekeeping():
    global _save_pending, ntp_ok
    n = 0
    wdt = None
    try:
        import machine
        wdt = machine.WDT(timeout=8300)
    except Exception:
        pass
    while True:
        await asyncio.sleep(1)
        if wdt:
            wdt.feed()
        n += 1
        if _save_pending and n % 3 == 0:
            _save_pending = False
            _write_config()
        if n % 30 == 0:
            gc.collect()
        if n % 60 == 0:
            broadcast("status", status_dict(), True)
        # NTP: beim Start alle 60 s bis erfolgreich, danach alle 6 h
        if (not ntp_ok and n % 60 == 5) or (ntp_ok and n % 21600 == 0):
            if wdt:
                wdt.feed()
            if net.ntp_sync(netcfg.get("ntp")):
                ntp_ok = True
            if wdt:
                wdt.feed()


def _client_id():
    try:
        import machine
        import binascii
        return "rp2350-dash-" + binascii.hexlify(machine.unique_id()).decode()[-8:]
    except Exception:
        return "rp2350-dash-%06x" % random.getrandbits(24)


async def main():
    global web, mqtt, netcfg
    gc.collect()
    init_pool()   # Verlaufspuffer frueh und zusammenhaengend reservieren
    gc.collect()
    print("[Start] %s, freier RAM: %d Bytes" % (VERSION, gc.mem_free()))
    netcfg = net.load_net()
    ip = net.start(netcfg)
    port = int(netcfg.get("port", 5001) or 5001)
    restore()
    mqtt = MQTTClient(_client_id(), on_mqtt_message, on_mqtt_state)
    web = WebServer({
        "/": _route_index,
        "/index.html": _route_index,
        "/chart.js": _route_chartjs,
        "/config.json": _route_config,
        "/status": _route_status,
        "/favicon.ico": _route_favicon,
    }, on_ws_message, on_ws_open=lambda c: emit(c, "hello", VERSION))
    await web.start(port)
    print("[Start] Dashboard erreichbar unter http://%s:%d" % (ip, port))
    if broker["ip"]:
        mqtt.configure(broker["ip"], broker["port"], broker["user"], broker["password"])
    asyncio.create_task(mqtt.run())
    asyncio.create_task(_housekeeping())
    while True:
        await asyncio.sleep(3600)


def run():
    try:
        asyncio.run(main())
    finally:
        asyncio.new_event_loop()
