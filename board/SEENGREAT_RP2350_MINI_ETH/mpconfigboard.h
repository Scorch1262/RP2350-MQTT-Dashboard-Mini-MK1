// Board config: Seengreat RP2350-MINI(ETH)
#define MICROPY_HW_BOARD_NAME               "Seengreat RP2350-MINI(ETH)"

#define MICROPY_PY_NETWORK                  (1)
#define MICROPY_PY_NETWORK_HOSTNAME_DEFAULT "mqtt-dashboard"

// W5500 laut Schaltplan RP2350-Eth V1.1
#define MICROPY_HW_WIZNET_SPI_ID            (0)
#define MICROPY_HW_WIZNET_SPI_BAUDRATE      (20 * 1000 * 1000)
#define MICROPY_HW_WIZNET_SPI_SCK           (18)
#define MICROPY_HW_WIZNET_SPI_MOSI          (19)
#define MICROPY_HW_WIZNET_SPI_MISO          (16)
#define MICROPY_HW_WIZNET_PIN_CS            (17)
#define MICROPY_HW_WIZNET_PIN_RST           (20)
#define MICROPY_HW_WIZNET_PIN_INTN          (21)
