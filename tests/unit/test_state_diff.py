"""Unit tests for the deterministic structural diff between two state snapshots.

Spec FR-05: "Snapshot canonical state before and after execution and calculate a
deterministic structural diff." The diff is keyed by each collection's identifier
field (`customer_id`, `order_id`, ...) rather than by list position, because an
entity can be added or removed and the surviving entities would otherwise shift
position without having changed at all.
"""

from datetime import UTC, datetime

from maf_lab.domain.refunds.models import OrderStatus, Refund, RefundReason, RefundStatus, Scope
from maf_lab.domain.refunds.state import InitialState, RefundState
from maf_lab.evidence.diff import diff_state

CLOCK_START = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)


def make_state(refundable_minor: int = 5000) -> RefundState:
    initial = InitialState.model_validate(
        {
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
                    "refundable_minor": refundable_minor,
                    "purchased_at": "2026-01-25T10:00:00Z",
                }
            ],
        }
    )
    return RefundState.from_initial(initial)


class TestNoChange:
    def test_an_identical_snapshot_produces_an_empty_diff(self) -> None:
        state = make_state()
        before = state.snapshot()
        after = state.snapshot()
        diff = diff_state(before, after)
        assert diff.changes == ()
        assert diff.is_empty


class TestFieldChange:
    def test_a_changed_field_on_an_existing_entity_is_reported(self) -> None:
        state = make_state()
        before = state.snapshot()
        state.commit_refund(
            Refund(
                refund_id="ref_0001",
                order_id="ord_100",
                customer_id="cus_001",
                amount_minor=2000,
                currency="USD",
                reason=RefundReason.DAMAGED,
                status=RefundStatus.PENDING,
                idempotency_key="idem-0000001",
                created_at=CLOCK_START,
            )
        )
        after = state.snapshot()
        diff = diff_state(before, after)

        order_change = next(c for c in diff.changes if c.path == "orders[ord_100].refundable_minor")
        assert order_change.before == 5000
        assert order_change.after == 3000
        assert not diff.is_empty

    def test_the_diff_path_uses_the_entity_identifier_not_its_list_position(self) -> None:
        """Two orders; only the second's balance changes. The path must name
        ord_200, not orders[1], because a future added/removed entity must not
        shift an unrelated entity's diff path."""
        initial = InitialState.model_validate(
            {
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
                    },
                    {
                        "order_id": "ord_200",
                        "customer_id": "cus_001",
                        "status": OrderStatus.DELIVERED,
                        "currency": "USD",
                        "paid_minor": 1000,
                        "refundable_minor": 1000,
                        "purchased_at": "2026-01-25T10:00:00Z",
                    },
                ],
            }
        )
        two_order_state = RefundState.from_initial(initial)
        before = two_order_state.snapshot()

        two_order_state.commit_refund(
            Refund(
                refund_id="ref_0001",
                order_id="ord_200",
                customer_id="cus_001",
                amount_minor=400,
                currency="USD",
                reason=RefundReason.DAMAGED,
                status=RefundStatus.PENDING,
                idempotency_key="idem-0000001",
                created_at=CLOCK_START,
            )
        )
        after = two_order_state.snapshot()
        diff = diff_state(before, after)

        paths = [c.path for c in diff.changes]
        assert "orders[ord_200].refundable_minor" in paths
        assert not any("ord_100" in path for path in paths)


class TestAddedEntity:
    def test_a_new_entity_is_reported_as_added(self) -> None:
        state = make_state()
        before = state.snapshot()

        state.commit_refund(
            Refund(
                refund_id="ref_0001",
                order_id="ord_100",
                customer_id="cus_001",
                amount_minor=2000,
                currency="USD",
                reason=RefundReason.DAMAGED,
                status=RefundStatus.PENDING,
                idempotency_key="idem-0000001",
                created_at=CLOCK_START,
            )
        )
        after = state.snapshot()
        diff = diff_state(before, after)

        added = next(c for c in diff.changes if c.path == "refunds[ref_0001]")
        assert added.before is None
        assert added.after is not None
        assert added.after["refund_id"] == "ref_0001"


class TestRemovedEntity:
    def test_a_removed_entity_is_reported_with_after_none(self) -> None:
        before: dict[str, list[dict[str, str]]] = {
            "customers": [{"customer_id": "cus_001", "name": "A"}],
            "orders": [],
            "refunds": [],
            "messages": [],
        }
        after: dict[str, list[dict[str, str]]] = {
            "customers": [],
            "orders": [],
            "refunds": [],
            "messages": [],
        }
        diff = diff_state(before, after)

        removed = next(c for c in diff.changes if c.path == "customers[cus_001]")
        assert removed.before == {"customer_id": "cus_001", "name": "A"}
        assert removed.after is None


class TestDeterminism:
    def test_change_order_is_stable_and_sorted_by_path(self) -> None:
        before = {
            "customers": [],
            "orders": [
                {"order_id": "ord_200", "refundable_minor": 100},
                {"order_id": "ord_100", "refundable_minor": 200},
            ],
            "refunds": [],
            "messages": [],
        }
        after = {
            "customers": [],
            "orders": [
                {"order_id": "ord_200", "refundable_minor": 50},
                {"order_id": "ord_100", "refundable_minor": 150},
            ],
            "refunds": [],
            "messages": [],
        }
        diff = diff_state(before, after)
        assert [c.path for c in diff.changes] == [
            "orders[ord_100].refundable_minor",
            "orders[ord_200].refundable_minor",
        ]

    def test_recomputing_the_same_diff_twice_is_identical(self) -> None:
        state = make_state()
        before = state.snapshot()

        state.commit_refund(
            Refund(
                refund_id="ref_0001",
                order_id="ord_100",
                customer_id="cus_001",
                amount_minor=2000,
                currency="USD",
                reason=RefundReason.DAMAGED,
                status=RefundStatus.PENDING,
                idempotency_key="idem-0000001",
                created_at=CLOCK_START,
            )
        )
        after = state.snapshot()
        first = diff_state(before, after)
        second = diff_state(before, after)
        assert first.changes == second.changes


class TestNestedFieldChanges:
    def test_a_change_nested_under_a_dict_field_is_reported_by_full_path(self) -> None:
        before = {
            "customers": [],
            "orders": [],
            "refunds": [],
            "messages": [
                {"message_id": "msg_0001", "variables": {"amount": "10.00"}},
            ],
        }
        after = {
            "customers": [],
            "orders": [],
            "refunds": [],
            "messages": [
                {"message_id": "msg_0001", "variables": {"amount": "20.00"}},
            ],
        }
        diff = diff_state(before, after)
        change = next(c for c in diff.changes if c.path == "messages[msg_0001].variables.amount")
        assert change.before == "10.00"
        assert change.after == "20.00"
