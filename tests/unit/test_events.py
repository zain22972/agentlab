"""Unit tests for the normalized event envelope (spec section 11.2)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from maf_lab.schemas.events import EventType, NormalizedEvent


def an_event(**overrides: object) -> NormalizedEvent:
    fields: dict[str, object] = {
        "event_id": "evt_0001",
        "trial_id": "trial_0001",
        "sequence": 1,
        "timestamp": datetime(2026, 2, 1, 12, 1, 1, 120000, tzinfo=UTC),
        "type": EventType.TRIAL_STARTED,
        "payload": {},
    }
    fields.update(overrides)
    return NormalizedEvent(**fields)  # type: ignore[arg-type]


def test_carries_the_documented_fields() -> None:
    event = an_event(
        type=EventType.TOOL_RESULT,
        payload={"tool_name": "create_refund", "outcome": "success"},
    )
    assert event.schema_version == "1.0"
    assert event.event_id == "evt_0001"
    assert event.trial_id == "trial_0001"
    assert event.sequence == 1
    assert event.type is EventType.TOOL_RESULT
    assert event.payload == {"tool_name": "create_refund", "outcome": "success"}


def test_turn_id_and_tool_call_id_and_trace_fields_are_optional() -> None:
    event = an_event()
    assert event.turn_id is None
    assert event.tool_call_id is None
    assert event.trace_id is None
    assert event.span_id is None


def test_carries_optional_turn_and_correlation_fields_when_present() -> None:
    event = an_event(
        turn_id="turn_2",
        tool_call_id="call_4",
        trace_id="a" * 32,
        span_id="b" * 16,
    )
    assert event.turn_id == "turn_2"
    assert event.tool_call_id == "call_4"
    assert event.trace_id == "a" * 32
    assert event.span_id == "b" * 16


def test_is_frozen() -> None:
    event = an_event()
    with pytest.raises(ValidationError):
        event.sequence = 2


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        an_event(unexpected="field")


def test_rejects_a_non_positive_sequence() -> None:
    with pytest.raises(ValidationError):
        an_event(sequence=0)


def test_timestamp_is_normalized_to_utc() -> None:
    event = an_event(timestamp=datetime.fromisoformat("2026-02-01T14:01:01.120+02:00"))
    assert event.timestamp == datetime(2026, 2, 1, 12, 1, 1, 120000, tzinfo=UTC)


def test_accepts_every_documented_event_type() -> None:
    """Every type named in spec section 11.2 must parse; unknown types are the
    ones that "remain parseable but cannot silently satisfy assertions"."""
    documented = [
        "trial.started",
        "message.input",
        "message.output",
        "model.request",
        "model.result",
        "tool.request",
        "authorization.decision",
        "fault.injected",
        "tool.result",
        "state.mutation",
        "checkpoint.saved",
        "limit.reached",
        "trial.error",
        "trial.ended",
    ]
    for type_value in documented:
        assert an_event(type=EventType(type_value)).type.value == type_value


def test_canonical_hash_ignores_key_order_in_the_payload() -> None:
    first = an_event(payload={"a": 1, "b": 2}).canonical_sha256()
    second = an_event(payload={"b": 2, "a": 1}).canonical_sha256()
    assert first == second


def test_canonical_hash_changes_when_the_payload_changes() -> None:
    first = an_event(payload={"a": 1}).canonical_sha256()
    second = an_event(payload={"a": 2}).canonical_sha256()
    assert first != second


def test_canonical_hash_tolerates_a_float_in_the_payload() -> None:
    """Unlike domain state, event payloads may legitimately carry floats
    (e.g. model.request parameters.temperature, tool.result duration_ms is an
    int, but usage/cost fields elsewhere are floats)."""
    digest = an_event(payload={"temperature": 0.2}).canonical_sha256()
    assert len(digest) == 64


class TestEventSequence:
    def test_a_contiguous_run_starting_at_one_is_valid(self) -> None:
        events = [an_event(sequence=i, event_id=f"evt_{i:04d}") for i in (1, 2, 3)]
        from maf_lab.schemas.events import assert_contiguous_sequence

        assert_contiguous_sequence(events)  # does not raise

    def test_empty_is_valid(self) -> None:
        from maf_lab.schemas.events import assert_contiguous_sequence

        assert_contiguous_sequence([])

    def test_a_gap_is_rejected(self) -> None:
        from maf_lab.schemas.events import EventSequenceError, assert_contiguous_sequence

        events = [an_event(sequence=1), an_event(sequence=3, event_id="evt_0003")]
        with pytest.raises(EventSequenceError, match="gap"):
            assert_contiguous_sequence(events)

    def test_starting_above_one_is_rejected(self) -> None:
        from maf_lab.schemas.events import EventSequenceError, assert_contiguous_sequence

        events = [an_event(sequence=2)]
        with pytest.raises(EventSequenceError, match="start"):
            assert_contiguous_sequence(events)

    def test_a_duplicate_sequence_number_is_rejected(self) -> None:
        from maf_lab.schemas.events import EventSequenceError, assert_contiguous_sequence

        events = [an_event(sequence=1), an_event(sequence=1, event_id="evt_0002")]
        with pytest.raises(EventSequenceError, match="duplicate|gap"):
            assert_contiguous_sequence(events)

    def test_out_of_order_input_is_still_checked_in_sequence_order(self) -> None:
        from maf_lab.schemas.events import assert_contiguous_sequence

        events = [an_event(sequence=2, event_id="evt_0002"), an_event(sequence=1)]
        assert_contiguous_sequence(events)  # does not raise: order is by .sequence
