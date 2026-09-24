"""The trial orchestrator: one scenario, one trial, end to end (spec section 8).

`execute_trial` is the offline, single-trial slice of the section 8 sequence
diagram this ticket builds: create isolated state, run the B0 agent, record
ordered events, snapshot and diff canonical state, evaluate the scenario's
critical assertions, redact, and commit artifacts through `ArtifactWriter`.

What is deliberately absent: the fault injector (#10), the full evaluator
registry (#6), the manifest loader (#7), statistics (#8), and any lifecycle
state beyond the happy path (`QUEUED`/`PREPARING`/`RUNNING`/`EVALUATING`/
`COMMITTING`/`COMPLETED`; `FAILED`/`INTERRUPTED`/`RECOVERABLE` belong to
crash-recovery ticket #9's durable profile). This module runs the `memory`
store profile only.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

from maf_lab.domain.refunds.state import RefundState
from maf_lab.domain.refunds.tools import Success, ToolGateway
from maf_lab.evaluators.state_assertions import evaluate_state_assertion
from maf_lab.evidence.diff import StateDiff, diff_state
from maf_lab.evidence.redaction import RedactionConfig, redact, scan_for_leaks
from maf_lab.evidence.writer import ArtifactWriter, CompletedTrialError
from maf_lab.runner.b0 import B0Agent, UnsupportedToolError
from maf_lab.schemas.canonical import artifact_canonical_json, artifact_sha256_hex
from maf_lab.schemas.events import EventType, NormalizedEvent, assert_contiguous_sequence
from maf_lab.schemas.scenario import ScenarioManifest
from maf_lab.schemas.trial import EvaluationResult, TrialRecord


class TrialOutcome(NamedTuple):
    """What one `execute_trial` call produced, for the CLI and for tests.

    `trial_dir` is only meaningful when `exit_code == 0`; a refused or failed
    attempt still returns an outcome so a caller can inspect why, rather than
    an outcome existing only on success.
    """

    exit_code: int
    trial_dir: Path
    events: tuple[NormalizedEvent, ...]
    evaluations: tuple[EvaluationResult, ...]
    state_before_sha256: str
    state_after_sha256: str
    state_diff: StateDiff
    error: str | None = None


def execute_trial(
    *,
    manifest: ScenarioManifest,
    trial_id: str,
    artifacts_root: Path,
    redaction_config: RedactionConfig | None = None,
    canary_values: frozenset[str] = frozenset(),
) -> TrialOutcome:
    """Run `manifest` as one B0 trial and commit its evidence under `artifacts_root`.

    Returns a `TrialOutcome` with `exit_code == 0` only when the commit
    succeeds and every critical assertion passed. Every anticipated failure
    mode returns a non-zero `TrialOutcome` with `error` set rather than
    raising, so a single CLI invocation always exits under control (issue #3
    acceptance criterion 1):

    - `UnsupportedToolError`: the scenario requires a tool the gateway does
      not implement yet.
    - `RedactionLeakError`: the pattern scanner found a canary or secret that
      schema-aware redaction missed; nothing is written to disk.
    - `CompletedTrialError`: `trial_id` already has a committed directory.

    Any other exception is a harness defect and is allowed to propagate,
    since swallowing it would hide a bug this ticket has not anticipated.
    """
    config = redaction_config or RedactionConfig.default()
    if canary_values:
        config = config.model_copy(update={"canary_values": config.canary_values | canary_values})

    clock = RefundState.from_initial(manifest.initial_state).clock
    state = RefundState.from_initial(manifest.initial_state, clock=clock)
    gateway = ToolGateway(state)

    events: list[NormalizedEvent] = []
    sequence = _SequenceCounter()

    state_before_sha256 = state.state_sha256()
    snapshot_before = state.snapshot()

    events.append(
        _event(
            trial_id,
            sequence,
            clock,
            EventType.TRIAL_STARTED,
            {"scenario_id": manifest.scenario_id},
        )
    )

    try:
        outcomes = B0Agent(manifest).run(gateway)
    except UnsupportedToolError as error:
        return TrialOutcome(
            exit_code=1,
            trial_dir=artifacts_root / trial_id,
            events=tuple(events),
            evaluations=(),
            state_before_sha256=state_before_sha256,
            state_after_sha256=state_before_sha256,
            state_diff=diff_state(snapshot_before, snapshot_before),
            error=str(error),
        )

    for outcome in outcomes:
        events.append(
            _event(
                trial_id,
                sequence,
                clock,
                EventType.TOOL_REQUEST,
                {"tool_name": outcome.tool_name.value, "arguments": dict(outcome.arguments)},
            )
        )
        events.append(
            _event(
                trial_id,
                sequence,
                clock,
                EventType.TOOL_RESULT,
                {
                    "tool_name": outcome.tool_name.value,
                    "outcome": outcome.result.outcome.value,
                    "success": isinstance(outcome.result, Success),
                },
            )
        )

    state_after_sha256 = state.state_sha256()
    snapshot_after = state.snapshot()
    state_diff = diff_state(snapshot_before, snapshot_after)

    evaluations = tuple(
        evaluate_state_assertion(
            assertion,
            snapshot_after,
            clock=clock,
            trial_id=trial_id,
            scenario_id=manifest.scenario_id,
        )
        for assertion in manifest.oracle.critical_assertions()
    )

    events.append(
        _event(trial_id, sequence, clock, EventType.TRIAL_ENDED, {"status": "completed"})
    )
    assert_contiguous_sequence(events)

    trial_record = TrialRecord(
        trial_id=trial_id,
        scenario_id=manifest.scenario_id,
        trial_index=0,
        status="completed",
        started_at=events[0].timestamp,
        duration_ms=0,
        manifest_sha256=artifact_sha256_hex(manifest.model_dump(mode="json")),
        fixture_version=manifest.fixture_version,
        state_before_sha256=state_before_sha256,
        state_after_sha256=state_after_sha256,
        store_profile="memory",
    )

    try:
        artifacts = _build_artifacts(
            trial_record=trial_record,
            events=events,
            audit_log=state.audit_log,
            state_diff=state_diff,
            evaluations=evaluations,
            config=config,
        )
    except RedactionLeakError as error:
        return TrialOutcome(
            exit_code=1,
            trial_dir=artifacts_root / trial_id,
            events=tuple(events),
            evaluations=evaluations,
            state_before_sha256=state_before_sha256,
            state_after_sha256=state_after_sha256,
            state_diff=state_diff,
            error=str(error),
        )

    try:
        trial_dir = ArtifactWriter(root=artifacts_root).commit_trial(
            trial_id=trial_id, artifacts=artifacts
        )
    except CompletedTrialError as error:
        return TrialOutcome(
            exit_code=1,
            trial_dir=artifacts_root / trial_id,
            events=tuple(events),
            evaluations=evaluations,
            state_before_sha256=state_before_sha256,
            state_after_sha256=state_after_sha256,
            state_diff=state_diff,
            error=str(error),
        )

    exit_code = 0 if all(e.passed for e in evaluations) else 1
    return TrialOutcome(
        exit_code=exit_code,
        trial_dir=trial_dir,
        events=tuple(events),
        evaluations=evaluations,
        state_before_sha256=state_before_sha256,
        state_after_sha256=state_after_sha256,
        state_diff=state_diff,
    )


class _SequenceCounter:
    """A monotonic sequence starting at 1, shared across every event this trial writes."""

    def __init__(self) -> None:
        self._next = 1

    def take(self) -> int:
        value = self._next
        self._next += 1
        return value


def _event(
    trial_id: str,
    sequence: _SequenceCounter,
    clock: Any,
    event_type: EventType,
    payload: dict[str, Any],
) -> NormalizedEvent:
    number = sequence.take()
    return NormalizedEvent(
        event_id=f"evt_{trial_id}_{number}",
        trial_id=trial_id,
        sequence=number,
        timestamp=clock.now(),
        type=event_type,
        payload=payload,
    )


def _build_artifacts(
    *,
    trial_record: TrialRecord,
    events: Sequence[NormalizedEvent],
    audit_log: Sequence[Any],
    state_diff: StateDiff,
    evaluations: Sequence[EvaluationResult],
    config: RedactionConfig,
) -> dict[str, bytes]:
    """Redact every payload, scan the result, then serialize to artifact bytes.

    Redaction and the pattern scan happen here, in the one place every
    artifact passes through before `ArtifactWriter` ever sees it, matching
    NFR-04: "redacted before disk or telemetry export."

    `RedactionConfig.default()`'s schema-aware paths (`prompt`, `completion`,
    `customer.name`, `order.notes`) are a no-op against B0's own artifacts
    today: B0 involves no prompts or completions, and `TrialRecord` /
    `NormalizedEvent` / `AuditEvent` do not nest a `customer` object at those
    paths. That is expected, not a bug: those paths exist for artifact shapes
    later tickets (a real agent's prompt/completion, a richer event payload)
    will introduce, and schema-aware redaction is meant to be configured per
    the artifact it actually guards. What protects *this* ticket's artifacts
    today is `scan_for_leaks` with the trial's `canary_values`, which is
    exactly the section 16.2 canary-disclosure check and does not depend on
    knowing a field's path in advance.
    """
    payloads: dict[str, Any] = {
        "trial.json": trial_record.model_dump(mode="json"),
        "events.jsonl": [event.model_dump(mode="json") for event in events],
        "audit.jsonl": [entry.model_dump(mode="json") for entry in audit_log],
        "state_diff.json": state_diff.model_dump(mode="json"),
        "evaluations.jsonl": [e.model_dump(mode="json") for e in evaluations],
    }

    redacted = {name: redact(_as_mapping(payload), config) for name, payload in payloads.items()}

    leaks = [
        violation
        for name, payload in redacted.items()
        for violation in scan_for_leaks(payload, config)
    ]
    if leaks:
        paths = ", ".join(f"{v.path} ({v.detail})" for v in leaks)
        raise RedactionLeakError(f"redaction left {len(leaks)} leak(s) unaddressed: {paths}")

    artifacts: dict[str, bytes] = {}
    for name, payload in redacted.items():
        if name.endswith(".jsonl"):
            lines = [artifact_canonical_json(item) for item in payload["items"]]
            artifacts[name] = ("\n".join(lines) + "\n" if lines else "").encode("utf-8")
        else:
            artifacts[name] = (
                json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
            ).encode("utf-8")
    return artifacts


def _as_mapping(payload: Any) -> dict[str, Any]:
    """Wrap a list payload so `redact`/`scan_for_leaks` (which expect a mapping) can walk it."""
    if isinstance(payload, list):
        return {"items": payload}
    return dict(payload)


class RedactionLeakError(RuntimeError):
    """Raised when the pattern scanner finds a leak that schema-aware redaction missed.

    Reaching this means a configured canary or secret pattern survived
    redaction; the trial's artifacts are not written in that case, because
    acceptance criterion 16 must hold for every completed trial.
    """
