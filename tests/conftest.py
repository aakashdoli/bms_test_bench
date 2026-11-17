"""Shared test setup: the CAN rig fixture, the req marker, results, and a summary."""
import itertools
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import can
import pytest

from bench import can_protocol as cp
from bench.bms_lib import Bms
from bench.clock import FakeClock
from bench.ecu_node import EcuNode

NORMAL, WARNING, FAULT = 0, 1, 2
REQ_PATTERN = re.compile(r"^REQ-\d{2}$")
_channels = itertools.count()


class Rig:
    """The test side of the bench. It only talks to the ECU through CAN."""

    def __init__(self, ecu: EcuNode, tester: can.BusABC, clock: FakeClock):
        self.ecu, self.tester, self.clock = ecu, tester, clock
        self.counter = 0
        self.status: cp.StatusFrame | None = None

    def send_reading(self, mv, temp_c, *, counter=None, corrupt=False, wait_ms=10):
        """Send one sensor frame `wait_ms` after the last step, return the status."""
        if counter is None:
            self.counter = (self.counter + 1) & 0xFF
            counter = self.counter
        self.clock.advance(wait_ms)
        self.send_raw(cp.SENSOR_ID, cp.pack_sensor(mv, temp_c, counter, corrupt))
        return self._cycle()

    def send_reset(self, wait_ms=10):
        self.clock.advance(wait_ms)
        self.send_raw(cp.RESET_ID, cp.pack_reset())
        return self._cycle()

    def advance(self, ms):
        """Let time pass with no frames sent, then read the status."""
        self.clock.advance(ms)
        return self._cycle()

    def send_raw(self, frame_id, data):
        self.tester.send(can.Message(arbitration_id=frame_id, data=data,
                                     is_extended_id=False))

    def _cycle(self):
        """Run one ECU cycle and keep the newest 0x200 status frame."""
        self.ecu.poll()
        while (msg := self.tester.recv(timeout=0)) is not None:
            if msg.arbitration_id == cp.STATUS_ID:
                self.status = cp.unpack_status(bytes(msg.data))
        return self.status


# ---- fixtures ---------------------------------------------------------------
@pytest.fixture(scope="session")
def bms_lib():
    return Bms()          # load the C library once


@pytest.fixture
def rig(bms_lib):
    """A fresh bus, clock and ECU for every test, so tests never affect each other."""
    channel = f"bms-test-{next(_channels)}"
    ecu_bus = can.Bus(interface="virtual", channel=channel)
    tester = can.Bus(interface="virtual", channel=channel)
    clock = FakeClock()
    r = Rig(EcuNode(ecu_bus, clock, bms_lib), tester, clock)
    yield r
    ecu_bus.shutdown()
    tester.shutdown()


# ---- req marker -------------------------------------------------------------
def pytest_configure(config):
    config.addinivalue_line("markers", "req(*ids): requirement IDs this test verifies")


def req_ids(item) -> list[str]:
    return [i for m in item.iter_markers("req") for i in m.args]


def pytest_collection_modifyitems(config, items):
    """Stop the run if any test has no requirement, or a badly written one."""
    problems = []
    for item in items:
        ids = req_ids(item)
        if not ids:
            problems.append(f"{item.nodeid}: missing @pytest.mark.req")
        problems += [f"{item.nodeid}: bad ID {i!r}" for i in ids if not REQ_PATTERN.match(i)]
    if problems:
        raise pytest.UsageError("Traceability check failed:\n  " + "\n  ".join(problems))


# ---- results collection (feeds tools/trace_report.py) -----------------------
RESULTS_PATH = Path(__file__).resolve().parent.parent / "reports" / "results.json"
_results: dict[str, dict] = {}


def pytest_collection_finish(session):
    """Record every selected test with its requirement IDs before it runs."""
    for item in session.items:
        _results[item.nodeid] = {
            "nodeid": item.nodeid, "name": item.name, "file": item.path.name,
            "reqs": req_ids(item), "outcome": "not run", "duration_s": 0.0, "message": "",
        }


def pytest_runtest_logreport(report):
    """Called for setup, call and teardown of each test: keep the final outcome."""
    r = _results.get(report.nodeid)
    if r is None:
        return
    r["duration_s"] = round(r["duration_s"] + report.duration, 4)
    if report.failed:
        r["outcome"] = "failed" if report.when == "call" else "error"
        r["message"] = report.longreprtext[-2000:]      # keep the useful tail
    elif report.skipped:
        r["outcome"] = "skipped"
    elif report.when == "call":
        r["outcome"] = "passed"


def pytest_sessionfinish(session):
    if not _results or session.config.option.collectonly:
        return
    tests = list(_results.values())
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {"total": len(tests), **Counter(t["outcome"] for t in tests)},
        "tests": tests,
    }, indent=2))


# ---- short summary ----------------------------------------------------------
def pytest_terminal_summary(terminalreporter):
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    errors = len(terminalreporter.stats.get("error", []))
    terminalreporter.write_sep("=", "BMS bench summary")
    terminalreporter.write_line(
        f"Total: {passed + failed + errors}   Passed: {passed}   Failed: {failed + errors}")
