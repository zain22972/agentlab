"""Time for the simulated domain.

Every timestamp the domain reads comes from an injected clock. The system clock
is deliberately unreachable from `maf_lab.domain`: an eligibility window that
depended on wall-clock time would make the same scenario pass today and fail
next month, which would destroy the repeatability the lab reports on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Protocol, runtime_checkable

from pydantic import AfterValidator, AwareDatetime


@runtime_checkable
class Clock(Protocol):
    """Reads the current instant of a trial."""

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC datetime."""
        ...


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError(f"clock instants must be timezone-aware, got {moment!r}")
    return moment.astimezone(UTC)


UtcDatetime = Annotated[datetime, AwareDatetime, AfterValidator(_as_utc)]
"""A timezone-aware instant, normalized to UTC so that canonical forms compare."""


class FakeClock:
    """A clock that only moves when a caller advances it.

    This is the only clock implementation in the project. There is no system
    clock to inject by accident.
    """

    def __init__(self, start: datetime) -> None:
        self._now = _as_utc(start)

    def now(self) -> datetime:
        """Return the current instant without moving it."""
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        """Move the clock forward by `delta` and return the new instant."""
        if delta < timedelta(0):
            raise ValueError(f"clock is monotonic, cannot advance by {delta}")
        self._now = self._now + delta
        return self._now
