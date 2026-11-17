"""Faults stay latched; reset only works when the latest reading is normal."""
import pytest

from conftest import FAULT, NORMAL


def make_fault(rig):
    for _ in range(3):
        rig.send_reading(2999, 25)
    assert rig.status.state == FAULT


@pytest.mark.req("REQ-08")
def test_fault_stays_latched_after_good_readings(rig):
    make_fault(rig)
    for _ in range(10):
        s = rig.send_reading(3700, 25)
    assert s.state == FAULT
    assert not s.contactor_closed


@pytest.mark.req("REQ-08", "REQ-09")
def test_reset_accepted_when_normal(rig):
    make_fault(rig)
    rig.send_reading(3700, 25)
    s = rig.send_reset()
    assert s.state == NORMAL
    assert s.contactor_closed
    assert s.faults == 0


@pytest.mark.req("REQ-09")
@pytest.mark.parametrize("mv, temp_c", [
    (2999, 25),    # still under-voltage
    (3700, 55),    # warning is not normal
    (3700, 50),    # warning boundary
])
def test_reset_ignored_when_not_normal(rig, mv, temp_c):
    make_fault(rig)
    rig.send_reading(mv, temp_c)
    s = rig.send_reset()
    assert s.state == FAULT
    assert not s.contactor_closed


@pytest.mark.req("REQ-09")
def test_reset_with_no_fault_changes_nothing(rig):
    rig.send_reading(3700, 25)
    s = rig.send_reset()
    assert s.state == NORMAL and s.contactor_closed


@pytest.mark.req("REQ-09")
def test_wrong_reset_code_is_ignored(rig):
    make_fault(rig)
    rig.send_reading(3700, 25)
    rig.clock.advance(10)
    rig.send_raw(0x101, bytes([0x5A]))      # not 0xA5
    assert rig.advance(0).state == FAULT
