"""The normalized event envelope (spec section 11.2).

Every observable step of a trial (a stimulus, a model call, a tool request, an
authorization decision, a fault, a state mutation) becomes exactly one
`NormalizedEvent`. The event stream is canonical evidence: acceptance criterion
13 requires "contiguous events" for every completed trial, and `assert_contiguous_sequence`
is the check that enforces it before a trial is allowed to commit.

Event payloads may legitimately contain floats (model parameters, cost), unlike
domain state, so hashing here goes through the artifact canonicalizer rather
than the domain one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from maf_lab.domain.clock import UtcDatetime
from maf_lab.schemas.canonical import artifact_sha256_hex

EventId = Annotated[str, StringConstraints(min_length=1, max_length=64)]
TrialId = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class EventType(StrEnum):
    """The event types named in spec section 11.2.

    This is the initial set the spec names, not a closed set: unknown types
    remain parseable (payload is `Mapping[str, Any]`, and nothing here rejects
    an unrecognized `type` string at the envelope level) but cannot silently
    satisfy an assertion, because evaluators match against these named values.
    """

    TRIAL_STARTED = "trial.started"
    MESSAGE_INPUT = "message.input"
    MESSAGE_OUTPUT = "message.output"
    MODEL_REQUEST = "model.request"
    MODEL_RESULT = "model.result"
    TOOL_REQUEST = "tool.request"
    AUTHORIZATION_DECISION = "authorization.decision"
    FAULT_INJECTED = "fault.injected"
    TOOL_RESULT = "tool.result"
    STATE_MUTATION = "state.mutation"
    CHECKPOINT_SAVED = "checkpoint.saved"
    LIMIT_REACHED = "limit.reached"
    TRIAL_ERROR = "trial.error"
    TRIAL_ENDED = "trial.ended"


class NormalizedEvent(BaseModel):
    """One ordered, timestamped, typed record of trial activity.

    Frozen and closed to unknown fields: the event stream is the canonical
    evidence acceptance criterion 13 checks, so its shape is fixed once written.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    event_id: EventId
    trial_id: TrialId
    sequence: int = Field(ge=1)
    timestamp: UtcDatetime
    type: EventType
    turn_id: str | None = None
    tool_call_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    payload: Mapping[str, Any] = Field(default_factory=dict)

    def canonical_sha256(self) -> str:
        """The digest of this event's canonical form, used for evidence refs."""
        return artifact_sha256_hex(self.model_dump(mode="json"))


class EventSequenceError(ValueError):
    """Raised when an event stream is not contiguous from 1.

    Reaching this means a trial's evidence is incomplete or corrupt: acceptance
    criterion 13 requires contiguous events for every completed trial, so a gap
    here must block the commit rather than be silently reported as a shorter
    stream.
    """


def assert_contiguous_sequence(events: Sequence[NormalizedEvent]) -> None:
    """Raise `EventSequenceError` unless `events` form 1, 2, 3, ... with no gaps.

    Checks in sequence-number order regardless of the order `events` arrives in,
    since a writer may append out of arrival order under concurrency (not the
    case for the single-threaded B0 path today, but the check should not assume
    it always will be).
    """
    ordered = sorted(events, key=lambda event: event.sequence)
    for expected, event in enumerate(ordered, start=1):
        if event.sequence != expected:
            if expected == 1:
                raise EventSequenceError(
                    f"event sequence must start at 1, got {event.sequence}"
                )
            raise EventSequenceError(
                f"gap or duplicate in event sequence: expected {expected}, got {event.sequence}"
            )
