"""The optional ``.plan-review.yml`` file: rules to ignore and severities to override.

Example::

    ignore:
      - R5
    severity:
      R3: medium

``ignore`` drops every finding of the listed rules. ``severity`` replaces the severity of
every finding of a rule; since only ``high`` findings are blocking, lowering a rule to
``medium`` keeps it in the report without failing the command. A rule may not be both
ignored and given a severity, and an unknown key, rule ID or severity is an error rather
than a silent no-op.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass, field

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from plan_review.findings import Finding, Severity
from plan_review.rules import RULE_TITLES

CONFIG_FILENAME = ".plan-review.yml"


class ConfigError(Exception):
    """The configuration file cannot be used; the message says why."""


class _File(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ignore: tuple[str, ...] = ()
    severity: dict[str, str] = {}

    @field_validator("ignore")
    @classmethod
    def _known_rules(cls, rules: tuple[str, ...]) -> tuple[str, ...]:
        for rule in rules:
            _check_rule(rule)
        return rules

    @field_validator("severity")
    @classmethod
    def _known_severities(cls, severities: dict[str, str]) -> dict[str, str]:
        labels = [severity.label for severity in Severity]
        for rule, label in severities.items():
            _check_rule(rule)
            if label not in labels:
                raise ValueError(f"{rule}: severity must be one of {', '.join(labels)}")
        return severities

    @model_validator(mode="after")
    def _not_both(self) -> _File:
        both = sorted(set(self.ignore) & set(self.severity))
        if both:
            raise ValueError(f"{', '.join(both)} cannot be both ignored and given a severity")
        return self


@dataclass(frozen=True)
class Config:
    """What the configuration file asks for; the default changes nothing."""

    ignore: frozenset[str] = frozenset()
    severity: dict[str, Severity] = field(default_factory=dict)

    def apply(self, findings: Sequence[Finding]) -> tuple[list[Finding], int]:
        """Return the findings to report, with severities overridden, and how many were ignored."""
        kept = [
            dataclasses.replace(
                finding, severity=self.severity.get(finding.rule_id, finding.severity)
            )
            for finding in findings
            if finding.rule_id not in self.ignore
        ]
        return kept, len(findings) - len(kept)


def parse_config(text: str) -> Config:
    """Parse the YAML text of a configuration file; raise ``ConfigError`` if it is unusable."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"not valid YAML ({_yaml_problem(error)})") from None
    if data is None:
        return Config()
    try:
        parsed = _File.model_validate(data)
    except ValidationError as error:
        raise ConfigError(_describe(error)) from None
    return Config(
        ignore=frozenset(parsed.ignore),
        severity={rule: Severity[label.upper()] for rule, label in parsed.severity.items()},
    )


def _check_rule(rule: str) -> None:
    if rule not in RULE_TITLES:
        raise ValueError(f"unknown rule {rule!r}; known rules are {', '.join(RULE_TITLES)}")


def _yaml_problem(error: yaml.YAMLError) -> str:
    if isinstance(error, yaml.MarkedYAMLError) and error.problem_mark is not None:
        return f"{error.problem}, line {error.problem_mark.line + 1}"
    return "parse error"


def _describe(error: ValidationError) -> str:
    first = error.errors(include_url=False, include_input=False)[0]
    location = ".".join(str(step) for step in first["loc"]) or "top level"
    message = first["msg"].removeprefix("Value error, ")
    return f"{location}: {message}"
