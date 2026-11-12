"""The review rules.

A rule is a pure function from one resource change to a list of findings, usually empty.
Rules only look at what the plan says will happen (``change.actions``,
``action_reason``, ``replace_paths``) and at the resource type; they never copy an
attribute value into a finding, so sensitive values cannot leak into the report.

- R1: a stateful resource is destroyed.
- R2: a stateful resource is replaced, in either order, including when
  ``lifecycle { destroy = false }`` keeps the old object running instead of destroying it.

Data sources (``mode = "data"``) are read, never destroyed, so the rules skip them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from plan_review.actions import ChangeKind
from plan_review.findings import Finding, Severity
from plan_review.model import PathStep, Plan, ResourceChange
from plan_review.stateful import STATEFUL_TYPES

Rule = Callable[[ResourceChange], list[Finding]]

# action_reason values documented by Terraform, phrased to follow "because".
_REASONS: dict[str, str] = {
    "delete_because_no_resource_config": "it was removed from the configuration",
    "delete_because_no_module": "its module was removed from the configuration",
    "delete_because_wrong_repetition": "the resource switched between count and for_each",
    "delete_because_count_index": "its count index is no longer in range",
    "delete_because_each_key": "its for_each key is no longer present",
    "delete_because_no_move_target": "it was moved to an address that has no configuration",
    "replace_because_tainted": "the object is tainted",
    "replace_because_cannot_update": "an attribute that cannot be updated in place changed",
    "replace_by_request": "replacement was requested with -replace",
    "replace_by_triggers": "a replace_triggered_by reference changed",
}


def r1_stateful_destroyed(change: ResourceChange) -> list[Finding]:
    """R1: a resource that holds data is destroyed."""
    if change.mode != "managed" or change.change.kind is not ChangeKind.DELETE:
        return []
    lost = STATEFUL_TYPES.get(change.type)
    if lost is None:
        return []
    why = f"Destroyed{_because(change)}. It holds {lost}."
    return [Finding("R1", Severity.HIGH, change.address, why)]


def r2_stateful_replaced(change: ResourceChange) -> list[Finding]:
    """R2: a resource that holds data is replaced, whichever side runs first."""
    kind = change.change.kind
    if change.mode != "managed" or not kind.is_replacement:
        return []
    lost = STATEFUL_TYPES.get(change.type)
    if lost is None:
        return []
    why = f"Replaced ({kind.value}){_because(change)}."
    if change.change.replace_paths:
        forced_by = ", ".join(
            _describe_path(path, unknown=change.change.is_unknown_after(path))
            for path in change.change.replace_paths
        )
        why += f" Forced by: {forced_by}."
    if kind.keeps_old_object:
        why += (
            f" It holds {lost}; the old object is removed from Terraform state and left "
            "running rather than destroyed, and the managed object at this address starts "
            "empty."
        )
    else:
        why += f" It holds {lost}, and the new object starts empty."
    return [Finding("R2", Severity.HIGH, change.address, why)]


RULES: tuple[Rule, ...] = (r1_stateful_destroyed, r2_stateful_replaced)


def evaluate(plan: Plan, rules: Sequence[Rule] = RULES) -> list[Finding]:
    """Run every rule on every resource change, in plan order."""
    return [
        finding for change in plan.resource_changes for rule in rules for finding in rule(change)
    ]


def _because(change: ResourceChange) -> str:
    reason = change.action_reason
    if reason is None:
        return ""
    if reason in _REASONS:
        return f", because {_REASONS[reason]}"
    return f" (Terraform reason: {reason})"


def _describe_path(path: Sequence[PathStep], *, unknown: bool) -> str:
    text = ""
    for step in path:
        if isinstance(step, int):
            text += f"[{step}]"
        else:
            text += f".{step}" if text else step
    return f"{text} (known after apply)" if unknown else text
