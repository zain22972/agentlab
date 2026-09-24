"""Unit tests for the injected fake clock."""

from datetime import UTC, datetime, timedelta

import pytest

from maf_lab.domain.clock import Clock, FakeClock


def test_fake_clock_satisfies_the_clock_protocol() -> None:
    clock: Clock = FakeClock(datetime(2026, 2, 1, 12, 0, tzinfo=UTC))
    assert clock.now() == datetime(2026, 2, 1, 12, 0, tzinfo=UTC)


def test_fake_clock_is_stable_until_advanced() -> None:
    clock = FakeClock(datetime(2026, 2, 1, 12, 0, tzinfo=UTC))
    assert clock.now() == clock.now()


def test_fake_clock_advances_by_an_explicit_delta() -> None:
    clock = FakeClock(datetime(2026, 2, 1, 12, 0, tzinfo=UTC))
    assert clock.advance(timedelta(minutes=5)) == datetime(2026, 2, 1, 12, 5, tzinfo=UTC)
    assert clock.now() == datetime(2026, 2, 1, 12, 5, tzinfo=UTC)


def test_fake_clock_never_moves_backwards() -> None:
    clock = FakeClock(datetime(2026, 2, 1, 12, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="monotonic"):
        clock.advance(timedelta(seconds=-1))


def test_fake_clock_requires_an_aware_start() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 2, 1, 12, 0))


def test_fake_clock_normalizes_to_utc() -> None:
    offset = datetime.fromisoformat("2026-02-01T14:00:00+02:00")
    clock = FakeClock(offset)
    assert clock.now() == datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    assert clock.now().tzinfo is UTC


def test_fake_clock_accepts_an_iso_instant_parsed_by_the_caller() -> None:
    clock = FakeClock(datetime.fromisoformat("2026-02-01T12:00:00+00:00"))
    assert clock.now() == datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
