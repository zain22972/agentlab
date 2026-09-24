"""Deterministic structural diff between two canonical state snapshots (FR-05).

`RefundState.snapshot()` returns `{"customers": [...], "orders": [...], ...}`,
each list sorted by identifier. A diff keyed by list position would relabel
every surviving entity whenever one entity is added or removed ahead of it in
sort order, so this module keys by each collection's declared identifier field
instead: an order's diff path always names its `order_id`, never its index.

The identifier field name for each top-level collection is fixed by the domain
entities in `maf_lab.domain.refunds.models` (`customer_id`, `order_id`,
`refund_id`, `message_id`), so it is hardcoded here rather than guessed.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from maf_lab.domain.refunds.models import SNAPSHOT_IDENTIFIER_FIELD


class StateChange(BaseModel):
    """One field-level difference between a before and an after snapshot.

    `path` names the changed location using the entity's identifier, e.g.
    `orders[ord_100].refundable_minor`. `before`/`after` are `None` exactly when
    the entity did not exist on that side (added or removed), never as a
    stand-in for an actual `null` value stored on the entity, since none of the
    domain's identifier or amount fields are nullable.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    before: Any
    after: Any


class StateDiff(BaseModel):
    """The complete, order-stable set of changes between two snapshots."""

    model_config = ConfigDict(frozen=True)

    changes: tuple[StateChange, ...]

    @property
    def is_empty(self) -> bool:
        """Whether the two snapshots were structurally identical."""
        return len(self.changes) == 0


def diff_state(before: dict[str, Any], after: dict[str, Any]) -> StateDiff:
    """Compute the structural diff from `before` to `after`.

    Both snapshots are expected in `RefundState.snapshot()`'s shape: a mapping
    of collection name to a list of entity dicts. Missing collections are
    treated as empty, so a diff against a hand-built partial snapshot (as in
    tests) does not need to declare every collection.
    """
    changes: list[StateChange] = []
    collection_names = sorted(set(before) | set(after))
    for collection in collection_names:
        identifier_field = SNAPSHOT_IDENTIFIER_FIELD.get(collection)
        if identifier_field is None:
            continue
        changes.extend(
            _diff_collection(
                collection,
                before.get(collection, []),
                after.get(collection, []),
                identifier_field,
            )
        )
    return StateDiff(changes=tuple(sorted(changes, key=lambda change: change.path)))


def _diff_collection(
    collection: str,
    before_entities: list[dict[str, Any]],
    after_entities: list[dict[str, Any]],
    identifier_field: str,
) -> list[StateChange]:
    before_by_id = {entity[identifier_field]: entity for entity in before_entities}
    after_by_id = {entity[identifier_field]: entity for entity in after_entities}
    changes: list[StateChange] = []

    for identifier in sorted(set(before_by_id) | set(after_by_id)):
        entity_path = f"{collection}[{identifier}]"
        before_entity = before_by_id.get(identifier)
        after_entity = after_by_id.get(identifier)
        if before_entity is None:
            changes.append(StateChange(path=entity_path, before=None, after=after_entity))
        elif after_entity is None:
            changes.append(StateChange(path=entity_path, before=before_entity, after=None))
        else:
            changes.extend(_diff_fields(entity_path, before_entity, after_entity))

    return changes


def _diff_fields(path_prefix: str, before: dict[str, Any], after: dict[str, Any]) -> list[StateChange]:
    """Recurse into nested dicts so a change is reported at its deepest scalar path."""
    changes: list[StateChange] = []
    for field in sorted(set(before) | set(after)):
        field_path = f"{path_prefix}.{field}"
        before_value = before.get(field)
        after_value = after.get(field)
        if isinstance(before_value, dict) and isinstance(after_value, dict):
            changes.extend(_diff_fields(field_path, before_value, after_value))
        elif before_value != after_value:
            changes.append(StateChange(path=field_path, before=before_value, after=after_value))
    return changes
