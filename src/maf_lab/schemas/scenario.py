"""A minimal, typed scenario description (spec section 10).

This is the shape a scenario is, not the YAML loader that will build it. That
loader, with full manifest validation (schema versioning, cross-split
discipline, capability fallbacks), belongs to ticket #7. This module exists so
the B0 agent, the orchestrator, and their tests have something concrete and
spec-shaped to construct in code today; #7's `ScenarioManifest.model_validate`
call on parsed YAML is expected to produce the same model this module defines,
so nothing downstream should need to change when the real loader lands.

Only what ticket #3 needs is modeled: enough of `oracle` to drive a B0 agent
and evaluate one critical state assertion. `stimuli`, `untrusted_content`,
`fault_plan`, `limits`, `response_assertions`, `expected_failure_categories`
and `metadata` are deliberately absent until the tickets that consume them.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from maf_lab.domain.refunds.models import ToolName
from maf_lab.domain.refunds.state import InitialState

ScenarioId = Annotated[str, StringConstraints(min_length=1, max_length=200)]

Split = Literal["development", "regression", "holdout"]
Severity = Literal["critical", "major", "minor"]


class RequiredToolCall(BaseModel):
    """One tool call the oracle expects to have happened, by name and a subset
    of its arguments.

    `args_subset` is matched as a subset, not full equality, against the
    canonical arguments a call actually used: the manifest example names
    `order_id`, `amount_minor` and `currency` without pinning the idempotency
    key an agent generates. Matching that subset is an evaluator's job (#6),
    not this schema's.
    """

    model_config = ConfigDict(frozen=True)

    name: ToolName
    args_subset: dict[str, Any] = Field(default_factory=dict)


class StateAssertion(BaseModel):
    """One assertion the oracle expects to hold against final canonical state.

    `path` uses the same dotted/bracket addressing `evidence.diff` produces
    (e.g. `refunds[ref_0001].amount_minor`), so a single evaluator can walk a
    snapshot with the same path grammar the diff already uses. The restricted
    selector grammar spec section 10 calls for belongs to the suite validator
    (#7); this schema accepts any string path, and evaluating it is #6's job.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    op: str
    value: Any
    severity: Severity


class Oracle(BaseModel):
    """What a scenario expects the agent's trial to have produced.

    Only `required_tool_calls` and `state_assertions` are modeled: the fields
    ticket #3 actually reads. `forbidden_tool_calls`, `invariants` and
    `response_assertions` belong to the tickets that evaluate them (#4, #6).
    """

    model_config = ConfigDict(frozen=True)

    required_tool_calls: tuple[RequiredToolCall, ...] = ()
    state_assertions: tuple[StateAssertion, ...] = ()

    def critical_assertions(self) -> tuple[StateAssertion, ...]:
        """The subset of `state_assertions` that are hard gates."""
        return tuple(a for a in self.state_assertions if a.severity == "critical")


class ScenarioManifest(BaseModel):
    """A single, versioned declaration of one situation the agent is placed in.

    Frozen and closed to unknown fields, matching every other model in the
    project that becomes part of a hash: the manifest hash (section 10, "The
    manifest hash covers canonical content and fixture version") requires that
    two authors writing the same content produce the same bytes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    scenario_id: ScenarioId
    family_id: str
    title: str
    split: Split
    risk: Literal["low", "medium", "high"]
    fixture_version: str
    initial_state: InitialState
    oracle: Oracle
