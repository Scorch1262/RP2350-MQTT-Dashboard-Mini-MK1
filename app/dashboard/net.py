# Netzwerk (W5500), NTP, Status-LED fuer RP2350-MINI(ETH)

import json
import time

NET_PATH = "/net.json"

DEFAULT_NET = {
    "dhcp": True,
    "ip": "192.168.1.200",
    "mask": "255.255.255.0",
    "gw": "192.168.1.1",
    "dns": "192.168.1.1",
    "hostname": "mqtt-dashboard",
    "ntp": "pool.ntp.org",
    "port": 5001,
}


def load_net():
    cfg = dict(DEFAULT_NET)
    try:
        with open(NET_PATH) as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_net(cfg):
    with open(NET_PATH, "w") as f:
        json.dump(cfg, f)


# ── Status-LED (WS2812 an GP25) ─────────────────────────────────────────────
class Led:
    def __init__(self):
        self.np = None
        try:
            import machine
            import neopixel
            self.np = neopixel.NeoPixel(machine.Pin(25), 1)
        except Exception:
            pass

    def set(self, r, g, b):
        if self.np:
            try:
                self.np[0] = (r, g, b)
                self.np.write()
            except Exception:
                pass


led = Led()
nic = None


def start(cfg):
    """Startet die Ethernet-Schnittstelle. Gibt IP (str) oder None zurueck."""
    global nic
    try:
        import network
    except ImportError:
        print("[Net] kein network-Modul (Host-Test)")
        return "127.0.0.1"
    try:
        network.hostname(cfg.get("hostname") or "mqtt-dashboard")
    except Exception:
        pass
    led.set(20, 0, 0)
    nic = network.WIZNET5K()
    nic.active(True)
    print("[Net] Warte auf Ethernet-Link ...")
    t0 = time.ticks_ms()
    while not _link(nic) and time.ticks_diff(time.ticks_ms(), t0) < 15000:
        time.sleep_ms(200)
    if cfg.get("dhcp", True):
        print("[Net] DHCP ...")
        ok = False
        for _ in range(3):
            try:
                nic.ifconfig("dhcp")
                ok = True
                break
            except Exception as e:
                print("[Net] DHCP:", e)
        if not ok:
            print("[Net] DHCP fehlgeschlagen - nutze statische IP", cfg["ip"])
            _static(nic, cfg)
    else:
        _static(nic, cfg)
    ip = nic.ifconfig()[0]
    print("[Net] IP-Adresse:", ip, " Maske:", nic.ifconfig()[1], " GW:", nic.ifconfig()[2])
    led.set(20, 12, 0)
    return ip


def _link(n):
    try:
        return n.status() != 0 or n.isconnected()
    except Exception:
        return True


def _static(n, cfg):
    n.ifconfig((cfg["ip"], cfg["mask"], cfg["gw"], cfg["dns"]))


def ifconfig():
    if nic:
        try:
            return nic.ifconfig()
        except Exception:
            pass
    return ("0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0")


def ntp_sync(host):
    try:
        import ntptime
        ntptime.host = host or "pool.ntp.org"
        ntptime.timeout = 2
        ntptime.settime()
        print("[NTP] Zeit gesetzt:", time.gmtime())
        return True
    except Exception as e:
        print("[NTP] Fehler:", e)
        return False


def set_time_ms(ms):
    """Setzt die RTC (UTC) aus Unix-Millisekunden (Browserzeit)."""
    try:
        import machine
        t = time.gmtime(ms // 1000)
        machine.RTC().datetime((t[0], t[1], t[2], t[6], t[3], t[4], t[5], 0))
        print("[Zeit] vom Browser uebernommen:", t)
        return True
    except Exception as e:
        print("[Zeit] Fehler:", e)
        return False


def reboot(delay_ms=1000):
    try:
        import machine
        time.sleep_ms(delay_ms)
        machine.reset()
    except ImportError:
        print("[Net] Neustart (Host-Test: ignoriert)")
