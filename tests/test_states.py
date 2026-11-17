"""NORMAL and WARNING states, including exact boundaries."""
import pytest

from conftest import NORMAL, WARNING


@pytest.mark.req("REQ-01")
def test_power_on_is_normal_with_contactor_closed(rig):
    s = rig.send_reading(3700, 25)
    assert s.state == NORMAL
    assert s.contactor_closed
    assert s.faults == 0


@pytest.mark.req("REQ-01", "REQ-02")
@pytest.mark.parametrize("mv, temp_c, expected", [
    (3700, 49, NORMAL),     # just below warning
    (3700, 50, WARNING),    # warning starts
    (3700, 60, WARNING),    # last warning value
    (3000, 25, NORMAL),     # lowest normal voltage
    (4200, 25, NORMAL),     # highest normal voltage
    (3700, -20, NORMAL),    # cold is not a fault
])
def test_state_boundaries(rig, mv, temp_c, expected):
    s = rig.send_reading(mv, temp_c)
    assert s.state == expected
    assert s.contactor_closed


@pytest.mark.req("REQ-02")
def test_warning_returns_to_normal_when_cooled(rig):
    assert rig.send_reading(3700, 55).state == WARNING
    assert rig.send_reading(3700, 30).state == NORMAL
