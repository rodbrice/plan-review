"""Classification of the action list Terraform records for each resource change.

In the plan JSON, ``resource_changes[].change.actions`` is a short list of strings. A
replacement is the only case with two entries, and their order says which side runs
first: ``["delete", "create"]`` destroys the old object before creating the new one
(the default), ``["create", "delete"]`` creates the new one first
(``create_before_destroy``). Any other list is not a documented Terraform action and is
rejected, so a format change surfaces as an error instead of being silently ignored.
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
}


def classify(actions: Sequence[str]) -> ChangeKind:
    """Map a ``change.actions`` list to its kind; raise ``ValueError`` if it is unknown."""
    try:
        return _KINDS[tuple(actions)]
    except KeyError:
        raise ValueError(f"unsupported action list {list(actions)!r}") from None
