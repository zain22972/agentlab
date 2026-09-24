"""Unit tests for the canonical refund-domain entities."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from maf_lab.domain.money import Money
from maf_lab.domain.refunds.models import (
    DEFAULT_REFUND_POLICY,
    AuditAction,
    AuditEvent,
    AuthorizationDecision,
    Customer,
    CustomerTier,
    EntityType,
    LineItem,
    Message,
    MessageChannel,
    Order,
    OrderStatus,
    Principal,
    ReasonCode,
    Refund,
    RefundReason,
    RefundStatus,
    Scope,
    SendStatus,
)

PURCHASED_AT = datetime(2026, 1, 25, 10, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def a_customer(**overrides: object) -> Customer:
    fields: dict[str, object] = {
        "customer_id": "cus_001",
        "name": "Example Customer",
        "region": "US",
        "verified_session": True,
    }
    fields.update(overrides)
    return Customer(**fields)  # type: ignore[arg-type]


def an_order(**overrides: object) -> Order:
    fields: dict[str, object] = {
        "order_id": "ord_100",
        "customer_id": "cus_001",
        "status": OrderStatus.DELIVERED,
        "currency": "USD",
        "paid_minor": 5000,
        "refundable_minor": 5000,
        "purchased_at": PURCHASED_AT,
    }
    fields.update(overrides)
    return Order(**fields)  # type: ignore[arg-type]


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
        "created_at": CREATED_AT,
    }
    fields.update(overrides)
    return Refund(**fields)  # type: ignore[arg-type]


class TestCustomer:
    def test_carries_identity_tier_region_and_verified_session(self) -> None:
        customer = a_customer(tier=CustomerTier.PLUS)
        assert customer.customer_id == "cus_001"
        assert customer.tier is CustomerTier.PLUS
        assert customer.region == "US"
        assert customer.verified_session is True

    def test_accepts_the_manifest_spelling_of_the_verified_flag(self) -> None:
        customer = Customer.model_validate(
            {"customer_id": "cus_001", "name": "Example", "region": "US", "verified": True}
        )
        assert customer.verified_session is True
        assert "verified_session" in customer.model_dump()

    def test_defaults_to_an_unverified_standard_customer(self) -> None:
        customer = Customer.model_validate({"customer_id": "cus_002", "name": "X", "region": "GB"})
        assert customer.verified_session is False
        assert customer.tier is CustomerTier.STANDARD

    def test_is_frozen(self) -> None:
        with pytest.raises(ValidationError):
            a_customer().verified_session = False

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            a_customer(is_admin=True)


class TestOrder:
    def test_exposes_money_valued_balances(self) -> None:
        order = an_order(paid_minor=5000, refundable_minor=3000)
        assert order.paid == Money.of(5000, "USD")
        assert order.refundable == Money.of(3000, "USD")

    def test_refundable_balance_can_never_exceed_the_paid_amount(self) -> None:
        with pytest.raises(ValidationError, match="refundable_minor"):
            an_order(paid_minor=5000, refundable_minor=5001)

    def test_refundable_balance_can_never_be_negative(self) -> None:
        with pytest.raises(ValidationError):
            an_order(refundable_minor=-1)

    def test_line_items_are_integer_minor_units(self) -> None:
        order = an_order(
            line_items=(
                LineItem(sku="sku_1", description="Lamp", quantity=1, unit_amount_minor=5000),
            )
        )
        assert order.line_items[0].unit_amount_minor == 5000

    def test_purchase_timestamp_is_normalized_to_utc(self) -> None:
        order = an_order(purchased_at="2026-01-25T12:00:00+02:00")
        assert order.purchased_at == datetime(2026, 1, 25, 10, 0, tzinfo=UTC)

    def test_rejects_a_naive_purchase_timestamp(self) -> None:
        with pytest.raises(ValidationError):
            an_order(purchased_at=datetime(2026, 1, 25, 10, 0))


class TestRefundPolicy:
    def test_default_policy_is_declared_in_minor_units(self) -> None:
        assert DEFAULT_REFUND_POLICY.max_amount_minor == 50_000
        assert DEFAULT_REFUND_POLICY.eligibility_window_days == 30

    def test_permits_only_declared_statuses(self) -> None:
        assert DEFAULT_REFUND_POLICY.permits_status(OrderStatus.DELIVERED)
        assert not DEFAULT_REFUND_POLICY.permits_status(OrderStatus.CANCELLED)

    def test_permits_only_declared_reasons(self) -> None:
        assert DEFAULT_REFUND_POLICY.permits_reason(RefundReason.DAMAGED)
        assert not DEFAULT_REFUND_POLICY.permits_reason(RefundReason.CHANGED_MIND)

    def test_requires_approval_above_the_threshold(self) -> None:
        threshold = DEFAULT_REFUND_POLICY.approval_threshold_minor
        assert not DEFAULT_REFUND_POLICY.requires_approval(threshold)
        assert DEFAULT_REFUND_POLICY.requires_approval(threshold + 1)

    def test_eligibility_deadline_is_the_window_after_purchase(self) -> None:
        assert DEFAULT_REFUND_POLICY.eligibility_deadline(PURCHASED_AT) == PURCHASED_AT + timedelta(
            days=30
        )

    def test_initial_status_follows_the_approval_threshold(self) -> None:
        threshold = DEFAULT_REFUND_POLICY.approval_threshold_minor
        assert DEFAULT_REFUND_POLICY.initial_status_for(threshold) is RefundStatus.PENDING
        assert (
            DEFAULT_REFUND_POLICY.initial_status_for(threshold + 1)
            is RefundStatus.PENDING_APPROVAL
        )


class TestRefund:
    def test_carries_amount_reason_status_key_and_timestamp(self) -> None:
        refund = a_refund()
        assert refund.amount == Money.of(2000, "USD")
        assert refund.reason is RefundReason.DAMAGED
        assert refund.status is RefundStatus.PENDING
        assert refund.idempotency_key == "idem-0000001"
        assert refund.created_at == CREATED_AT

    def test_rejects_a_zero_amount(self) -> None:
        with pytest.raises(ValidationError):
            a_refund(amount_minor=0)

    def test_rejects_a_short_idempotency_key(self) -> None:
        with pytest.raises(ValidationError):
            a_refund(idempotency_key="short")


class TestMessage:
    def test_carries_recipient_template_variables_channel_and_status(self) -> None:
        message = Message(
            message_id="msg_0001",
            customer_id="cus_001",
            template_id="tpl.refund_created",
            variables={"amount": "20.00 USD"},
            created_at=CREATED_AT,
        )
        assert message.channel is MessageChannel.EMAIL
        assert message.send_status is SendStatus.QUEUED
        assert message.variables == {"amount": "20.00 USD"}


class TestAuthorizationDecision:
    def test_allow_carries_the_authorized_reason_code(self) -> None:
        decision = AuthorizationDecision.allow()
        assert decision.allowed is True
        assert decision.reason_code is ReasonCode.AUTHORIZED

    def test_deny_carries_a_stable_reason_code_and_detail(self) -> None:
        decision = AuthorizationDecision.deny(ReasonCode.PRINCIPAL_NOT_ORDER_OWNER, "not owner")
        assert decision.allowed is False
        assert decision.reason_code is ReasonCode.PRINCIPAL_NOT_ORDER_OWNER
        assert decision.detail == "not owner"

    def test_an_allowed_decision_cannot_carry_a_denial_reason(self) -> None:
        with pytest.raises(ValidationError):
            AuthorizationDecision(allowed=True, reason_code=ReasonCode.CURRENCY_MISMATCH)

    def test_a_denied_decision_cannot_claim_authorization(self) -> None:
        with pytest.raises(ValidationError):
            AuthorizationDecision(allowed=False, reason_code=ReasonCode.AUTHORIZED)


class TestAuditEvent:
    def test_carries_sequence_actor_action_entity_hashes_decision_and_key(self) -> None:
        event = AuditEvent(
            audit_id="audit_1",
            sequence=1,
            occurred_at=CREATED_AT,
            actor="cus_001",
            action=AuditAction.REFUND_CREATE,
            entity_type=EntityType.REFUND,
            entity_id="ref_0001",
            before_sha256=DIGEST_A,
            after_sha256=DIGEST_B,
            decision=AuthorizationDecision.allow(),
            idempotency_key="idem-0000001",
        )
        assert event.sequence == 1
        assert event.mutated is True

    def test_equal_hashes_mean_state_was_untouched(self) -> None:
        event = AuditEvent(
            audit_id="audit_2",
            sequence=2,
            occurred_at=CREATED_AT,
            actor="cus_001",
            action=AuditAction.REFUND_CREATE,
            entity_type=EntityType.ORDER,
            entity_id="ord_100",
            before_sha256=DIGEST_A,
            after_sha256=DIGEST_A,
            decision=AuthorizationDecision.deny(ReasonCode.CURRENCY_MISMATCH),
            idempotency_key=None,
        )
        assert event.mutated is False

    def test_rejects_a_hash_that_is_not_a_sha256_digest(self) -> None:
        with pytest.raises(ValidationError):
            AuditEvent(
                audit_id="audit_3",
                sequence=3,
                occurred_at=CREATED_AT,
                actor="cus_001",
                action=AuditAction.REFUND_CREATE,
                entity_type=EntityType.REFUND,
                entity_id="ref_0001",
                before_sha256="not-a-digest",
                after_sha256=DIGEST_B,
                decision=AuthorizationDecision.allow(),
                idempotency_key=None,
            )


class TestPrincipal:
    def test_reports_held_scopes(self) -> None:
        principal = Principal(customer_id="cus_001", scopes=frozenset({Scope.REFUND_CREATE}))
        assert principal.has(Scope.REFUND_CREATE)
        assert not principal.has(Scope.ORDER_READ)
        assert principal.is_staff is False

    def test_parses_scopes_from_manifest_strings(self) -> None:
        principal = Principal.model_validate(
            {"customer_id": "cus_001", "scopes": ["refund:create", "order:read"]}
        )
        assert principal.has(Scope.REFUND_CREATE)
        assert principal.has(Scope.ORDER_READ)

    def test_staff_scope_is_reported(self) -> None:
        principal = Principal(customer_id="staff_1", scopes=frozenset({Scope.STAFF_READ}))
        assert principal.is_staff is True
