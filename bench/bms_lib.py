"""ctypes wrapper around the C controller in build/libbms.(so|dylib)."""
import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB_NAME = "libbms.dylib" if sys.platform == "darwin" else "libbms.so"
LIB_PATH = ROOT / "build" / LIB_NAME

STATE_NAMES = {0: "NORMAL", 1: "WARNING", 2: "FAULT"}
FAULT_BITS = {
    0x01: "over-temperature",
    0x02: "under-voltage",
    0x04: "over-voltage",
    0x08: "signal timeout",
    0x10: "bad frames",
}


def decode_faults(mask: int) -> list[str]:
    """Turn a fault bitmask into words, e.g. 0x03 -> ['over-temperature', 'under-voltage']."""
    return [name for bit, name in FAULT_BITS.items() if mask & bit]


class Bms:
    """Thin Python face for the C functions.

    Note: the C code keeps ONE static state struct, so every Bms object in a
    process shares the same controller. That is how a real ECU behaves too.
    """

    def __init__(self, path: Path = LIB_PATH):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Run `make` first.")
        lib = ctypes.CDLL(str(path))

        # Tell ctypes the exact C types, so values are passed correctly.
        lib.bms_init.argtypes = []
        lib.bms_on_reading.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_uint32]
        lib.bms_on_bad_frame.argtypes = []
        lib.bms_on_reset.argtypes = []
        lib.bms_on_reset.restype = ctypes.c_bool
        lib.bms_tick.argtypes = [ctypes.c_uint32]
        lib.bms_get_state.restype = ctypes.c_int
        lib.bms_get_contactor_closed.restype = ctypes.c_bool
        lib.bms_get_faults.restype = ctypes.c_uint8
        lib.bms_get_debounce_count.restype = ctypes.c_uint8
        self._lib = lib

    def init(self) -> None:                  self._lib.bms_init()
    def on_reading(self, mv, temp_c, now_ms): self._lib.bms_on_reading(mv, temp_c, now_ms)
    def on_bad_frame(self) -> None:          self._lib.bms_on_bad_frame()
    def on_reset(self) -> bool:              return self._lib.bms_on_reset()
    def tick(self, now_ms: int) -> None:     self._lib.bms_tick(now_ms)
    def state(self) -> int:                  return self._lib.bms_get_state()
    def contactor_closed(self) -> bool:      return self._lib.bms_get_contactor_closed()
    def faults(self) -> int:                 return self._lib.bms_get_faults()
    def debounce_count(self) -> int:         return self._lib.bms_get_debounce_count()
