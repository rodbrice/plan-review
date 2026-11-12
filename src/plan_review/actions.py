"""Classification of the action list Terraform records for each resource change.

In the plan JSON, ``resource_changes[].change.actions`` is a short list of strings. Two
entries mean a replacement, and their order says which step runs first:
``["delete", "create"]`` destroys the old object before creating the new one (the
default) and ``["create", "delete"]`` creates the new one first
(``create_before_destroy``). When the resource block has ``lifecycle { destroy = false }``
and is replaced anyway, Terraform writes ``["forget", "create"]`` or
``["create", "forget"]`` instead: the old object is removed from state and left running
rather than destroyed, and a new object is created at the same address. Any other list
is not an action Terraform emits and is rejected, so a format change surfaces as an error
instead of being silently ignored.
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
    REPLACE_FORGET_FIRST = "forget, then create"
    REPLACE_CREATE_FIRST_KEEP_OLD = "create, then forget"

    @property
    def is_replacement(self) -> bool:
        return self in (
            ChangeKind.REPLACE_DELETE_FIRST,
            ChangeKind.REPLACE_CREATE_FIRST,
            ChangeKind.REPLACE_FORGET_FIRST,
            ChangeKind.REPLACE_CREATE_FIRST_KEEP_OLD,
        )

    @property
    def keeps_old_object(self) -> bool:
        """The replaced object is dropped from state and left running, not destroyed."""
        return self in (ChangeKind.REPLACE_FORGET_FIRST, ChangeKind.REPLACE_CREATE_FIRST_KEEP_OLD)


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
    # A resource with `lifecycle { destroy = false }` that is replaced: the old object is
    # dropped from state and left running, and a new one is created.
    ("forget", "create"): ChangeKind.REPLACE_FORGET_FIRST,
    ("create", "forget"): ChangeKind.REPLACE_CREATE_FIRST_KEEP_OLD,
}


def classify(actions: Sequence[str]) -> ChangeKind:
    """Map a ``change.actions`` list to its kind; raise ``ValueError`` if it is unknown."""
    try:
        return _KINDS[tuple(actions)]
    except KeyError:
        raise ValueError(f"unsupported action list {list(actions)!r}") from None
