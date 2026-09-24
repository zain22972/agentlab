"""Unit tests for per-trial refund state built from a declared initial state."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from maf_lab.domain.clock import FakeClock
from maf_lab.domain.refunds.models import (
    AuditAction,
    AuthorizationDecision,
    Customer,
    EntityType,
    Order,
    OrderStatus,
    Principal,
    ReasonCode,
    Refund,
    RefundReason,
    RefundStatus,
    Scope,
    ToolName,
)
from maf_lab.domain.refunds.state import InitialState, RefundState, StateError

CLOCK_START = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
DIGEST = "c" * 64


def an_initial_state(**overrides: object) -> InitialState:
    fields: dict[str, object] = {
        "clock": CLOCK_START,
        "authenticated_principal": {
            "customer_id": "cus_001",
            "scopes": [Scope.REFUND_CREATE, Scope.ORDER_READ],
        },
        "customers": [
            {"customer_id": "cus_001", "name": "Example Customer", "region": "US", "verified": True}
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
        "refunds": [],
    }
    fields.update(overrides)
    return InitialState.model_validate(fields)


def a_refund(**overrides: object) -> Refund:
    fields: dict[str, object] = {
        "refund_id": "ref_0001",
        "order_id": "ord_100",
        "customer_id": "cus_001",
        "amount_minor": 2000,
        "currency": "USD",
        "reason": RefundReason.DAMAGED,
        "status": RefundStatus.PENDING,
        "idempotency_key": "idem-0000001",
        "created_at": CLOCK_START,
    }
    fields.update(overrides)
    return Refund(**fields)  # type: ignore[arg-type]


class TestInitialState:
    def test_parses_the_manifest_shape(self) -> None:
        initial = an_initial_state()
        assert initial.clock == CLOCK_START
        assert initial.authenticated_principal.customer_id == "cus_001"
        assert initial.orders[0].refundable_minor == 5000
        assert initial.refund_policy.eligibility_window_days == 30

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            an_initial_state(surprise=True)

    def test_rejects_duplicate_customer_ids(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            an_initial_state(
                customers=[
                    {"customer_id": "cus_001", "name": "A", "region": "US"},
                    {"customer_id": "cus_001", "name": "B", "region": "US"},
                ]
            )

    def test_rejects_an_order_owned_by_an_undeclared_customer(self) -> None:
        with pytest.raises(ValidationError, match="unknown customer"):
            an_initial_state(
                orders=[
                    {
                        "order_id": "ord_100",
                        "customer_id": "cus_999",
                        "status": OrderStatus.DELIVERED,
                        "currency": "USD",
                        "paid_minor": 5000,
                        "refundable_minor": 5000,
                        "purchased_at": "2026-01-25T10:00:00Z",
                    }
                ]
            )

    def test_rejects_a_refund_against_an_undeclared_order(self) -> None:
        with pytest.raises(ValidationError, match="unknown order"):
            an_initial_state(refunds=[a_refund(order_id="ord_999")])

    def test_rejects_a_refund_in_a_different_currency_from_its_order(self) -> None:
        with pytest.raises(ValidationError, match="currency"):
            an_initial_state(refunds=[a_refund(currency="EUR")])

    def test_rejects_a_balance_that_ignores_a_declared_refund(self) -> None:
        """A full balance plus an already-committed refund would exceed the amount paid."""
        with pytest.raises(ValidationError, match="exceeds the 5000 paid"):
            an_initial_state(refunds=[a_refund(amount_minor=2000)])

    def test_accepts_a_balance_that_accounts_for_a_declared_refund(self) -> None:
        initial = an_initial_state(
            orders=[
                {
                    "order_id": "ord_100",
                    "customer_id": "cus_001",
                    "status": OrderStatus.DELIVERED,
                    "currency": "USD",
                    "paid_minor": 5000,
                    "refundable_minor": 3000,
                    "purchased_at": "2026-01-25T10:00:00Z",
                }
            ],
            refunds=[a_refund(amount_minor=2000)],
        )
        state = RefundState.from_initial(initial)
        assert state.order("ord_100").refundable_minor == 3000  # type: ignore[union-attr]
        assert state.refund("ref_0001") is not None


class TestStateConstruction:
    def test_builds_a_clock_at_the_declared_instant(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        assert state.clock.now() == CLOCK_START

    def test_accepts_an_injected_clock(self) -> None:
        clock = FakeClock(CLOCK_START)
        state = RefundState.from_initial(an_initial_state(), clock=clock)
        clock.advance(timedelta(hours=1))
        assert state.clock.now() == CLOCK_START + timedelta(hours=1)

    def test_each_trial_gets_an_isolated_instance(self) -> None:
        initial = an_initial_state()
        first = RefundState.from_initial(initial)
        second = RefundState.from_initial(initial)

        first.commit_refund(a_refund())

        assert first.order("ord_100") is not None
        assert second.order("ord_100") is not None
        assert first.order("ord_100").refundable_minor == 3000  # type: ignore[union-attr]
        assert second.order("ord_100").refundable_minor == 5000  # type: ignore[union-attr]
        assert second.refund("ref_0001") is None
        assert initial.orders[0].refundable_minor == 5000

    def test_exposes_the_declared_principal_and_policy(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        assert state.principal == Principal(
            customer_id="cus_001", scopes=frozenset({Scope.REFUND_CREATE, Scope.ORDER_READ})
        )
        assert state.refund_policy.policy_id == "policy.default.v1"


class TestLookups:
    def test_finds_declared_entities(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        assert isinstance(state.customer("cus_001"), Customer)
        assert isinstance(state.order("ord_100"), Order)

    def test_returns_none_for_unknown_entities(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        assert state.customer("cus_999") is None
        assert state.order("ord_999") is None
        assert state.refund("ref_999") is None

    def test_lists_refunds_for_one_order(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        state.commit_refund(a_refund())
        assert [refund.refund_id for refund in state.refunds_for_order("ord_100")] == ["ref_0001"]
        assert state.refunds_for_order("ord_999") == ()


class TestSnapshot:
    def test_snapshot_holds_the_four_canonical_collections(self) -> None:
        snapshot = RefundState.from_initial(an_initial_state()).snapshot()
        assert set(snapshot) == {"customers", "orders", "refunds", "messages"}

    def test_snapshot_is_ordered_by_identifier(self) -> None:
        initial = an_initial_state(
            customers=[
                {"customer_id": "cus_002", "name": "B", "region": "US"},
                {"customer_id": "cus_001", "name": "A", "region": "US"},
            ],
            orders=[],
        )
        snapshot = RefundState.from_initial(initial).snapshot()
        assert [entry["customer_id"] for entry in snapshot["customers"]] == ["cus_001", "cus_002"]

    def test_snapshot_is_json_safe_and_hashable(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        assert state.snapshot()["orders"][0]["purchased_at"] == "2026-01-25T10:00:00Z"
        assert len(state.state_sha256()) == 64

    def test_snapshot_hash_changes_only_when_state_changes(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        before = state.state_sha256()
        assert state.state_sha256() == before
        state.commit_refund(a_refund())
        assert state.state_sha256() != before

    def test_snapshot_is_a_copy_a_caller_cannot_use_to_mutate_state(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        snapshot = state.snapshot()
        snapshot["orders"][0]["refundable_minor"] = 1
        assert state.order("ord_100").refundable_minor == 5000  # type: ignore[union-attr]


class TestCommitRefund:
    def test_reduces_the_refundable_balance_by_the_refund_amount(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        order = state.commit_refund(a_refund(amount_minor=2000))
        assert order.refundable_minor == 3000
        assert state.refund("ref_0001") is not None

    def test_refuses_to_overdraw_the_refundable_balance(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        with pytest.raises(StateError, match="balance"):
            state.commit_refund(a_refund(amount_minor=5001))
        assert state.order("ord_100").refundable_minor == 5000  # type: ignore[union-attr]
        assert state.refund("ref_0001") is None

    def test_refuses_a_currency_that_does_not_match_the_order(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        with pytest.raises(StateError, match="currency"):
            state.commit_refund(a_refund(currency="EUR"))

    def test_refuses_an_unknown_order(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        with pytest.raises(StateError, match="unknown order"):
            state.commit_refund(a_refund(order_id="ord_999"))

    def test_refuses_to_overwrite_an_existing_refund(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        state.commit_refund(a_refund())
        with pytest.raises(StateError, match="already exists"):
            state.commit_refund(a_refund())


class TestAuditLog:
    def test_starts_empty(self) -> None:
        assert RefundState.from_initial(an_initial_state()).audit_log == ()

    def test_sequence_is_monotonic_and_gapless(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        for _ in range(3):
            state.record_audit(
                action=AuditAction.REFUND_CREATE,
                entity_type=EntityType.ORDER,
                entity_id="ord_100",
                decision=AuthorizationDecision.deny(ReasonCode.CURRENCY_MISMATCH),
                idempotency_key=None,
                before_sha256=DIGEST,
                after_sha256=DIGEST,
            )
        assert [event.sequence for event in state.audit_log] == [1, 2, 3]
        assert [event.audit_id for event in state.audit_log] == ["audit_1", "audit_2", "audit_3"]

    def test_records_the_actor_and_the_injected_clock_instant(self) -> None:
        clock = FakeClock(CLOCK_START)
        state = RefundState.from_initial(an_initial_state(), clock=clock)
        clock.advance(timedelta(seconds=30))
        event = state.record_audit(
            action=AuditAction.REFUND_CREATE,
            entity_type=EntityType.REFUND,
            entity_id="ref_0001",
            decision=AuthorizationDecision.allow(),
            idempotency_key="idem-0000001",
            before_sha256=DIGEST,
            after_sha256="d" * 64,
        )
        assert event.actor == "cus_001"
        assert event.occurred_at == CLOCK_START + timedelta(seconds=30)
        assert event.mutated is True


class TestIdempotencyIndex:
    def test_is_keyed_by_principal_tool_and_key(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        state.record_idempotency(
            tool_name=ToolName.CREATE_REFUND,
            idempotency_key="idem-0000001",
            request_sha256=DIGEST,
            result_payload={"refund_id": "ref_0001"},
        )
        found = state.idempotency_record(
            tool_name=ToolName.CREATE_REFUND, idempotency_key="idem-0000001"
        )
        assert found is not None
        assert found.principal_id == "cus_001"
        assert found.request_sha256 == DIGEST
        assert found.result_payload == {"refund_id": "ref_0001"}

    def test_a_key_recorded_for_one_tool_is_not_found_for_another(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        state.record_idempotency(
            tool_name=ToolName.CREATE_REFUND,
            idempotency_key="idem-0000001",
            request_sha256=DIGEST,
            result_payload={},
        )
        assert (
            state.idempotency_record(
                tool_name=ToolName.SEND_CUSTOMER_MESSAGE, idempotency_key="idem-0000001"
            )
            is None
        )

    def test_refuses_to_replace_an_existing_record(self) -> None:
        state = RefundState.from_initial(an_initial_state())
        state.record_idempotency(
            tool_name=ToolName.CREATE_REFUND,
            idempotency_key="idem-0000001",
            request_sha256=DIGEST,
            result_payload={},
        )
        with pytest.raises(StateError, match="already"):
            state.record_idempotency(
                tool_name=ToolName.CREATE_REFUND,
                idempotency_key="idem-0000001",
                request_sha256=DIGEST,
                result_payload={},
            )
