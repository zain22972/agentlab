"""Unit tests for evaluating one state assertion against a snapshot.

This is not the full four-level evaluator pipeline (#6). It is the minimal
piece ticket #3 needs: given a state snapshot and one `StateAssertion`, produce
a typed, evidence-referencing verdict. `path` uses the same dotted/bracket
addressing `evidence.diff` uses.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from maf_lab.domain.clock import FakeClock
from maf_lab.evaluators.state_assertions import (
    UnsupportedOperatorError,
    evaluate_state_assertion,
    resolve_path,
)
from maf_lab.schemas.scenario import StateAssertion

CLOCK = FakeClock(datetime(2026, 2, 1, 12, 0, tzinfo=UTC))

SNAPSHOT: dict[str, Any] = {
    "customers": [{"customer_id": "cus_001", "name": "Example"}],
    "orders": [{"order_id": "ord_100", "refundable_minor": 3000, "currency": "USD"}],
    "refunds": [
        {"refund_id": "ref_0001", "order_id": "ord_100", "amount_minor": 2000, "currency": "USD"}
    ],
    "messages": [],
}


class TestResolvePath:
    def test_resolves_a_top_level_collection(self) -> None:
        assert resolve_path(SNAPSHOT, "refunds") == SNAPSHOT["refunds"]

    def test_resolves_an_entity_by_identifier(self) -> None:
        assert resolve_path(SNAPSHOT, "orders[ord_100]") == SNAPSHOT["orders"][0]

    def test_resolves_a_field_on_an_identified_entity(self) -> None:
        assert resolve_path(SNAPSHOT, "orders[ord_100].refundable_minor") == 3000

    def test_resolves_a_field_by_list_index(self) -> None:
        """The example manifest in spec section 10 uses `refunds[0].order_id`,
        an index rather than an identifier, so both addressing styles resolve."""
        assert resolve_path(SNAPSHOT, "refunds[0].order_id") == "ord_100"

    def test_raises_key_error_for_an_unknown_identifier(self) -> None:
        with pytest.raises(KeyError):
            resolve_path(SNAPSHOT, "orders[ord_999]")

    def test_raises_key_error_for_an_unknown_field(self) -> None:
        with pytest.raises(KeyError):
            resolve_path(SNAPSHOT, "orders[ord_100].not_a_field")


class TestEvaluateLengthEq:
    def test_passes_when_the_collection_has_the_expected_length(self) -> None:
        assertion = StateAssertion(path="refunds", op="length_eq", value=1, severity="critical")
        result = evaluate_state_assertion(assertion, SNAPSHOT, clock=CLOCK)
        assert result.passed is True
        assert result.severity == "critical"

    def test_fails_when_the_collection_has_a_different_length(self) -> None:
        assertion = StateAssertion(path="messages", op="length_eq", value=1, severity="critical")
        result = evaluate_state_assertion(assertion, SNAPSHOT, clock=CLOCK)
        assert result.passed is False


class TestEvaluateEq:
    def test_passes_when_the_resolved_value_matches(self) -> None:
        assertion = StateAssertion(
            path="orders[ord_100].refundable_minor", op="eq", value=3000, severity="critical"
        )
        assert evaluate_state_assertion(assertion, SNAPSHOT, clock=CLOCK).passed is True

    def test_fails_when_the_resolved_value_differs(self) -> None:
        assertion = StateAssertion(
            path="orders[ord_100].refundable_minor", op="eq", value=9999, severity="critical"
        )
        assert evaluate_state_assertion(assertion, SNAPSHOT, clock=CLOCK).passed is False

    def test_fails_rather_than_raises_when_the_path_does_not_resolve(self) -> None:
        """A missing path is a failed assertion, not a harness crash: the
        scenario oracle asked for something the trial did not produce, which
        is exactly the case an assertion exists to catch."""
        assertion = StateAssertion(
            path="orders[ord_999].refundable_minor", op="eq", value=1, severity="critical"
        )
        result = evaluate_state_assertion(assertion, SNAPSHOT, clock=CLOCK)
        assert result.passed is False
        assert "ord_999" in result.summary


class TestEvidenceReferences:
    def test_a_passing_result_references_the_resolved_path(self) -> None:
        assertion = StateAssertion(path="refunds", op="length_eq", value=1, severity="critical")
        result = evaluate_state_assertion(assertion, SNAPSHOT, clock=CLOCK)
        assert any("refunds" in ref for ref in result.evidence_refs)

    def test_result_carries_a_stable_reason_code(self) -> None:
        passing = StateAssertion(path="refunds", op="length_eq", value=1, severity="critical")
        failing = StateAssertion(path="refunds", op="length_eq", value=99, severity="critical")
        assert evaluate_state_assertion(passing, SNAPSHOT, clock=CLOCK).reason_code == "EXPECTED_STATE_REACHED"
        assert (
            evaluate_state_assertion(failing, SNAPSHOT, clock=CLOCK).reason_code
            == "STATE_ASSERTION_FAILED"
        )


class TestUnsupportedOperator:
    def test_an_unrecognized_operator_raises_rather_than_silently_passing(self) -> None:
        assertion = StateAssertion(path="refunds", op="matches_regex", value=".*", severity="critical")
        with pytest.raises(UnsupportedOperatorError, match="matches_regex"):
            evaluate_state_assertion(assertion, SNAPSHOT, clock=CLOCK)
