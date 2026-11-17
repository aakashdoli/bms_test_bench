"""Signal timeout: no valid sensor frame for 500 ms means FAULT."""
import pytest

from conftest import FAULT, NORMAL

TIMEOUT_BIT = 0x08


@pytest.mark.req("REQ-10")
@pytest.mark.parametrize("silence_ms, expected", [(499, NORMAL), (500, FAULT)])
def test_timeout_boundary(rig, silence_ms, expected):
    rig.send_reading(3700, 25)
    s = rig.advance(silence_ms)
    assert s.state == expected


@pytest.mark.req("REQ-10", "REQ-07")
def test_timeout_sets_bit_and_opens_contactor(rig):
    rig.send_reading(3700, 25)
    s = rig.advance(500)
    assert s.faults == TIMEOUT_BIT
    assert not s.contactor_closed


@pytest.mark.req("REQ-10")
def test_no_frame_at_all_after_power_on(rig):
    assert rig.advance(500).state == FAULT


@pytest.mark.req("REQ-10")
def test_steady_frames_never_time_out(rig):
    for _ in range(50):
        s = rig.send_reading(3700, 25, wait_ms=100)
    assert s.state == NORMAL


@pytest.mark.req("REQ-10", "REQ-09")
def test_reset_after_timeout_needs_fresh_frame(rig):
    rig.send_reading(3700, 25)
    rig.advance(500)
    assert rig.send_reset().state == FAULT           # no fresh reading yet
    rig.send_reading(3700, 25)
    assert rig.send_reset().state == NORMAL


@pytest.mark.req("REQ-10", "REQ-11", "REQ-12")
def test_dropped_frames_do_not_refresh_timer(rig):
    rig.send_reading(3700, 25, counter=1, wait_ms=0)
    rig.send_reading(3700, 25, counter=1, wait_ms=200)    # replay: dropped
    rig.send_reading(3700, 25, corrupt=True, wait_ms=200) # bad checksum: dropped
    s = rig.advance(100)                                  # 500 ms since last valid
    assert s.state == FAULT
    assert s.faults & TIMEOUT_BIT
