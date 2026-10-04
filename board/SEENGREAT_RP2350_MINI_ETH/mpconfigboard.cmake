# Seengreat RP2350-MINI(ETH): RP2350A + W5500 (SPI0), 4 MB Flash
set(PICO_BOARD "pico2")

set(MICROPY_PY_NETWORK_WIZNET5K W5500)
set(MICROPY_PY_LWIP 1)
set(MICROPY_FROZEN_MANIFEST ${MICROPY_BOARD_DIR}/manifest.py)

# 4 MB Flash: ~1.5 MB Firmware (inkl. Dashboard), Rest Dateisystem
if(NOT DEFINED MICROPY_HW_FLASH_STORAGE_BYTES)
    set(MICROPY_HW_FLASH_STORAGE_BYTES 2097152)
endif()

# Mehr gleichzeitige TCP-Verbindungen (MQTT + mehrere Browser/WebSockets)
list(APPEND MICROPY_DEF_BOARD
    MEMP_NUM_TCP_PCB=16
)
