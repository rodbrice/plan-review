"""The .plan-review.yml file: ignoring rules and overriding severities."""

from __future__ import annotations

import pytest

from plan_review.config import Config, ConfigError, parse_config
from plan_review.findings import Finding, Severity

FINDINGS = [
    Finding("R1", Severity.HIGH, "aws_db_instance.a", "Destroyed."),
    Finding("R3", Severity.HIGH, "aws_iam_policy.b", "Policy widened."),
    Finding("R5", Severity.HIGH, "aws_s3_bucket_public_access_block.c", "Removed."),
]


def test_an_empty_file_changes_nothing() -> None:
    for text in ("", "# only a comment\n"):
        config = parse_config(text)
        assert config == Config()
        assert config.apply(FINDINGS) == (FINDINGS, 0)


def test_ignore_drops_every_finding_of_a_rule_and_counts_it() -> None:
    kept, ignored = parse_config("ignore:\n  - R5\n").apply(FINDINGS)
    assert [f.rule_id for f in kept] == ["R1", "R3"]
    assert ignored == 1


def test_severity_override_changes_blocking() -> None:
    config = parse_config("severity:\n  R3: medium\n  R1: low\n")
    kept, ignored = config.apply(FINDINGS)
    assert ignored == 0
    assert [(f.rule_id, f.severity, f.is_blocking) for f in kept] == [
        ("R1", Severity.LOW, False),
        ("R3", Severity.MEDIUM, False),
        ("R5", Severity.HIGH, True),
    ]


def test_severity_can_raise_a_low_finding_to_blocking() -> None:
    low = [Finding("R3", Severity.LOW, "aws_iam_policy.b", "Known only after apply.")]
    (finding,), _ = parse_config("severity: {R3: high}").apply(low)
    assert finding.is_blocking


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("ignore: [R9]", "ignore: unknown rule 'R9'; known rules are R1, R2, R3, R4, R5"),
        ("severity: {R2: critical}", "severity: R2: severity must be one of low, medium, high"),
        ("severity: {R7: low}", "severity: unknown rule 'R7'"),
        ("ignore: [R3]\nseverity: {R3: low}", "R3 cannot be both ignored and given a severity"),
        ("threshold: high", "threshold: Extra inputs are not permitted"),
        ("- R1", "top level: Input should be a valid dictionary"),
        ("ignore: [R1", "not valid YAML"),
    ],
)
def test_unusable_files_are_rejected(text: str, reason: str) -> None:
    with pytest.raises(ConfigError) as raised:
        parse_config(text)
    assert reason in str(raised.value)
