"""Trimmed normalized records for one trial (spec section 11.1, 11.3).

Only the fields ticket #3 actually produces are modeled. `EvaluationResult`
omits `evaluator_version`, `kind`, `threshold`, `failure_category` and
`details`: those belong to the full evaluator registry (#6). `TrialRecord`
omits `agent`, `usage`, `limits` and `retrieval`: B0 involves no model, no
cost, no limits enforcement and no retrieval. Both models are meant to grow
additively as later tickets add the fields they own, never to be replaced.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from maf_lab.domain.clock import UtcDatetime

TrialStatus = Literal["completed", "failed"]
EvaluationLevel = Literal["tool", "turn", "session", "system"]

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class EvaluationResult(BaseModel):
    """One deterministic verdict against one scenario oracle assertion.

    Spec section 11.3's full shape carries `evaluator_version`, `kind`,
    `threshold`, `failure_category` and `details` as well; those are added when
    the evaluator registry (#6) exists to populate them meaningfully.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    evaluation_id: str
    trial_id: str
    scenario_id: str
    level: EvaluationLevel
    metric: str
    evaluator: str
    passed: bool
    severity: Literal["critical", "major", "minor"]
    reason_code: str
    summary: str
    evidence_refs: tuple[str, ...] = ()
    created_at: UtcDatetime


class TrialRecord(BaseModel):
    """The canonical record of one completed trial (trimmed spec section 11.1).

    `manifest_sha256` and `state.before_sha256`/`after_sha256` are what
    acceptance criterion 13 ("state hashes, manifest hash") requires be present
    on every completed trial.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    trial_id: str
    scenario_id: str
    trial_index: int = Field(ge=0)
    status: TrialStatus
    started_at: UtcDatetime
    duration_ms: int = Field(ge=0)
    manifest_sha256: Sha256Hex
    fixture_version: str
    state_before_sha256: Sha256Hex
    state_after_sha256: Sha256Hex
    store_profile: Literal["memory", "durable"] = "memory"
