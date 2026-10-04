#!/usr/bin/env python3
"""Packt web/index.html und Chart.js (gzip) in app/dashboard/assets.py.

Die Dateien liegen danach als bytes-Konstanten in der Firmware (Flash),
belegen also keinen RAM und das Dashboard funktioniert ohne Internet.

Aufruf:  python3 tools/build_assets.py [Pfad/zu/Chart.bundle.min.js]
"""
import gzip
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "web", "index.html")
CHART = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "web", "Chart.bundle.min.js")
OUT = os.path.join(ROOT, "app", "dashboard", "assets.py")


def gz(path):
    with open(path, "rb") as f:
        raw = f.read()
    return raw, gzip.compress(raw, compresslevel=9, mtime=0)


def main():
    html_raw, html_gz = gz(HTML)
    chart_raw, chart_gz = gz(CHART)
    with open(OUT, "w") as f:
        f.write("# Automatisch erzeugt von tools/build_assets.py - nicht von Hand bearbeiten\n")
        f.write("INDEX_GZ = %r\n" % html_gz)
        f.write("CHARTJS_GZ = %r\n" % chart_gz)
    print("index.html : %6d -> %6d Bytes (gzip)" % (len(html_raw), len(html_gz)))
    print("chart.js   : %6d -> %6d Bytes (gzip)" % (len(chart_raw), len(chart_gz)))
    print("geschrieben:", OUT)


if __name__ == "__main__":
    main()
