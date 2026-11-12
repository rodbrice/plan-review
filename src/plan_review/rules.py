"""The review rules.

A rule is a pure function from one resource change to a list of findings, usually empty.
R1 and R2 look only at what the plan says will happen (``change.actions``,
``action_reason``, ``replace_paths``) and at the resource type. R3 to R5 compare
``before`` with ``after`` and report only what is new in ``after``: a wildcard that was
already granted, a port that was already open or a protection that was already off is
not a finding.

- R1: a stateful resource is destroyed.
- R2: a stateful resource is replaced, in either order, including when
  ``lifecycle { destroy = false }`` keeps the old object running instead of destroying it.
- R3: an IAM policy grants a new wildcard action or resource.
- R4: an ingress rule is newly open to ``0.0.0.0/0`` or ``::/0``.
- R5: a bucket loses public-access protection or is made public by ACL or bucket policy.

Findings quote the parts of a value the reviewer needs (an IAM action, a port), never a
value Terraform marks as sensitive. Data sources (``mode = "data"``) are read, never
changed, so the rules skip them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from plan_review.actions import ChangeKind
from plan_review.exposure import (
    new_open_ingress,
    new_public_acl,
    new_public_bucket_statements,
    removed_public_access_blocks,
)
from plan_review.findings import Finding, Severity
from plan_review.iam import Grant, PolicyError, parse_policy, wide_grants
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


# Identity-based policy resources and the attribute that holds the document.
IAM_POLICY_ATTRIBUTE: dict[str, str] = {
    "aws_iam_policy": "policy",
    "aws_iam_role_policy": "policy",
    "aws_iam_user_policy": "policy",
    "aws_iam_group_policy": "policy",
}

# At most this many items are listed in one finding; the rest are counted.
_LISTED = 5


def r3_iam_widened(change: ResourceChange) -> list[Finding]:
    """R3: an IAM policy grants a wildcard action or resource it did not grant before."""
    attribute = IAM_POLICY_ATTRIBUTE.get(change.type)
    if attribute is None or not _has_after(change):
        return []
    after = _attribute(change.change.after, attribute)
    if change.change.is_unknown_after([attribute]):
        why = "The policy document is known only after apply, so it was not compared."
        return [Finding("R3", Severity.LOW, change.address, why)]
    if not isinstance(after, str):
        return []
    try:
        granted = wide_grants(parse_policy(after))
    except PolicyError as error:
        why = f"The new policy document could not be read: {error}."
        return [Finding("R3", Severity.LOW, change.address, why)]
    new = granted - _grants_before(change, attribute)
    if not new:
        return []
    if change.change.is_sensitive([attribute]):
        detail = f"{len(new)} new wildcard grant(s); the document is sensitive and not shown"
    else:
        detail = _listing([grant.describe() for grant in sorted(new)])
    lead = "New policy allows" if change.change.before is None else "Policy widened, now allows"
    return [Finding("R3", Severity.HIGH, change.address, f"{lead}: {detail}.")]


def r4_ingress_open_to_world(change: ResourceChange) -> list[Finding]:
    """R4: an ingress rule opens a port to the whole IPv4 or IPv6 internet."""
    if change.mode != "managed" or not _has_after(change):
        return []
    opened = new_open_ingress(change)
    if not opened:
        return []
    why = f"Ingress newly open to the internet: {_listing(opened)}."
    return [Finding("R4", Severity.HIGH, change.address, why)]


def r5_bucket_public(change: ResourceChange) -> list[Finding]:
    """R5: a bucket loses its public-access block, or an ACL or policy makes it public."""
    if change.mode != "managed":
        return []
    reasons = [
        *removed_public_access_blocks(change),
        *new_public_acl(change),
        *new_public_bucket_statements(change),
    ]
    return [Finding("R5", Severity.HIGH, change.address, reason) for reason in reasons]


RULES: tuple[Rule, ...] = (
    r1_stateful_destroyed,
    r2_stateful_replaced,
    r3_iam_widened,
    r4_ingress_open_to_world,
    r5_bucket_public,
)

# Rule ID -> short title, used by the Markdown and JSON reports and to validate the
# configuration file.
RULE_TITLES: dict[str, str] = {
    "R1": "Stateful resource destroyed",
    "R2": "Stateful resource replaced",
    "R3": "IAM policy widened",
    "R4": "Ingress open to the world",
    "R5": "Bucket made public",
}


def evaluate(plan: Plan, rules: Sequence[Rule] = RULES) -> list[Finding]:
    """Run every rule on every resource change, in plan order."""
    return [
        finding for change in plan.resource_changes for rule in rules for finding in rule(change)
    ]


def _has_after(change: ResourceChange) -> bool:
    """The change leaves an object in place whose new values the plan describes."""
    kind = change.change.kind
    return change.mode == "managed" and (
        kind in (ChangeKind.CREATE, ChangeKind.UPDATE) or kind.is_replacement
    )


def _attribute(values: object, name: str) -> object:
    return values.get(name) if isinstance(values, dict) else None


def _grants_before(change: ResourceChange, attribute: str) -> set[Grant]:
    # A replacement starts a new object, but the access it grants is what matters, so
    # the old document is still the baseline.
    before = _attribute(change.change.before, attribute)
    if not isinstance(before, str):
        return set()
    try:
        return wide_grants(parse_policy(before))
    except PolicyError:
        return set()


def _listing(items: Sequence[str]) -> str:
    shown = ", ".join(items[:_LISTED])
    if len(items) > _LISTED:
        shown += f" and {len(items) - _LISTED} more"
    return shown


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
