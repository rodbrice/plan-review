"""Plain-text report: a one-line summary of the plan, then one block per finding."""

from __future__ import annotations

import textwrap
from collections import Counter
from collections.abc import Sequence

from plan_review.actions import ChangeKind
from plan_review.findings import Finding
from plan_review.model import Plan

WIDTH = 88

# Summary order and wording; every replacement kind counts as "to replace".
_SUMMARY: tuple[tuple[tuple[ChangeKind, ...], str], ...] = (
    ((ChangeKind.CREATE,), "to create"),
    ((ChangeKind.UPDATE,), "to update in place"),
    (tuple(kind for kind in ChangeKind if kind.is_replacement), "to replace"),
    ((ChangeKind.DELETE,), "to destroy"),
    ((ChangeKind.READ,), "to read"),
    ((ChangeKind.FORGET,), "to forget"),
    ((ChangeKind.NO_OP,), "unchanged"),
)


def summarize(plan: Plan) -> str:
    counts = Counter(change.change.kind for change in plan.resource_changes)
    parts = []
    for kinds, label in _SUMMARY:
        total = sum(counts[kind] for kind in kinds)
        if total:
            parts.append(f"{total} {label}")
    line = "Plan: " + (", ".join(parts) if parts else "no resources")
    if plan.terraform_version:
        line += f" (Terraform {plan.terraform_version})"
    return line


def render_text(plan: Plan, findings: Sequence[Finding]) -> str:
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
    lines.append(_footer(findings))
    return "\n".join(lines) + "\n"


def _footer(findings: Sequence[Finding]) -> str:
    if not findings:
        return "No findings."
    noun = "finding" if len(findings) == 1 else "findings"
    blocking = sum(finding.is_blocking for finding in findings)
    return f"{len(findings)} {noun}, {blocking} blocking."
