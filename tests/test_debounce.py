"""Debounce: a fault needs 3 bad readings in a row."""
import pytest

from conftest import FAULT, NORMAL


@pytest.mark.req("REQ-06")
@pytest.mark.parametrize("mv, temp_c", [(3700, 61), (2999, 25), (4201, 25)])
def test_two_bad_readings_do_not_fault(rig, mv, temp_c):
    for _ in range(2):
        s = rig.send_reading(mv, temp_c)
    assert s.state != FAULT
    assert s.contactor_closed


@pytest.mark.req("REQ-06")
def test_third_bad_reading_faults(rig):
    states = [rig.send_reading(2999, 25).state for _ in range(3)]
    assert states == [NORMAL, NORMAL, FAULT]


@pytest.mark.req("REQ-06")
def test_good_reading_resets_count(rig):
    rig.send_reading(2999, 25)
    rig.send_reading(2999, 25)
    rig.send_reading(3700, 25)              # good: count back to 0
    rig.send_reading(2999, 25)
    s = rig.send_reading(2999, 25)
    assert s.state != FAULT                 # only 2 in a row


@pytest.mark.req("REQ-06")
def test_mixed_bad_causes_count_together(rig):
    rig.send_reading(3700, 61)
    rig.send_reading(2999, 25)
    s = rig.send_reading(4201, 25)
    assert s.state == FAULT
    assert s.faults == 0x07                 # all three causes recorded
