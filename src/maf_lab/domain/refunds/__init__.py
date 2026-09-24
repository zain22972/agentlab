"""The simulated refund-support domain.

This package is the trusted core of the lab. It runs with no model, no agent
framework and no harness present, which is what makes an authorization decision
checkable on its own terms rather than inferred from an agent's prose.

Layout:

- `models`: canonical entities, enums and the typed tool request.
- `policy`: pure authorization rules.
- `state`: per-trial isolated state, audit log and idempotency index.
- `tools`: the typed tool gateway the agent is allowed to call.
"""

from maf_lab.domain.refunds.models import (
    DEFAULT_REFUND_POLICY,
    AuditAction,
    AuditEvent,
    AuthorizationDecision,
    CreateRefundRequest,
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
    RefundPolicy,
    RefundReason,
    RefundStatus,
    Scope,
    SendStatus,
    ToolName,
    ToolOutcome,
)
from maf_lab.domain.refunds.policy import authorize_create_refund
from maf_lab.domain.refunds.state import (
    IdempotencyRecord,
    InitialState,
    RefundState,
    StateError,
)
from maf_lab.domain.refunds.tools import (
    CreateRefundData,
    CreateRefundResult,
    IdempotencyConflict,
    InvalidRequest,
    NotFound,
    PolicyDenied,
    Success,
    ToolGateway,
    TransientFailure,
    UnknownOutcome,
)

__all__ = [
    "DEFAULT_REFUND_POLICY",
    "AuditAction",
    "AuditEvent",
    "AuthorizationDecision",
    "CreateRefundData",
    "CreateRefundRequest",
    "CreateRefundResult",
    "Customer",
    "CustomerTier",
    "EntityType",
    "IdempotencyConflict",
    "IdempotencyRecord",
    "InitialState",
    "InvalidRequest",
    "LineItem",
    "Message",
    "MessageChannel",
    "NotFound",
    "Order",
    "OrderStatus",
    "PolicyDenied",
    "Principal",
    "ReasonCode",
    "Refund",
    "RefundPolicy",
    "RefundReason",
    "RefundState",
    "RefundStatus",
    "Scope",
    "SendStatus",
    "StateError",
    "Success",
    "ToolGateway",
    "ToolName",
    "ToolOutcome",
    "TransientFailure",
    "UnknownOutcome",
    "authorize_create_refund",
]
