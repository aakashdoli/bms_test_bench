"""Controller node on the virtual CAN bus.

It plays the role of the real ECU: receive frames, check they are genuine,
feed the C controller, and reply with a status frame on 0x200.
"""
from collections import deque

import can

from bench import can_protocol as cp
from bench.bms_lib import Bms, STATE_NAMES, decode_faults
from bench.clock import FakeClock

CHANNEL = "bms-bench"


class EcuNode:
    def __init__(self, bus: can.BusABC, clock: FakeClock, bms: Bms | None = None):
        self.bus = bus
        self.clock = clock
        self.bms = bms or Bms()
        self.bms.init()
        self.last_counter: int | None = None   # for replay check (REQ-12)
        self.status_counter = 0
        self.log: deque[dict] = deque(maxlen=500)  # CAN log for the dashboard

    def poll(self) -> None:
        """One ECU cycle: check timeout, handle waiting frames, send status."""
        self.bms.tick(self.clock.now())           # REQ-10: catch a gap first
        while (msg := self.bus.recv(timeout=0)) is not None:
            self._handle(msg)
        self.bms.tick(self.clock.now())
        self._send_status()

    # ---- frame handling ------------------------------------------------
    def _handle(self, msg: can.Message) -> None:
        data = bytes(msg.data)
        if msg.arbitration_id == cp.SENSOR_ID:
            self._handle_sensor(data)
        elif msg.arbitration_id == cp.RESET_ID:
            if cp.is_reset(data):
                ok = self.bms.on_reset()
                self._log("RX", msg.arbitration_id, data,
                          "reset accepted" if ok else "reset ignored (REQ-09)")
            else:
                self._log("RX", msg.arbitration_id, data, "reset", "wrong reset code")

    def _handle_sensor(self, data: bytes) -> None:
        try:
            f = cp.unpack_sensor(data)
        except ValueError:
            self.bms.on_bad_frame()               # wrong length: treat as bad frame
            self._log("RX", cp.SENSOR_ID, data, "sensor", "wrong length")
            return
        meaning = f"{f.voltage_mv} mV, {f.temp_c} °C, cnt {f.counter}"
        if not f.checksum_ok:
            self.bms.on_bad_frame()               # REQ-11: drop + count as bad
            self._log("RX", cp.SENSOR_ID, data, meaning, "bad checksum")
            return
        if f.counter == self.last_counter:
            self._log("RX", cp.SENSOR_ID, data, meaning, "repeated counter")  # REQ-12
            return
        self.last_counter = f.counter
        self.bms.on_reading(f.voltage_mv, f.temp_c, self.clock.now())
        self._log("RX", cp.SENSOR_ID, data, meaning)

    def _send_status(self) -> None:
        data = cp.pack_status(self.bms.state(), self.bms.contactor_closed(),
                              self.bms.faults(), self.status_counter)
        self.bus.send(can.Message(arbitration_id=cp.STATUS_ID, data=data,
                                  is_extended_id=False))
        faults = ", ".join(decode_faults(self.bms.faults())) or "none"
        self._log("TX", cp.STATUS_ID, data,
                  f"{STATE_NAMES[self.bms.state()]}, contactor "
                  f"{'CLOSED' if self.bms.contactor_closed() else 'OPEN'}, faults: {faults}")
        self.status_counter = (self.status_counter + 1) & 0xFF

    def _log(self, direction, frame_id, data, meaning, dropped=None):
        self.log.append({
            "time_ms": self.clock.now(), "dir": direction, "id": f"0x{frame_id:03X}",
            "bytes": data.hex(" ").upper(), "meaning": meaning,
            "dropped": dropped or "",
        })


# ---- quick demo: python -m bench.ecu_node ---------------------------------
if __name__ == "__main__":
    clock = FakeClock()
    ecu_bus = can.Bus(interface="virtual", channel=CHANNEL)
    tester = can.Bus(interface="virtual", channel=CHANNEL)
    ecu = EcuNode(ecu_bus, clock)
    counter = 0

    def send(frame_id, data):
        tester.send(can.Message(arbitration_id=frame_id, data=data, is_extended_id=False))

    def step(label, mv=None, temp=None, corrupt=False, same_counter=False, reset=False, wait=100):
        global counter
        clock.advance(wait)
        if mv is not None:
            if not same_counter:
                counter = (counter + 1) & 0xFF
            send(cp.SENSOR_ID, cp.pack_sensor(mv, temp, counter, corrupt))
        if reset:
            send(cp.RESET_ID, cp.pack_reset())
        ecu.poll()
        s = cp.unpack_status(bytes(tester.recv(timeout=0).data))
        print(f"{clock.now():>5} ms  {label:<28} -> {STATE_NAMES[s.state]:<7} "
              f"contactor={'CLOSED' if s.contactor_closed else 'OPEN  '} "
              f"faults={decode_faults(s.faults)}")

    step("normal 3700 mV 25 C", 3700, 25)
    step("warm 55 C", 3700, 55)
    step("hot 65 C (1 of 3)", 3700, 65)
    step("hot 65 C (2 of 3)", 3700, 65)
    step("hot 65 C (3 of 3)", 3700, 65)
    step("reset while hot", 3700, 65, reset=True)
    step("cool 25 C", 3700, 25)
    step("reset when normal", reset=True)
    step("replayed counter", 3700, 25, same_counter=True)
    step("bad checksum", 3700, 25, corrupt=True)
    step("silence (600 ms)", wait=600)

    print("\nCAN log (last 6 entries):")
    for e in list(ecu.log)[-6:]:
        print(f"  {e['time_ms']:>5} {e['dir']} {e['id']} [{e['bytes']}] "
              f"{e['meaning']} {'DROPPED: ' + e['dropped'] if e['dropped'] else ''}")
    ecu_bus.shutdown()
    tester.shutdown()
