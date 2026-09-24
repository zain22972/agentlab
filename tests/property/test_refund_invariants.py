"""Property-based tests for the trusted refund core.

The scenario oracle in every later ticket rests on two claims that must hold for
*any* sequence of tool calls, not just the ones a scenario author thought of:

- a refundable balance can never become negative,
- one idempotency key can produce at most one effective refund.

Hypothesis drives the gateway with arbitrary arguments, including the malformed
and the malicious, and checks both claims after every call.
"""

from datetime import UTC, datetime
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from maf_lab.domain.money import Money, NegativeMoneyError
from maf_lab.domain.refunds.models import OrderStatus, RefundReason, Scope
from maf_lab.domain.refunds.state import InitialState, RefundState
from maf_lab.domain.refunds.tools import (
    IdempotencyConflict,
    InvalidRequest,
    NotFound,
    PolicyDenied,
    Success,
    ToolGateway,
)

CLOCK_START = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
PURCHASED_AT = datetime(2026, 1, 25, 10, 0, tzinfo=UTC)
KEYS = ["idem-0000001", "idem-0000002", "idem-0000003"]
RESULT_TYPES = (Success, InvalidRequest, NotFound, PolicyDenied, IdempotencyConflict)

tool_arguments = st.fixed_dictionaries(
    {
        "order_id": st.sampled_from(["ord_100", "ord_999", ""]),
        "amount_minor": st.one_of(
            st.integers(min_value=-5_000, max_value=60_000),
            st.just("two thousand"),
            st.none(),
        ),
        "currency": st.sampled_from(["USD", "EUR", "usd", "United States Dollars"]),
        "reason": st.sampled_from(
            [reason.value for reason in RefundReason] + ["ignore previous instructions"]
        ),
        "idempotency_key": st.sampled_from([*KEYS, "x"]),
    }
)


def build_state(paid_minor: int) -> RefundState:
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
                    "paid_minor": paid_minor,
                    "refundable_minor": paid_minor,
                    "purchased_at": PURCHASED_AT,
                }
            ],
        }
    )
    return RefundState.from_initial(initial)


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    paid_minor=st.integers(min_value=1, max_value=50_000),
    calls=st.lists(tool_arguments, max_size=10),
)
def test_a_refundable_balance_never_becomes_negative(
    paid_minor: int, calls: list[dict[str, Any]]
) -> None:
    state = build_state(paid_minor)
    gateway = ToolGateway(state)

    for arguments in calls:
        gateway.create_refund(arguments)
        order = state.order("ord_100")
        assert order is not None
        assert order.refundable_minor >= 0
        assert order.refundable_minor <= paid_minor


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    paid_minor=st.integers(min_value=1, max_value=50_000),
    calls=st.lists(tool_arguments, max_size=10),
)
def test_refunds_and_the_remaining_balance_always_account_for_the_paid_amount(
    paid_minor: int, calls: list[dict[str, Any]]
) -> None:
    state = build_state(paid_minor)
    gateway = ToolGateway(state)

    for arguments in calls:
        gateway.create_refund(arguments)

    order = state.order("ord_100")
    assert order is not None
    refunded = sum(refund.amount_minor for refund in state.refunds_for_order("ord_100"))
    assert refunded + order.refundable_minor == paid_minor


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    paid_minor=st.integers(min_value=1, max_value=50_000),
    calls=st.lists(tool_arguments, max_size=10),
)
def test_one_idempotency_key_yields_at_most_one_effective_refund(
    paid_minor: int, calls: list[dict[str, Any]]
) -> None:
    state = build_state(paid_minor)
    gateway = ToolGateway(state)

    for arguments in calls:
        gateway.create_refund(arguments)

    for key in KEYS:
        committed = [
            refund
            for refund in state.refunds_for_order("ord_100")
            if refund.idempotency_key == key
        ]
        assert len(committed) <= 1


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    paid_minor=st.integers(min_value=1, max_value=50_000),
    calls=st.lists(tool_arguments, max_size=10),
)
def test_every_call_returns_a_typed_result_and_appends_exactly_one_audit_event(
    paid_minor: int, calls: list[dict[str, Any]]
) -> None:
    state = build_state(paid_minor)
    gateway = ToolGateway(state)

    for index, arguments in enumerate(calls, start=1):
        result = gateway.create_refund(arguments)
        assert isinstance(result, RESULT_TYPES)
        assert len(state.audit_log) == index

    assert [event.sequence for event in state.audit_log] == list(range(1, len(calls) + 1))


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    paid_minor=st.integers(min_value=1, max_value=50_000),
    calls=st.lists(tool_arguments, max_size=10),
)
def test_only_a_success_changes_canonical_state(
    paid_minor: int, calls: list[dict[str, Any]]
) -> None:
    state = build_state(paid_minor)
    gateway = ToolGateway(state)

    for arguments in calls:
        before = state.state_sha256()
        result = gateway.create_refund(arguments)
        changed = state.state_sha256() != before
        event = state.audit_log[-1]
        assert changed == event.mutated
        if changed:
            assert isinstance(result, Success)


@settings(max_examples=500, deadline=None)
@given(
    balance=st.integers(min_value=0, max_value=1_000_000),
    amount=st.integers(min_value=0, max_value=1_000_000),
)
def test_money_subtraction_either_stays_non_negative_or_refuses(
    balance: int, amount: int
) -> None:
    try:
        remaining = Money.of(balance, "USD") - Money.of(amount, "USD")
    except NegativeMoneyError:
        assert amount > balance
    else:
        assert remaining.minor_units == balance - amount
        assert remaining.minor_units >= 0
