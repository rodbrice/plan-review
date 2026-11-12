#!/usr/bin/env python3
"""Regenerate the sample Terraform plans under fixtures/plans/.

Each directory under fixtures/terraform/ (except _shared/) is one scenario: a minimal
Terraform configuration and, when the scenario needs prior state, a seed.tfstate file.
For every scenario the script copies the shared provider configuration next to the
scenario files in a temporary directory, runs ``terraform init``, ``terraform plan
-refresh=false`` and ``terraform show -json``, removes the timestamp, and writes the
result to fixtures/plans/<scenario>.json.

No AWS account is involved. The shared provider configuration uses placeholder
credentials, skips every check that would need the API, and points each service
endpoint at a closed local port. See fixtures/README.md for the reasoning.

Usage::

    uv run scripts/generate_fixtures.py          # rewrite every fixture
    uv run scripts/generate_fixtures.py --check  # exit 1 if a fixture is stale

Terraform must be on PATH and its version must match TERRAFORM_VERSION, because the
version is recorded in every plan and a different one would change every fixture. The
provider is downloaded once per run, into a temporary plugin cache that lives for the
duration of the run.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TERRAFORM_VERSION = "1.17.2"

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = ROOT / "fixtures" / "terraform"
SHARED_DIR = TERRAFORM_DIR / "_shared"
PLANS_DIR = ROOT / "fixtures" / "plans"

# Fields that change on every run and carry no information a review could use.
VOLATILE_TOP_LEVEL_KEYS = ("timestamp",)


class GenerationError(Exception):
    """A step of the generation failed; the message is ready to print."""


def find_terraform() -> Path:
    found = shutil.which("terraform")
    if found is None:
        raise GenerationError("terraform not found on PATH")
    return Path(found)


def run_terraform(terraform: Path, args: list[str], cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        [str(terraform), *args, "-no-color"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        command = " ".join(["terraform", *args])
        raise GenerationError(f"{command} failed in {cwd}:\n{result.stderr.strip()}")
    return result.stdout


def check_terraform_version(terraform: Path, env: dict[str, str]) -> None:
    output = run_terraform(terraform, ["version", "-json"], ROOT, env)
    found = json.loads(output).get("terraform_version")
    if found != TERRAFORM_VERSION:
        raise GenerationError(
            f"terraform {TERRAFORM_VERSION} is required to regenerate fixtures, found {found}"
        )


def scenario_dirs() -> list[Path]:
    return sorted(
        path
        for path in TERRAFORM_DIR.iterdir()
        if path.is_dir() and not path.name.startswith("_") and (path / "main.tf").is_file()
    )


def stage_scenario(scenario: Path, workdir: Path) -> None:
    """Copy the shared provider files and the scenario files into workdir."""
    for source in SHARED_DIR.iterdir():
        if source.is_file():
            shutil.copy2(source, workdir / source.name)
    for source in scenario.iterdir():
        if not source.is_file():
            continue
        if source.name == "seed.tfstate":
            shutil.copy2(source, workdir / "terraform.tfstate")
        else:
            shutil.copy2(source, workdir / source.name)


def normalize(plan: dict[str, object]) -> dict[str, object]:
    for key in VOLATILE_TOP_LEVEL_KEYS:
        plan.pop(key, None)
    return plan


def generate_plan(terraform: Path, scenario: Path, env: dict[str, str]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"plan-review-{scenario.name}-") as tmp:
        workdir = Path(tmp)
        stage_scenario(scenario, workdir)
        run_terraform(terraform, ["init", "-input=false"], workdir, env)
        run_terraform(
            terraform,
            ["plan", "-input=false", "-refresh=false", "-lock=false", "-out=plan.tfplan"],
            workdir,
            env,
        )
        output = run_terraform(terraform, ["show", "-json", "plan.tfplan"], workdir, env)
    plan = json.loads(output)
    if not isinstance(plan, dict):
        raise GenerationError(f"terraform show -json did not return an object for {scenario}")
    return normalize(plan)


def render(plan: dict[str, object]) -> str:
    return json.dumps(plan, indent=2) + "\n"


def generate_all(check: bool, plugin_cache: Path) -> list[str]:
    """Generate every scenario; return the names whose committed plan is stale."""
    env = {
        **os.environ,
        "TF_IN_AUTOMATION": "1",
        "TF_INPUT": "0",
        "TF_PLUGIN_CACHE_DIR": str(plugin_cache),
    }
    terraform = find_terraform()
    check_terraform_version(terraform, env)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    for scenario in scenario_dirs():
        target = PLANS_DIR / f"{scenario.name}.json"
        fresh = render(generate_plan(terraform, scenario, env))
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if check:
            status = "up to date" if fresh == current else "STALE"
            if fresh != current:
                stale.append(scenario.name)
        else:
            target.write_text(fresh, encoding="utf-8")
            status = "unchanged" if fresh == current else "written"
        print(f"{scenario.name}: {status}")
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if any committed fixture differs from a fresh run",
    )
    args = parser.parse_args(argv)

    try:
        with tempfile.TemporaryDirectory(prefix="plan-review-plugin-cache-") as cache:
            stale = generate_all(args.check, Path(cache))
    except GenerationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if stale:
        print(
            f"stale fixtures: {', '.join(stale)}; run scripts/generate_fixtures.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
