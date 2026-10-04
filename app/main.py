# Startet das MQTT-Dashboard.
# Wartungsmodus: Datei "/kein_dashboard" anlegen -> Dashboard startet nicht (REPL frei).
import os

try:
    os.stat("/kein_dashboard")
    print("[Start] /kein_dashboard gefunden - Dashboard nicht gestartet")
except OSError:
    from dashboard import app
    app.run()
