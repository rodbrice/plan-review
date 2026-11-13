"""Command-line entry point: ``plan-review [--format FORMAT] PLAN_JSON``.

The command reads ``.plan-review.yml`` from the current directory when that file exists.

Exit status:

- 0: the plan was read and no finding is blocking;
- 1: at least one blocking finding;
- 2: the input could not be read or is not a usable Terraform plan, the configuration
  file cannot be used, or the arguments are wrong.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from enum import IntEnum
from pathlib import Path
from typing import Protocol

from plan_review.config import CONFIG_FILENAME, Config, ConfigError, parse_config
from plan_review.findings import Finding
from plan_review.model import Plan, PlanError, load_plan
from plan_review.report import render_json, render_markdown, render_text
from plan_review.rules import evaluate


class Renderer(Protocol):
    def __call__(self, plan: Plan, findings: Sequence[Finding], *, ignored: int = 0) -> str: ...


FORMATS: dict[str, Renderer] = {
    "text": render_text,
    "markdown": render_markdown,
    "json": render_json,
}


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
        help="path to the plan JSON written by `terraform show -json PLANFILE`",
    )
    parser.add_argument(
        "--format",
        choices=sorted(FORMATS),
        default="text",
        help="report format (default: text)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = _load_config()
    except (OSError, ConfigError) as error:
        print(
            f"plan-review: error: {_message(CONFIG_FILENAME, error, 'configuration')}",
            file=sys.stderr,
        )
        return ExitCode.INVALID_INPUT
    try:
        plan = load_plan(Path(args.plan).read_bytes())
    except (OSError, PlanError) as error:
        print(
            f"plan-review: error: {_message(args.plan, error, 'Terraform plan')}", file=sys.stderr
        )
        return ExitCode.INVALID_INPUT

    findings, ignored = config.apply(evaluate(plan))
    sys.stdout.write(FORMATS[args.format](plan, findings, ignored=ignored))
    if any(finding.is_blocking for finding in findings):
        return ExitCode.BLOCKING
    return ExitCode.OK


def _load_config() -> Config:
    path = Path(CONFIG_FILENAME)
    if not path.is_file():
        return Config()
    return parse_config(path.read_text(encoding="utf-8"))


def _message(path: str, error: Exception, what: str) -> str:
    if isinstance(error, OSError):
        reason = error.strerror or str(error)
        return f"cannot read {path}: {reason}"
    return f"{path} is not a usable {what}: {error}"
