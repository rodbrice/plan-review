"""Typed model of the JSON that ``terraform show -json <planfile>`` produces.

Only the parts the rules read are modelled; every other key is accepted and ignored, so
newer minor versions of the format still load. The reference is Terraform's "JSON
Output Format" documentation, section "Plan Representation".

Two details of the format matter for a reviewer:

- Values that are only known after apply are missing from ``after`` (or ``null``), and
  the matching position in ``after_unknown`` is ``true``. A rule must never read a
  missing or ``null`` value in ``after`` as "the attribute is removed" without checking
  ``after_unknown``.
- Sensitive values are present in clear text in ``before`` and ``after``;
  ``before_sensitive`` and ``after_sensitive`` only mark where they are. The rules and
  reporters of this package never copy an attribute value into their output.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from plan_review.actions import ChangeKind, classify

SUPPORTED_FORMAT_MAJOR = "1"

PathStep = str | int


class PlanError(Exception):
    """The input is not a Terraform plan this tool can read; the message says why."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class Change(_Model):
    """``resource_changes[].change``: the planned transition of one resource instance."""

    actions: tuple[str, ...]
    before: JsonValue = None
    after: JsonValue = None
    after_unknown: JsonValue = None
    before_sensitive: JsonValue = None
    after_sensitive: JsonValue = None
    replace_paths: tuple[tuple[PathStep, ...], ...] = ()

    @field_validator("actions")
    @classmethod
    def _actions_are_known(cls, actions: tuple[str, ...]) -> tuple[str, ...]:
        classify(actions)  # raises ValueError, which pydantic reports as a validation error
        return actions

    @property
    def kind(self) -> ChangeKind:
        return classify(self.actions)

    def is_unknown_after(self, path: Sequence[PathStep]) -> bool:
        """True if the value at ``path`` in ``after`` is only known after apply."""
        return is_marked(self.after_unknown, path)


class ResourceChange(_Model):
    """One entry of ``resource_changes``: a resource instance and its planned change."""

    address: str
    mode: Literal["managed", "data"]
    type: str
    name: str
    change: Change
    action_reason: str | None = None


class Plan(_Model):
    """The top level of the plan JSON."""

    format_version: str
    terraform_version: str | None = None
    resource_changes: tuple[ResourceChange, ...] = Field(default=())

    @field_validator("format_version")
    @classmethod
    def _format_is_supported(cls, version: str) -> str:
        if version.split(".", 1)[0] != SUPPORTED_FORMAT_MAJOR:
            raise ValueError(
                f"format_version {version!r} is not supported; "
                f"this tool reads format {SUPPORTED_FORMAT_MAJOR}.x"
            )
        return version


def is_marked(marks: JsonValue, path: Sequence[PathStep]) -> bool:
    """Follow ``path`` through an ``after_unknown`` or ``*_sensitive`` structure.

    Those structures mirror the shape of ``before``/``after`` but hold ``true`` where a
    value is unknown or sensitive. A ``true`` on the way down marks the whole subtree.
    """
    node = marks
    for step in path:
        if node is True:
            return True
        if isinstance(node, dict) and isinstance(step, str):
            if step not in node:
                return False
            node = node[step]
        elif isinstance(node, list) and isinstance(step, int):
            if not 0 <= step < len(node):
                return False
            node = node[step]
        else:
            return False
    return node is True


def load_plan(data: str | bytes) -> Plan:
    """Parse plan JSON text; raise ``PlanError`` with a one-line reason if it is unusable."""
    try:
        return Plan.model_validate_json(data)
    except ValidationError as error:
        raise PlanError(_describe(error)) from None


def _describe(error: ValidationError) -> str:
    problems = error.errors(include_url=False, include_input=False)
    first = problems[0]
    if first["type"] == "json_invalid":
        message = f"not valid JSON ({first['msg']})"
    else:
        location = ".".join(str(step) for step in first["loc"]) or "top level"
        message = f"{location}: {first['msg']}"
    if len(problems) > 1:
        message += f" (and {len(problems) - 1} more)"
    return message
