#!/usr/bin/env bash
# Baut firmware/MQTT-Dashboard-RP2350-MINI-ETH.uf2 (MicroPython + eingebranntes Dashboard)
#
# Voraussetzungen: git, cmake, make, python3, arm-none-eabi-gcc im PATH
# Aufruf aus dem Projektordner:  ./tools/build_firmware.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MPY_VERSION="v1.29.0"
MPY_DIR="${MPY_DIR:-$ROOT/build/micropython}"

if [ ! -d "$MPY_DIR" ]; then
    git clone --depth 1 -b "$MPY_VERSION" https://github.com/micropython/micropython "$MPY_DIR"
fi

python3 "$ROOT/tools/build_assets.py"
make -C "$MPY_DIR/mpy-cross" -j"$(nproc)"
make -C "$MPY_DIR/ports/rp2" BOARD_DIR="$ROOT/board/SEENGREAT_RP2350_MINI_ETH" BUILD=build-seengreat submodules
make -C "$MPY_DIR/ports/rp2" BOARD_DIR="$ROOT/board/SEENGREAT_RP2350_MINI_ETH" BUILD=build-seengreat -j"$(nproc)"

mkdir -p "$ROOT/firmware"
cp "$MPY_DIR/ports/rp2/build-seengreat/firmware.uf2" "$ROOT/firmware/MQTT-Dashboard-RP2350-MINI-ETH.uf2"
echo "Fertig: $ROOT/firmware/MQTT-Dashboard-RP2350-MINI-ETH.uf2"
