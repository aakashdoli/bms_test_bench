"""Pack and unpack the bench's CAN frames. Pure functions, no bus needed.

0x100 sensor  (8 B): [0-1] voltage mV uint16 BE, [2] temp °C int8,
                     [3-5] zero, [6] alive counter, [7] XOR of bytes 0-6
0x101 reset   (1 B): [0] 0xA5
0x200 status  (4 B): [0] state, [1] contactor, [2] fault mask, [3] counter
"""
import struct
from dataclasses import dataclass

SENSOR_ID = 0x100
RESET_ID = 0x101
STATUS_ID = 0x200
RESET_MAGIC = 0xA5


def checksum(data: bytes) -> int:
    """XOR of all given bytes."""
    result = 0
    for b in data:
        result ^= b
    return result


@dataclass
class SensorFrame:
    voltage_mv: int
    temp_c: int
    counter: int
    checksum_ok: bool


@dataclass
class StatusFrame:
    state: int
    contactor_closed: bool
    faults: int
    counter: int


def pack_sensor(voltage_mv: int, temp_c: int, counter: int, corrupt: bool = False) -> bytes:
    """Build a sensor frame. corrupt=True flips the checksum (fault injection)."""
    body = struct.pack(">Hb3xB", voltage_mv, temp_c, counter & 0xFF)  # 7 bytes
    cs = checksum(body) ^ (0xFF if corrupt else 0x00)
    return body + bytes([cs])


def unpack_sensor(data: bytes) -> SensorFrame:
    """Read a sensor frame. Raises ValueError if it is not 8 bytes."""
    if len(data) != 8:
        raise ValueError(f"sensor frame must be 8 bytes, got {len(data)}")
    mv, temp, counter = struct.unpack(">Hb3xB", data[:7])
    return SensorFrame(mv, temp, counter, checksum(data[:7]) == data[7])


def pack_reset() -> bytes:
    return bytes([RESET_MAGIC])


def is_reset(data: bytes) -> bool:
    return len(data) >= 1 and data[0] == RESET_MAGIC


def pack_status(state: int, contactor_closed: bool, faults: int, counter: int) -> bytes:
    return bytes([state, int(contactor_closed), faults, counter & 0xFF])


def unpack_status(data: bytes) -> StatusFrame:
    if len(data) != 4:
        raise ValueError(f"status frame must be 4 bytes, got {len(data)}")
    return StatusFrame(data[0], bool(data[1]), data[2], data[3])
