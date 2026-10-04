# MQTT-Dashboard-MK3 – Version für Seengreat RP2350-MINI(ETH)

Portierung von **MQTT-Dashboard-MK3 V1.9** (Python/Flask/SocketIO) auf das Board
**Seengreat RP2350-MINI(ETH)** (RP2350A + W5500-Ethernet). Das Dashboard läuft komplett
auf dem Board – kein PC mehr nötig. Oberfläche und Bedienung entsprechen der PC-Version.

## Installation (eine Datei)

1. **BOOT**-Taste gedrückt halten und das Board per USB-C anschließen (oder BOOT halten + RUN drücken).
2. Es erscheint ein Laufwerk **RP2350**.
3. `firmware/MQTT-Dashboard-RP2350-MINI-ETH.uf2` auf das Laufwerk ziehen – das Board startet neu.
4. Netzwerkkabel anstecken. Das Board holt sich per **DHCP** eine IP-Adresse.
5. Im Browser öffnen: `http://mqtt-dashboard.local:5001` oder `http://<IP-Adresse>:5001`
   (IP steht im Router oder in der seriellen Ausgabe, z. B. Thonny/`mpremote`).
6. Beim ersten Aufruf fragt das Dashboard nach der **Broker-IP** (optional mit Port: `192.168.1.10:1883`).

Die Firmware enthält MicroPython v1.29.0, den W5500-Treiber (lwIP), das Dashboard und Chart.js –
die Seite funktioniert also auch **ohne Internetzugang**.

## Status-LED (WS2812, GP25)

| Farbe | Bedeutung |
|---|---|
| Rot | Start / warte auf Netzwerk |
| Gelb | Netzwerk ok, MQTT-Broker nicht verbunden |
| Grün | MQTT-Broker verbunden |

## Funktionen (wie V1.9)

- Diagramme mit mehreren Topics, Zeitbereich 1/6/12/24/48 h, automatische Y-Achse, 24-h-Zeitformat
- Schaltflächen (Schalter/Slider) mit Gerätetyp, Payload AN/AUS, Farbwechsel, „eigen/extern“
- Anzeigen, Gruppen (einklappbar, Farbe), virtuelle Topics mit Formel (`a - b`, `(a + b) / 2` …)
- Gleiche Ansicht auf allen Geräten, Live-Aktualisierung, Konfiguration bleibt nach Neustart erhalten

**Neu auf dem Board:**
- ⚙ **Einstellungen**: Broker (inkl. Benutzer/Passwort), DHCP oder feste IP, Hostname, NTP-Server,
  Statusanzeige (IP, Laufzeit, freier RAM), Neustart, **Konfiguration herunterladen** (`/config.json`)
- Status-Punkt in der Kopfzeile (grün = MQTT verbunden), automatische Wiederverbindung
- Uhrzeit per NTP, ersatzweise vom Browser
- Watchdog: das Board startet bei einem Hänger selbst neu

## Unterschiede zur PC-Version (wegen 520 KB RAM)

| | PC (V1.9) | RP2350 |
|---|---|---|
| Verlauf | bis 20 000 Rohwerte/Topic | gemittelt: 30 s für die letzten 6 h, 4 min bis 48 h |
| Topics mit Verlauf | unbegrenzt | max. 24 (Diagramme + virtuelle Topics) |
| bekannte Topics | unbegrenzt | max. 400 (Topic-Auswahl) |
| Verlauf beim Hinzufügen eines Diagramms | sofort vorhanden | beginnt ab dem Hinzufügen |
| Verlauf nach Neustart | geht verloren | geht verloren (wie PC) |
| Formeln virtueller Topics | Python-Ausdruck | nur `a`–`f`, Zahlen, `+ - * / % ( )` |
| Payload | unbegrenzt | max. 2 KB je Nachricht |

Konfigurationsformat (`/mqtt_dashboard_config.json`) ist kompatibel zur PC-Version.

## Dateien auf dem Board

| Datei | Inhalt |
|---|---|
| `/mqtt_dashboard_config.json` | Broker, Gruppen, Diagramme, Schaltflächen, virtuelle Topics |
| `/net.json` | Netzwerk: `dhcp`, `ip`, `mask`, `gw`, `dns`, `hostname`, `ntp`, `port` |

Beispiel feste IP (`/net.json`, z. B. mit Thonny hochladen):
```json
{"dhcp": false, "ip": "192.168.1.200", "mask": "255.255.255.0", "gw": "192.168.1.1", "dns": "192.168.1.1"}
```

**Wartung:** Datei `/kein_dashboard` anlegen → Dashboard startet nicht, REPL ist frei.
Ein Ordner `/dashboard` auf dem Board überschreibt die eingebrannte Version (Updates ohne Neu-Flashen).
Mit Strg+C im seriellen Terminal lässt sich das laufende Dashboard ebenfalls stoppen.

## Pinbelegung (laut Schaltplan RP2350-Eth V1.1)

W5500 an SPI0: SCK GP18, MOSI GP19, MISO GP16, CS GP17, RST GP20, INT GP21 · WS2812: GP25

## Projektstruktur

```
app/main.py              Start (eingefroren in der Firmware)
app/dashboard/app.py     Logik (entspricht den SocketIO-Events der PC-Version)
app/dashboard/mqtt.py    asynchroner MQTT-3.1.1-Client
app/dashboard/web.py     HTTP- + WebSocket-Server
app/dashboard/store.py   Ringpuffer-Verlauf, Topic-Verwaltung
app/dashboard/net.py     W5500, DHCP/statisch, NTP, LED
app/dashboard/assets.py  erzeugt: index.html + Chart.js (gzip)
web/index.html           Weboberfläche (aus V1.9, Socket.IO → WebSocket)
board/…                  MicroPython-Boarddefinition RP2350-MINI(ETH)
tools/build_assets.py    erzeugt assets.py
tools/build_firmware.sh  baut die UF2 selbst
```

Selbst bauen: `./tools/build_firmware.sh` (benötigt `arm-none-eabi-gcc`, `cmake`, `git`, `python3`).

Chart.js 2.9.4 (MIT-Lizenz) ist in der Firmware enthalten, siehe `web/Chart.js-LICENSE.md`.
