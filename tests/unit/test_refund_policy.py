"""Unit tests for refund authorization, a pure function of typed state.

Every test here calls the decision function with literal values: no state store,
no tool gateway, no agent, no framework. That is the point of the seam.
"""

from datetime import UTC, datetime, timedelta

from maf_lab.domain.refunds.models import (
    DEFAULT_REFUND_POLICY,
    CreateRefundRequest,
    Customer,
    Order,
    OrderStatus,
    Principal,
    ReasonCode,
    RefundReason,
    RefundStatus,
    Scope,
)
from maf_lab.domain.refunds.policy import authorize_create_refund

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
PURCHASED_AT = datetime(2026, 1, 25, 10, 0, tzinfo=UTC)

CUSTOMER = Customer(
    customer_id="cus_001", name="Example Customer", region="US", verified_session=True
)
ORDER = Order(
    order_id="ord_100",
    customer_id="cus_001",
    status=OrderStatus.DELIVERED,
    currency="USD",
    paid_minor=5000,
    refundable_minor=5000,
    purchased_at=PURCHASED_AT,
)
PRINCIPAL = Principal(
    customer_id="cus_001", scopes=frozenset({Scope.REFUND_CREATE, Scope.ORDER_READ})
)


def a_request(**overrides: object) -> CreateRefundRequest:
    fields: dict[str, object] = {
        "order_id": "ord_100",
        "amount_minor": 2000,
        "currency": "USD",
        "reason": RefundReason.DAMAGED,
        "idempotency_key": "idem-0000001",
    }
    fields.update(overrides)
    return CreateRefundRequest(**fields)  # type: ignore[arg-type]


def decide(
    *,
    principal: Principal = PRINCIPAL,
    customer: Customer | None = CUSTOMER,
    order: Order | None = ORDER,
    request: CreateRefundRequest | None = None,
    now: datetime = NOW,
) -> ReasonCode:
    decision = authorize_create_refund(
        principal=principal,
        customer=customer,
        order=order,
        policy=DEFAULT_REFUND_POLICY,
        request=request if request is not None else a_request(),
        now=now,
    )
    assert decision.allowed is (decision.reason_code is ReasonCode.AUTHORIZED)
    return decision.reason_code


def test_authorizes_an_eligible_partial_refund() -> None:
    assert decide() == ReasonCode.AUTHORIZED


def test_authorizes_a_full_refund_of_the_remaining_balance() -> None:
    assert decide(request=a_request(amount_minor=5000)) == ReasonCode.AUTHORIZED


def test_requires_the_refund_create_scope() -> None:
    without_scope = Principal(customer_id="cus_001", scopes=frozenset({Scope.ORDER_READ}))
    assert decide(principal=without_scope) == ReasonCode.SCOPE_MISSING


def test_requires_a_known_principal() -> None:
    assert decide(customer=None) == ReasonCode.CUSTOMER_NOT_FOUND


def test_requires_a_verified_session() -> None:
    unverified = CUSTOMER.model_copy(update={"verified_session": False})
    assert decide(customer=unverified) == ReasonCode.SESSION_NOT_VERIFIED


def test_reports_a_missing_order_distinctly_from_a_denial() -> None:
    assert decide(order=None) == ReasonCode.ORDER_NOT_FOUND


def test_denies_an_order_the_principal_does_not_own() -> None:
    other = ORDER.model_copy(update={"customer_id": "cus_002"})
    assert decide(order=other) == ReasonCode.PRINCIPAL_NOT_ORDER_OWNER


def test_a_staff_read_scope_does_not_grant_refunds_on_another_customers_order() -> None:
    staff_principal = Principal(
        customer_id="staff_1", scopes=frozenset({Scope.STAFF_READ, Scope.REFUND_CREATE})
    )
    staff_customer = CUSTOMER.model_copy(update={"customer_id": "staff_1"})
    assert (
        decide(principal=staff_principal, customer=staff_customer)
        == ReasonCode.PRINCIPAL_NOT_ORDER_OWNER
    )


def test_denial_detail_never_names_the_other_customer() -> None:
    other = ORDER.model_copy(update={"customer_id": "cus_002"})
    decision = authorize_create_refund(
        principal=PRINCIPAL,
        customer=CUSTOMER,
        order=other,
        policy=DEFAULT_REFUND_POLICY,
        request=a_request(),
        now=NOW,
    )
    assert "cus_002" not in decision.detail


def test_denies_a_status_the_policy_does_not_allow() -> None:
    cancelled = ORDER.model_copy(update={"status": OrderStatus.CANCELLED})
    assert decide(order=cancelled) == ReasonCode.ORDER_STATUS_NOT_REFUNDABLE


def test_allows_a_refund_on_the_last_day_of_the_eligibility_window() -> None:
    last_moment = PURCHASED_AT + timedelta(days=DEFAULT_REFUND_POLICY.eligibility_window_days)
    assert decide(now=last_moment) == ReasonCode.AUTHORIZED


def test_denies_a_refund_one_second_past_the_eligibility_window() -> None:
    expired = (
        PURCHASED_AT
        + timedelta(days=DEFAULT_REFUND_POLICY.eligibility_window_days)
        + timedelta(seconds=1)
    )
    assert decide(now=expired) == ReasonCode.ELIGIBILITY_WINDOW_EXPIRED


def test_denies_a_currency_that_does_not_match_the_order() -> None:
    assert decide(request=a_request(currency="EUR")) == ReasonCode.CURRENCY_MISMATCH


def test_denies_a_reason_the_policy_does_not_permit() -> None:
    assert (
        decide(request=a_request(reason=RefundReason.CHANGED_MIND))
        == ReasonCode.REASON_NOT_PERMITTED
    )


def test_denies_an_amount_above_the_policy_maximum() -> None:
    rich_order = ORDER.model_copy(update={"paid_minor": 90_000, "refundable_minor": 90_000})
    request = a_request(amount_minor=DEFAULT_REFUND_POLICY.max_amount_minor + 1)
    assert decide(order=rich_order, request=request) == ReasonCode.AMOUNT_EXCEEDS_POLICY_MAXIMUM


def test_denies_an_amount_above_the_refundable_balance() -> None:
    partly_refunded = ORDER.model_copy(update={"refundable_minor": 1500})
    assert (
        decide(order=partly_refunded, request=a_request(amount_minor=1501))
        == ReasonCode.AMOUNT_EXCEEDS_REFUNDABLE_BALANCE
    )


def test_denies_a_refund_against_a_zero_balance() -> None:
    exhausted = ORDER.model_copy(update={"refundable_minor": 0})
    assert decide(order=exhausted) == ReasonCode.AMOUNT_EXCEEDS_REFUNDABLE_BALANCE


def test_ownership_is_checked_before_policy_details() -> None:
    other_and_cancelled = ORDER.model_copy(
        update={"customer_id": "cus_002", "status": OrderStatus.CANCELLED}
    )
    assert decide(order=other_and_cancelled) == ReasonCode.PRINCIPAL_NOT_ORDER_OWNER


def test_refund_status_follows_the_approval_threshold() -> None:
    threshold = DEFAULT_REFUND_POLICY.approval_threshold_minor
    assert DEFAULT_REFUND_POLICY.initial_status_for(threshold) is RefundStatus.PENDING
    assert (
        DEFAULT_REFUND_POLICY.initial_status_for(threshold + 1) is RefundStatus.PENDING_APPROVAL
    )
