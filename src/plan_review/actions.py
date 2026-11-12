"""Classification of the action list Terraform records for each resource change.

In the plan JSON, ``resource_changes[].change.actions`` is a short list of strings. Two
entries mean two steps, and their order says which runs first. A replacement is
``["delete", "create"]`` (destroy the old object, then create the new one; the default)
or ``["create", "delete"]`` (``create_before_destroy``). A ``removed`` block with
``destroy = false`` combined with a move or a new instance gives ``["create", "forget"]``
or ``["forget", "create"]``: the old object is dropped from state and left running while
a new one is created, so nothing is destroyed. Any other list is not an action Terraform
emits and is rejected, so a format change surfaces as an error instead of being silently
ignored.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum


class ChangeKind(Enum):
    """What Terraform plans to do with one resource instance."""

    NO_OP = "no-op"
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    REPLACE_DELETE_FIRST = "delete, then create"
    REPLACE_CREATE_FIRST = "create, then delete"
    FORGET = "forget"
    CREATE_THEN_FORGET = "create, then forget"
    FORGET_THEN_CREATE = "forget, then create"

    @property
    def is_replacement(self) -> bool:
        return self in (ChangeKind.REPLACE_DELETE_FIRST, ChangeKind.REPLACE_CREATE_FIRST)


_KINDS: dict[tuple[str, ...], ChangeKind] = {
    ("no-op",): ChangeKind.NO_OP,
    ("create",): ChangeKind.CREATE,
    ("read",): ChangeKind.READ,
    ("update",): ChangeKind.UPDATE,
    ("delete",): ChangeKind.DELETE,
    ("delete", "create"): ChangeKind.REPLACE_DELETE_FIRST,
    ("create", "delete"): ChangeKind.REPLACE_CREATE_FIRST,
    # Terraform 1.7+: a `removed` block with `destroy = false` drops the object from state
    # and leaves it running. Nothing is destroyed.
    ("forget",): ChangeKind.FORGET,
    ("create", "forget"): ChangeKind.CREATE_THEN_FORGET,
    ("forget", "create"): ChangeKind.FORGET_THEN_CREATE,
}


def classify(actions: Sequence[str]) -> ChangeKind:
    """Map a ``change.actions`` list to its kind; raise ``ValueError`` if it is unknown."""
    try:
        return _KINDS[tuple(actions)]
    except KeyError:
        raise ValueError(f"unsupported action list {list(actions)!r}") from None
