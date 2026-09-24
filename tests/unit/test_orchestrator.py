"""Unit tests for the trial orchestrator (spec section 8, issue #3 acceptance criteria).

The orchestrator is what a single CLI invocation drives: build isolated state
from a scenario, run the B0 agent, record ordered events, snapshot and diff
canonical state, evaluate the scenario's critical assertions, redact, and
commit artifacts. Every acceptance criterion in issue #3 is checked against
this module's output directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from maf_lab.domain.refunds.models import OrderStatus, Scope
from maf_lab.evidence.writer import verify_checksums
from maf_lab.runner.orchestrator import TrialOutcome, execute_trial
from maf_lab.schemas.events import assert_contiguous_sequence
from maf_lab.schemas.scenario import ScenarioManifest

CLOCK_START = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)


def eligible_refund_scenario() -> ScenarioManifest:
    """The spec section 10 example: an eligible customer refunds part of an order."""
    return ScenarioManifest.model_validate(
        {
            "schema_version": "1.0",
            "scenario_id": "refund.eligible.single.v1",
            "family_id": "refund.eligible",
            "title": "Eligible customer requests a partial refund",
            "split": "regression",
            "risk": "high",
            "fixture_version": "refund-fixtures-1.0",
            "initial_state": {
                "clock": CLOCK_START,
                "authenticated_principal": {
                    "customer_id": "cus_001",
                    "scopes": [Scope.REFUND_CREATE, Scope.ORDER_READ],
                },
                "customers": [
                    {
                        "customer_id": "cus_001",
                        "name": "Example Customer",
                        "region": "US",
                        "verified": True,
                    }
                ],
                "orders": [
                    {
                        "order_id": "ord_100",
                        "customer_id": "cus_001",
                        "status": OrderStatus.DELIVERED,
                        "currency": "USD",
                        "paid_minor": 5000,
                        "refundable_minor": 5000,
                        "purchased_at": "2026-01-25T10:00:00Z",
                    }
                ],
            },
            "oracle": {
                "required_tool_calls": [
                    {
                        "name": "create_refund",
                        "args_subset": {
                            "order_id": "ord_100",
                            "amount_minor": 2000,
                            "currency": "USD",
                            "reason": "damaged",
                        },
                    }
                ],
                "state_assertions": [
                    {
                        "path": "orders[ord_100].refundable_minor",
                        "op": "eq",
                        "value": 3000,
                        "severity": "critical",
                    }
                ],
            },
        }
    )


class TestSuccessfulTrial:
    def test_returns_a_zero_exit_code(self, tmp_path: Path) -> None:
        outcome = execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path
        )
        assert outcome.exit_code == 0

    def test_the_committed_directory_exists_and_verifies(self, tmp_path: Path) -> None:
        outcome = execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path
        )
        assert outcome.trial_dir == tmp_path / "trial_0001"
        assert (outcome.trial_dir / "COMMITTED").exists()
        assert verify_checksums(outcome.trial_dir) is True

    def test_records_ordered_contiguous_events(self, tmp_path: Path) -> None:
        outcome = execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path
        )
        assert_contiguous_sequence(outcome.events)  # does not raise
        assert len(outcome.events) >= 3  # started, at least one tool event, ended
        assert outcome.events[0].type.value == "trial.started"
        assert outcome.events[-1].type.value == "trial.ended"

    def test_snapshots_state_before_and_after_and_produces_a_diff(self, tmp_path: Path) -> None:
        outcome = execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path
        )
        assert outcome.state_before_sha256 != outcome.state_after_sha256
        assert not outcome.state_diff.is_empty
        assert any(
            change.path == "orders[ord_100].refundable_minor" for change in outcome.state_diff.changes
        )

    def test_evaluates_the_critical_assertion_and_it_passes(self, tmp_path: Path) -> None:
        outcome = execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path
        )
        assert len(outcome.evaluations) == 1
        assert outcome.evaluations[0].passed is True
        assert outcome.evaluations[0].severity == "critical"
        assert outcome.evaluations[0].evidence_refs

    def test_writes_the_trial_record_events_audit_diff_and_evaluations_artifacts(
        self, tmp_path: Path
    ) -> None:
        outcome = execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path
        )
        names = {p.name for p in outcome.trial_dir.iterdir()}
        assert {
            "trial.json",
            "events.jsonl",
            "audit.jsonl",
            "state_diff.json",
            "evaluations.jsonl",
            "checksums.sha256",
            "COMMITTED",
        } <= names

    def test_events_jsonl_has_one_json_object_per_line(self, tmp_path: Path) -> None:
        import json

        outcome = execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path
        )
        lines = (outcome.trial_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == len(outcome.events)
        for line in lines:
            json.loads(line)  # does not raise

    def test_the_trial_record_carries_the_manifest_and_state_hashes(self, tmp_path: Path) -> None:
        import json

        outcome = execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path
        )
        record = json.loads((outcome.trial_dir / "trial.json").read_text(encoding="utf-8"))
        assert record["trial_id"] == "trial_0001"
        assert record["status"] == "completed"
        assert record["state_before_sha256"] == outcome.state_before_sha256
        assert record["state_after_sha256"] == outcome.state_after_sha256
        assert len(record["manifest_sha256"]) == 64


class TestReproducibility:
    def test_two_executions_of_the_same_scenario_produce_the_same_verdict_and_hashes(
        self, tmp_path: Path
    ) -> None:
        first = execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path / "a"
        )
        second = execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path / "b"
        )
        assert first.state_before_sha256 == second.state_before_sha256
        assert first.state_after_sha256 == second.state_after_sha256
        assert [e.passed for e in first.evaluations] == [e.passed for e in second.evaluations]
        assert [e.model_dump(exclude={"created_at"}) for e in first.evaluations] == [
            e.model_dump(exclude={"created_at"}) for e in second.evaluations
        ]


class TestHarnessFailuresExitCleanly:
    def test_a_scenario_requiring_an_unimplemented_tool_exits_nonzero_rather_than_raising(
        self, tmp_path: Path
    ) -> None:
        """`get_customer` is allowlisted (schemas/scenario.py) but not yet
        implemented by the gateway (pending #5). B0Agent raises
        UnsupportedToolError for it; execute_trial must turn that into a clean
        non-zero TrialOutcome, not propagate an uncaught exception, so a single
        CLI invocation always returns a controlled exit code (AC1)."""
        base = eligible_refund_scenario()
        dumped = base.model_dump(mode="json")
        dumped["oracle"]["required_tool_calls"].append(
            {"name": "get_customer", "args_subset": {}}
        )
        unsupported = ScenarioManifest.model_validate(dumped)
        outcome = execute_trial(
            manifest=unsupported, trial_id="trial_0001", artifacts_root=tmp_path
        )
        assert outcome.exit_code != 0
        assert outcome.error is not None
        assert "get_customer" in outcome.error


class TestNeverOverwritesACompletedTrial:
    def test_a_second_execution_with_the_same_trial_id_is_refused(self, tmp_path: Path) -> None:
        execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path
        )
        outcome = execute_trial(
            manifest=eligible_refund_scenario(), trial_id="trial_0001", artifacts_root=tmp_path
        )
        assert outcome.exit_code != 0


class TestRedaction:
    def test_a_configured_canary_value_present_in_the_trial_does_not_reach_any_artifact(
        self, tmp_path: Path
    ) -> None:
        manifest = eligible_refund_scenario()
        canary = "CANARY-af31-do-not-disclose"
        # A canary the manifest's customer name happens to carry, standing in
        # for a value an indirect-injection scenario would smuggle into free
        # text. The point under test is that execute_trial scans and redacts
        # whatever canary_values names, regardless of which field carries it.
        poisoned = manifest.model_copy(
            update={
                "initial_state": manifest.initial_state.model_copy(
                    update={
                        "customers": (
                            manifest.initial_state.customers[0].model_copy(
                                update={"name": canary}
                            ),
                        )
                    }
                )
            }
        )
        outcome = execute_trial(
            manifest=poisoned,
            trial_id="trial_0001",
            artifacts_root=tmp_path,
            canary_values=frozenset({canary}),
        )
        assert outcome.exit_code == 0
        for artifact_file in outcome.trial_dir.glob("*"):
            if artifact_file.is_file() and artifact_file.suffix in {".json", ".jsonl"}:
                assert canary not in artifact_file.read_text(encoding="utf-8")


def test_trial_outcome_is_a_named_tuple_with_the_documented_fields() -> None:
    assert set(TrialOutcome._fields) >= {
        "exit_code",
        "trial_dir",
        "events",
        "evaluations",
        "state_before_sha256",
        "state_after_sha256",
        "state_diff",
    }
