"""Cybersecurity-style checks: corrupted and replayed frames."""
import pytest

from bench import can_protocol as cp
from conftest import FAULT, NORMAL

BAD_FRAME_BIT = 0x10


# ---- REQ-11: wrong checksum ----------------------------------------------
@pytest.mark.req("REQ-11")
def test_bad_checksum_frame_is_dropped(rig):
    rig.send_reading(3700, 55)                   # WARNING
    s = rig.send_reading(3700, 25, corrupt=True) # would be NORMAL if accepted
    assert s.state != NORMAL


@pytest.mark.req("REQ-11")
def test_three_bad_checksums_fault(rig):
    for _ in range(3):
        s = rig.send_reading(3700, 25, corrupt=True)
    assert s.state == FAULT
    assert s.faults == BAD_FRAME_BIT


@pytest.mark.req("REQ-11", "REQ-06")
def test_bad_checksum_counts_with_bad_readings(rig):
    rig.send_reading(2999, 25)
    rig.send_reading(2999, 25)
    s = rig.send_reading(3700, 25, corrupt=True)
    assert s.state == FAULT
    assert s.faults == 0x02 | BAD_FRAME_BIT


@pytest.mark.req("REQ-11")
def test_short_frame_counts_as_bad(rig):
    for _ in range(3):
        rig.clock.advance(10)
        rig.send_raw(cp.SENSOR_ID, bytes([0x0E, 0x74, 0x19]))
        s = rig.advance(0)
    assert s.state == FAULT


@pytest.mark.req("REQ-11")
def test_checksum_is_xor_of_first_seven_bytes():
    data = cp.pack_sensor(3700, 25, 7)
    assert data[7] == data[0] ^ data[1] ^ data[2] ^ data[6]
    assert cp.unpack_sensor(data).checksum_ok
    assert not cp.unpack_sensor(cp.pack_sensor(3700, 25, 7, corrupt=True)).checksum_ok


# ---- REQ-12: repeated alive counter ----------------------------------------
@pytest.mark.req("REQ-12")
def test_replayed_frame_is_dropped(rig):
    rig.send_reading(3700, 25, counter=5)
    s = rig.send_reading(3700, 55, counter=5)    # same counter: replay
    assert s.state == NORMAL                     # the 55 °C was ignored


@pytest.mark.req("REQ-12")
def test_replay_does_not_count_as_bad(rig):
    rig.send_reading(2999, 25, counter=9)        # bad reading #1
    for _ in range(5):
        s = rig.send_reading(2999, 25, counter=9)  # replays: dropped
    assert s.state != FAULT


@pytest.mark.req("REQ-12")
def test_stuck_sender_cannot_hold_state(rig):
    """A stuck sender repeats one frame forever: the ECU must time out."""
    rig.send_reading(3700, 25, counter=1)
    for _ in range(5):
        s = rig.send_reading(3700, 25, counter=1, wait_ms=100)
    assert s.state == FAULT


@pytest.mark.req("REQ-12")
def test_counter_wraps_from_255_to_0(rig):
    """254 -> 255 -> 0 are all new values, so all three bad readings count."""
    for c in (254, 255, 0):
        s = rig.send_reading(2999, 25, counter=c)
    assert s.state == FAULT
