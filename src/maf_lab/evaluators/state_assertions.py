"""Evaluating one state assertion against a canonical state snapshot.

This is the minimal piece ticket #3 needs: given a snapshot (the shape
`RefundState.snapshot()` and `evidence.diff` both use) and one
`StateAssertion`, produce a typed, evidence-referencing `EvaluationResult`.
The full evaluator registry, the restricted selector grammar, and the complete
operator set belong to ticket #6; this module supports the two operators the
spec's own example manifest uses (`length_eq`, `eq`) and fails loudly on any
other, rather than silently treating an unrecognized operator as a pass.

`resolve_path` accepts the same addressing `evidence.diff` produces
(`orders[ord_100].refundable_minor`) as well as list-index addressing
(`refunds[0].order_id`), because spec section 10's own example manifest uses
the latter.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from maf_lab.domain.clock import Clock
from maf_lab.domain.refunds.models import SNAPSHOT_IDENTIFIER_FIELD
from maf_lab.schemas.canonical import artifact_sha256_hex
from maf_lab.schemas.scenario import StateAssertion
from maf_lab.schemas.trial import EvaluationResult

_SEGMENT_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\[([^\]]+)\])?$")


class UnsupportedOperatorError(ValueError):
    """Raised for an assertion operator this module does not evaluate.

    Silently treating an unrecognized operator as passing would let a typo in
    a scenario's `op` field quietly disable a critical hard gate.
    """


class StatePathError(KeyError):
    """Raised when a dotted/bracket path does not resolve against a snapshot."""


def resolve_path(snapshot: dict[str, Any], path: str) -> Any:
    """Resolve a dotted/bracket path against a state snapshot.

    `orders[ord_100].refundable_minor` looks up the order whose identifier
    field equals `ord_100`; `refunds[0].order_id` looks up by list position.
    Which style applies is decided per-segment: a bracket value that matches no
    entity's identifier and is not a valid list index raises.
    """
    node: Any = snapshot
    for segment in path.split("."):
        node = _resolve_segment(node, segment, path)
    return node


def _resolve_segment(node: Any, segment: str, full_path: str) -> Any:
    match = _SEGMENT_PATTERN.match(segment)
    if match is None:
        raise StatePathError(f"malformed path segment {segment!r} in {full_path!r}")
    key, bracket = match.groups()

    if not isinstance(node, dict) or key not in node:
        raise StatePathError(f"{key!r} does not exist while resolving {full_path!r}")
    value = node[key]

    if bracket is None:
        return value
    if not isinstance(value, list):
        raise StatePathError(f"{key!r} is not a list while resolving {full_path!r}")

    if bracket.isdigit():
        index = int(bracket)
        if index >= len(value):
            raise StatePathError(f"index {index} out of range while resolving {full_path!r}")
        return value[index]

    identifier_field = SNAPSHOT_IDENTIFIER_FIELD.get(key)
    if identifier_field is not None:
        for entity in value:
            if entity.get(identifier_field) == bracket:
                return entity
    raise StatePathError(f"no entity {bracket!r} found in {key!r} while resolving {full_path!r}")


def evaluate_state_assertion(
    assertion: StateAssertion,
    snapshot: dict[str, Any],
    *,
    clock: Clock,
    trial_id: str = "",
    scenario_id: str = "",
) -> EvaluationResult:
    """Evaluate one assertion against `snapshot` and return a typed verdict.

    A path that fails to resolve is reported as a failed assertion, not raised:
    the scenario oracle asked for state the trial did not produce, which is
    exactly the case this evaluator exists to catch, not a harness defect.
    """
    if assertion.op not in ("length_eq", "eq"):
        raise UnsupportedOperatorError(
            f"operator {assertion.op!r} is not supported by this evaluator"
        )

    try:
        resolved = resolve_path(snapshot, assertion.path)
    except StatePathError as error:
        return _result(
            assertion,
            passed=False,
            reason_code="STATE_ASSERTION_FAILED",
            summary=f"could not resolve {assertion.path!r}: {error}",
            evidence_refs=(),
            trial_id=trial_id,
            scenario_id=scenario_id,
            created_at=clock.now(),
        )

    if assertion.op == "length_eq":
        passed = isinstance(resolved, list) and len(resolved) == assertion.value
        summary = f"{assertion.path} has length {len(resolved) if isinstance(resolved, list) else 'n/a'}, expected {assertion.value}"
    else:  # "eq"
        passed = resolved == assertion.value
        summary = f"{assertion.path} is {resolved!r}, expected {assertion.value!r}"

    return _result(
        assertion,
        passed=passed,
        reason_code="EXPECTED_STATE_REACHED" if passed else "STATE_ASSERTION_FAILED",
        summary=summary,
        evidence_refs=(f"state_diff.json#/{assertion.path}",),
        trial_id=trial_id,
        scenario_id=scenario_id,
        created_at=clock.now(),
    )


def _result(
    assertion: StateAssertion,
    *,
    passed: bool,
    reason_code: str,
    summary: str,
    evidence_refs: tuple[str, ...],
    trial_id: str,
    scenario_id: str,
    created_at: datetime,
) -> EvaluationResult:
    evaluation_id = f"eval_{artifact_sha256_hex({'path': assertion.path, 'op': assertion.op})[:16]}"
    return EvaluationResult(
        evaluation_id=evaluation_id,
        trial_id=trial_id,
        scenario_id=scenario_id,
        level="session",
        metric="state_oracle",
        evaluator="core.state_oracle",
        passed=passed,
        severity=assertion.severity,
        reason_code=reason_code,
        summary=summary,
        evidence_refs=evidence_refs,
        created_at=created_at,
    )


