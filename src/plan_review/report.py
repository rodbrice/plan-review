"""The three report formats: plain text, Markdown and JSON.

Every format carries the same information: a summary of the plan, one entry per
finding, the number of blocking findings and the number of findings the configuration
ignored. Text is meant for a terminal, Markdown for a pull request comment or a job
summary, JSON for other programs.
"""

from __future__ import annotations

import json
import textwrap
from collections import Counter
from collections.abc import Sequence

from plan_review.actions import ChangeKind
from plan_review.findings import Finding
from plan_review.model import Plan
from plan_review.rules import RULE_TITLES

WIDTH = 88

# Version of the JSON report layout; it changes only when a key is removed or renamed.
JSON_REPORT_VERSION = 1

# Summary order and wording, with the key the JSON report uses; every replacement kind
# counts as "to replace".
_SUMMARY: tuple[tuple[tuple[ChangeKind, ...], str, str], ...] = (
    ((ChangeKind.CREATE,), "to create", "create"),
    ((ChangeKind.UPDATE,), "to update in place", "update"),
    (tuple(kind for kind in ChangeKind if kind.is_replacement), "to replace", "replace"),
    ((ChangeKind.DELETE,), "to destroy", "delete"),
    ((ChangeKind.READ,), "to read", "read"),
    ((ChangeKind.FORGET,), "to forget", "forget"),
    ((ChangeKind.NO_OP,), "unchanged", "no-op"),
)


def count_changes(plan: Plan) -> dict[str, int]:
    """Number of resource changes per summary key, in summary order."""
    counts = Counter(change.change.kind for change in plan.resource_changes)
    return {key: sum(counts[kind] for kind in kinds) for kinds, _, key in _SUMMARY}


def summarize(plan: Plan) -> str:
    counts = count_changes(plan)
    parts = [f"{counts[key]} {label}" for _, label, key in _SUMMARY if counts[key]]
    line = "Plan: " + (", ".join(parts) if parts else "no resources")
    if plan.terraform_version:
        line += f" (Terraform {plan.terraform_version})"
    return line


def render_text(plan: Plan, findings: Sequence[Finding], *, ignored: int = 0) -> str:
    lines = [summarize(plan), ""]
    for finding in findings:
        lines.append(f"{finding.rule_id} {finding.severity.label:<6} {finding.address}")
        lines.extend(
            textwrap.wrap(
                finding.why,
                width=WIDTH,
                initial_indent="    ",
                subsequent_indent="    ",
                break_on_hyphens=False,
            )
        )
        lines.append("")
    lines.append(_footer(findings, ignored))
    return "\n".join(lines) + "\n"


def render_markdown(plan: Plan, findings: Sequence[Finding], *, ignored: int = 0) -> str:
    lines = ["## plan-review", "", summarize(plan), ""]
    if findings:
        lines += [
            "| Rule | Severity | Resource | Finding |",
            "|------|----------|----------|---------|",
        ]
        for finding in findings:
            rule = f"{finding.rule_id} {RULE_TITLES.get(finding.rule_id, '')}".strip()
            severity = finding.severity.label
            if finding.is_blocking:
                severity = f"**{severity}**"
            cells = [rule, severity, f"`{finding.address}`", finding.why]
            lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
        lines.append("")
    lines.append(_footer(findings, ignored))
    return "\n".join(lines) + "\n"


def render_json(plan: Plan, findings: Sequence[Finding], *, ignored: int = 0) -> str:
    report = {
        "version": JSON_REPORT_VERSION,
        "terraform_version": plan.terraform_version,
        "changes": count_changes(plan),
        "findings": [
            {
                "rule": finding.rule_id,
                "title": RULE_TITLES.get(finding.rule_id),
                "severity": finding.severity.label,
                "blocking": finding.is_blocking,
                "address": finding.address,
                "message": finding.why,
            }
            for finding in findings
        ],
        "blocking": sum(finding.is_blocking for finding in findings),
        "ignored": ignored,
    }
    return json.dumps(report, indent=2) + "\n"


def _cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _footer(findings: Sequence[Finding], ignored: int) -> str:
    if findings:
        noun = "finding" if len(findings) == 1 else "findings"
        blocking = sum(finding.is_blocking for finding in findings)
        line = f"{len(findings)} {noun}, {blocking} blocking."
    else:
        line = "No findings."
    if ignored:
        line += f" {ignored} ignored by configuration."
    return line
