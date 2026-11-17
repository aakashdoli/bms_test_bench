"""Each fault type, its fault bit, and the contactor opening."""
import pytest

from conftest import FAULT

OVER_TEMP, UNDER_VOLT, OVER_VOLT = 0x01, 0x02, 0x04

FAULT_CASES = [
    pytest.param(3700, 61, OVER_TEMP, marks=pytest.mark.req("REQ-03"), id="61C"),
    pytest.param(3700, 90, OVER_TEMP, marks=pytest.mark.req("REQ-03"), id="90C"),
    pytest.param(2999, 25, UNDER_VOLT, marks=pytest.mark.req("REQ-04"), id="2999mV"),
    pytest.param(2500, 25, UNDER_VOLT, marks=pytest.mark.req("REQ-04"), id="2500mV"),
    pytest.param(4201, 25, OVER_VOLT, marks=pytest.mark.req("REQ-05"), id="4201mV"),
    pytest.param(4500, 25, OVER_VOLT, marks=pytest.mark.req("REQ-05"), id="4500mV"),
]


@pytest.mark.req("REQ-07")
@pytest.mark.parametrize("mv, temp_c, bit", FAULT_CASES)
def test_fault_sets_bit_and_opens_contactor(rig, mv, temp_c, bit):
    for _ in range(3):
        s = rig.send_reading(mv, temp_c)
    assert s.state == FAULT
    assert s.faults == bit
    assert not s.contactor_closed          # opened in the same step


@pytest.mark.req("REQ-07")
def test_contactor_closed_until_fault_step(rig):
    """The contactor must stay closed on readings 1 and 2, and open on reading 3."""
    closed = [rig.send_reading(4300, 25).contactor_closed for _ in range(3)]
    assert closed == [True, True, False]


@pytest.mark.req("REQ-03", "REQ-05")
def test_two_causes_are_both_reported(rig):
    for _ in range(3):
        s = rig.send_reading(4300, 70)
    assert s.faults == OVER_TEMP | OVER_VOLT
