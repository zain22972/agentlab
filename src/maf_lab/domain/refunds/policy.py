"""Refund authorization rules.

Every function here is a pure function of typed values: a principal, the
entities it named, the trusted policy, the validated request and the instant the
request was made. No model output, no framework, no state store, no I/O.

That purity is the product, not a style preference. An authorization decision
that can be recomputed from evidence is a decision a reviewer can check without
paying for a model call, and a decision a mutant test can attack directly.
"""

from __future__ import annotations

from datetime import datetime

from maf_lab.domain.money import Money
from maf_lab.domain.refunds.models import (
    AuthorizationDecision,
    CreateRefundRequest,
    Customer,
    Order,
    Principal,
    ReasonCode,
    RefundPolicy,
    Scope,
)


def authorize_create_refund(
    *,
    principal: Principal,
    customer: Customer | None,
    order: Order | None,
    policy: RefundPolicy,
    request: CreateRefundRequest,
    now: datetime,
) -> AuthorizationDecision:
    """Decide whether `principal` may create the refund described by `request`.

    Checks run identity first, then ownership, then policy, then amounts. The
    order is deliberate: a denial detail for an order the principal does not own
    must not disclose anything about that order, so ownership is settled before
    any field of the order is described in a reason.

    `now` comes from the trial's injected clock, passed in so this stays a
    function of values alone.
    """
    if not principal.has(Scope.REFUND_CREATE):
        return AuthorizationDecision.deny(
            ReasonCode.SCOPE_MISSING,
            f"principal lacks scope {Scope.REFUND_CREATE.value}",
        )
    if customer is None:
        return AuthorizationDecision.deny(
            ReasonCode.CUSTOMER_NOT_FOUND, "authenticated principal is not a known customer"
        )
    if not customer.verified_session:
        return AuthorizationDecision.deny(
            ReasonCode.SESSION_NOT_VERIFIED, "session is not verified"
        )
    if order is None:
        return AuthorizationDecision.deny(
            ReasonCode.ORDER_NOT_FOUND, f"order {request.order_id} does not exist"
        )
    if order.customer_id != principal.customer_id:
        return AuthorizationDecision.deny(
            ReasonCode.PRINCIPAL_NOT_ORDER_OWNER,
            "order is not owned by the authenticated principal",
        )
    if not policy.permits_status(order.status):
        return AuthorizationDecision.deny(
            ReasonCode.ORDER_STATUS_NOT_REFUNDABLE,
            f"order status {order.status.value} is not refundable",
        )
    if now > policy.eligibility_deadline(order.purchased_at):
        return AuthorizationDecision.deny(
            ReasonCode.ELIGIBILITY_WINDOW_EXPIRED,
            f"eligibility window of {policy.eligibility_window_days} days has passed",
        )
    if request.currency != order.currency:
        return AuthorizationDecision.deny(
            ReasonCode.CURRENCY_MISMATCH,
            f"requested {request.currency} against an order in {order.currency}",
        )
    if not policy.permits_reason(request.reason):
        return AuthorizationDecision.deny(
            ReasonCode.REASON_NOT_PERMITTED,
            f"reason {request.reason.value} is not permitted by {policy.policy_id}",
        )
    if request.amount_minor > policy.max_amount_minor:
        return AuthorizationDecision.deny(
            ReasonCode.AMOUNT_EXCEEDS_POLICY_MAXIMUM,
            f"amount exceeds the policy maximum of {policy.max_amount_minor}",
        )
    requested = Money(minor_units=request.amount_minor, currency=request.currency)
    if requested > order.refundable:
        return AuthorizationDecision.deny(
            ReasonCode.AMOUNT_EXCEEDS_REFUNDABLE_BALANCE,
            f"amount exceeds the refundable balance of {order.refundable_minor}",
        )
    return AuthorizationDecision.allow()
