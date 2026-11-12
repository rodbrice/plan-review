"""Command-line entry point: ``plan-review PLAN_JSON``.

Exit status:

- 0: the plan was read and no finding is blocking;
- 1: at least one blocking finding;
- 2: the input could not be read or is not a usable Terraform plan, or the arguments
  are wrong.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from enum import IntEnum
from pathlib import Path

from plan_review import __version__
from plan_review.model import PlanError, load_plan
from plan_review.report import render_text
from plan_review.rules import evaluate


class ExitCode(IntEnum):
    OK = 0
    BLOCKING = 1
    INVALID_INPUT = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plan-review",
        description=(
            "Review a Terraform plan before apply. Reads the output of "
            "`terraform show -json PLANFILE` and reports risky changes."
        ),
    )
    parser.add_argument(
        "plan",
        metavar="PLAN_JSON",
        help="path to the plan JSON, or - to read it from standard input",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = _read(args.plan)
        plan = load_plan(data)
    except (OSError, PlanError) as error:
        print(f"plan-review: error: {_message(args.plan, error)}", file=sys.stderr)
        return ExitCode.INVALID_INPUT

    findings = evaluate(plan)
    sys.stdout.write(render_text(plan, findings))
    if any(finding.is_blocking for finding in findings):
        return ExitCode.BLOCKING
    return ExitCode.OK


def _read(source: str) -> bytes:
    if source == "-":
        return sys.stdin.buffer.read()
    return Path(source).read_bytes()


def _message(source: str, error: OSError | PlanError) -> str:
    name = "standard input" if source == "-" else source
    if isinstance(error, OSError):
        reason = error.strerror or str(error)
        return f"cannot read {name}: {reason}"
    return f"{name} is not a usable Terraform plan: {error}"
