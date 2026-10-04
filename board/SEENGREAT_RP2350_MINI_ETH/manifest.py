include("$(PORT_DIR)/boards/manifest.py")
require("bundle-networking")
# MQTT-Dashboard (wird mit in die Firmware eingebrannt)
freeze("$(BOARD_DIR)/../../app")
