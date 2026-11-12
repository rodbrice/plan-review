"""Parsing IAM policy documents and finding the wildcard grants they contain.

Terraform stores a policy document as a JSON string (``aws_iam_policy.policy``, for
example). ``parse_policy`` turns that string into a list of ``Statement`` values, with
the shorthand forms of the policy language normalised:

- ``Statement`` may be a single object or a list of objects;
- ``Action``, ``NotAction``, ``Resource`` and ``NotResource`` may be a string or a list
  of strings;
- ``Principal`` may be the string ``"*"`` or an object such as ``{"AWS": [...]}``.

``wide_grants`` then lists what rule R3 compares between ``before`` and ``after``: each
pair of an action and a resource that an ``Allow`` statement grants, where at least one
side is a wildcard. Comparing pairs rather than separate lists of actions and resources
catches a statement that combines a wildcard action already granted on one resource
with a wildcard resource already used by another action.

What counts as a wildcard:

- an action containing ``*`` or ``?`` (``*``, ``s3:*``, ``s3:Get*``);
- the resource ``*``, or an ARN whose resource part is ``*`` (``arn:aws:s3:::*``);
- ``NotAction`` or ``NotResource`` in an ``Allow`` statement, which grants everything
  except what is listed.

Actions are compared without regard to case, as IAM does. ``Deny`` statements never
widen anything, so they are skipped. Conditions are not evaluated: a statement with a
condition is treated like one without.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# Stand-ins used in a Grant when the statement uses NotAction or NotResource.
ALL_ACTIONS_EXCEPT = "NotAction"
ALL_RESOURCES_EXCEPT = "NotResource"


class PolicyError(ValueError):
    """The text is not an IAM policy document; the message says why."""


@dataclass(frozen=True)
class Statement:
    """One statement of a policy document, with every list field normalised to a tuple."""

    effect: str
    actions: tuple[str, ...] = ()
    not_actions: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    not_resources: tuple[str, ...] = ()
    principals: tuple[str, ...] = ()
    has_condition: bool = False

    @property
    def allows(self) -> bool:
        return self.effect == "Allow"


@dataclass(frozen=True, order=True)
class Grant:
    """An action granted on a resource by an ``Allow`` statement."""

    action: str
    resource: str

    def describe(self) -> str:
        action = (
            "every action except those listed in NotAction"
            if self.action == ALL_ACTIONS_EXCEPT
            else self.action
        )
        resource = (
            "every resource except those listed in NotResource"
            if self.resource == ALL_RESOURCES_EXCEPT
            else self.resource
        )
        return f"{action} on {resource}"


def parse_policy(text: str) -> list[Statement]:
    """Parse a policy document; raise ``PolicyError`` if it is not one."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise PolicyError(f"not valid JSON ({error.msg})") from None
    if not isinstance(document, dict):
        raise PolicyError("the document is not a JSON object")
    raw = document.get("Statement")
    if raw is None:
        raise PolicyError("the document has no Statement")
    items = raw if isinstance(raw, list) else [raw]
    return [_statement(item, index) for index, item in enumerate(items)]


def wide_grants(statements: list[Statement]) -> set[Grant]:
    """Every (action, resource) pair allowed where the action or the resource is a wildcard."""
    grants: set[Grant] = set()
    for statement in statements:
        if not statement.allows:
            continue
        actions = statement.actions or ((ALL_ACTIONS_EXCEPT,) if statement.not_actions else ())
        resources = statement.resources or (
            (ALL_RESOURCES_EXCEPT,) if statement.not_resources else ()
        )
        for action in actions:
            for resource in resources:
                if is_wildcard_action(action) or is_wildcard_resource(resource):
                    grants.add(Grant(_normalise_action(action), resource))
    return grants


def is_wildcard_action(action: str) -> bool:
    return action == ALL_ACTIONS_EXCEPT or "*" in action or "?" in action


def is_wildcard_resource(resource: str) -> bool:
    if resource in ("*", ALL_RESOURCES_EXCEPT):
        return True
    parts = resource.split(":", 5)
    return len(parts) == 6 and parts[0] == "arn" and parts[5] == "*"


def is_public_principal(statement: Statement) -> bool:
    """The statement applies to anyone: ``"*"`` or ``{"AWS": "*"}``."""
    return "*" in statement.principals


def _normalise_action(action: str) -> str:
    return action if action == ALL_ACTIONS_EXCEPT else action.lower()


def _statement(item: Any, index: int) -> Statement:
    if not isinstance(item, dict):
        raise PolicyError(f"Statement[{index}] is not a JSON object")
    effect = item.get("Effect")
    if effect not in ("Allow", "Deny"):
        raise PolicyError(f"Statement[{index}].Effect must be Allow or Deny")
    return Statement(
        effect=effect,
        actions=_strings(item, "Action", index),
        not_actions=_strings(item, "NotAction", index),
        resources=_strings(item, "Resource", index),
        not_resources=_strings(item, "NotResource", index),
        principals=_principals(item.get("Principal"), index),
        has_condition=bool(item.get("Condition")),
    )


def _strings(item: dict[str, Any], key: str, index: int) -> tuple[str, ...]:
    value = item.get(key)
    if value is None:
        return ()
    values = value if isinstance(value, list) else [value]
    if not all(isinstance(entry, str) for entry in values):
        raise PolicyError(f"Statement[{index}].{key} must be a string or a list of strings")
    return tuple(values)


def _principals(value: Any, index: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        found: list[str] = []
        for entries in value.values():
            listed = entries if isinstance(entries, list) else [entries]
            if not all(isinstance(entry, str) for entry in listed):
                raise PolicyError(f"Statement[{index}].Principal values must be strings")
            found.extend(listed)
        return tuple(found)
    raise PolicyError(f"Statement[{index}].Principal must be a string or an object")
