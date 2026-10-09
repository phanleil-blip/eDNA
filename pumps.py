import atexit

import board
import busio
from adafruit_mcp230xx.mcp23017 import MCP23017

ADDRESSES = {"sub": 0x20, "pres": 0x21}
ACTIVE_LOW = True
IDLE = 0xFFFF if ACTIVE_LOW else 0x0000

UNITS = [f"{n}{s}" for n in range(1, 9) for s in "AB"]

i2c = busio.I2C(board.SCL, board.SDA)
boards = {kind: MCP23017(i2c, address=addr) for kind, addr in ADDRESSES.items()}


def _pin(i):
    # 5A-8B are wired to PB7..PB0, but the driver numbers PB0..PB7 as pins 8-15
    return i if i < 8 else 23 - i


PINS = {
    (kind, unit): chip.get_pin(_pin(i))
    for kind, chip in boards.items()
    for i, unit in enumerate(UNITS)
}


def all_off():
    for chip in boards.values():
        chip.gpio = IDLE


def set_pump(kind, unit, on):
    PINS[kind, unit].value = on != ACTIVE_LOW


# Latch the idle level before switching to outputs so relays don't pulse at startup
all_off()
for chip in boards.values():
    chip.iodir = 0x0000
atexit.register(all_off)
