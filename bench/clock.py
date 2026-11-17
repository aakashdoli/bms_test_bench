"""Fake clock: time only moves when a test says so. No sleeps, no flaky timing."""


class FakeClock:
    def __init__(self, start_ms: int = 0):
        self._now_ms = start_ms

    def now(self) -> int:
        """Current time in milliseconds (wraps like a 32-bit MCU timer)."""
        return self._now_ms & 0xFFFFFFFF

    def advance(self, ms: int) -> None:
        """Move time forward by `ms` milliseconds."""
        if ms < 0:
            raise ValueError("time cannot go backwards")
        self._now_ms += ms
