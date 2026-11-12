"""The sample plans load as Terraform plan JSON and have the shapes the rules will rely on."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

PLANS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "plans"

# Scenario name -> the set of action lists the plan must contain. Each list is one of
# the shapes Terraform emits in resource_changes[].change.actions.
EXPECTED_ACTIONS: dict[str, set[tuple[str, ...]]] = {
    "create_baseline": {("create",)},
    "no_changes": {("no-op",)},
    "destroy_stateful": {("delete",), ("no-op",)},
    "replace_stateful": {("delete", "create"), ("create", "delete")},
    "iam_widened": {("update",), ("create",)},
    "exposure": {("update",), ("create",), ("delete",), ("no-op",)},
}

KNOWN_ACTIONS = {
    ("no-op",),
    ("create",),
    ("read",),
    ("update",),
    ("delete",),
    ("delete", "create"),
    ("create", "delete"),
    ("forget",),
    ("create", "forget"),
    ("forget", "create"),
}


def load(name: str) -> dict[str, Any]:
    with (PLANS_DIR / f"{name}.json").open(encoding="utf-8") as handle:
        plan: dict[str, Any] = json.load(handle)
    return plan


def actions_of(plan: dict[str, Any]) -> set[tuple[str, ...]]:
    return {tuple(change["change"]["actions"]) for change in plan["resource_changes"]}


def test_every_expected_fixture_exists_and_nothing_else() -> None:
    present = {path.stem for path in PLANS_DIR.glob("*.json")}
    assert present == set(EXPECTED_ACTIONS)


@pytest.mark.parametrize("name", sorted(EXPECTED_ACTIONS))
def test_fixture_is_a_terraform_plan(name: str) -> None:
    plan = load(name)
    assert plan["format_version"].startswith("1.")
    assert plan["terraform_version"]
    assert isinstance(plan["resource_changes"], list)
    assert plan["resource_changes"], "a fixture with no resources would exercise nothing"
    for change in plan["resource_changes"]:
        assert change["address"]
        assert change["type"].startswith("aws_")
        assert change["mode"] == "managed"
        assert tuple(change["change"]["actions"]) in KNOWN_ACTIONS


@pytest.mark.parametrize("name", sorted(EXPECTED_ACTIONS))
def test_fixture_has_the_documented_change_shapes(name: str) -> None:
    assert actions_of(load(name)) == EXPECTED_ACTIONS[name]


@pytest.mark.parametrize("name", sorted(EXPECTED_ACTIONS))
def test_fixture_is_normalized(name: str) -> None:
    plan = load(name)
    assert "timestamp" not in plan, "generate_fixtures.py removes the timestamp"
    assert plan["errored"] is False
    assert plan["complete"] is True


def test_replacement_fixture_carries_both_orderings() -> None:
    by_address = {
        change["address"]: tuple(change["change"]["actions"])
        for change in load("replace_stateful")["resource_changes"]
    }
    assert by_address["aws_db_instance.orders"] == ("delete", "create")
    assert by_address["aws_s3_bucket.logs"] == ("create", "delete")


def test_before_and_after_are_present_on_updates() -> None:
    for change in load("iam_widened")["resource_changes"]:
        if change["change"]["actions"] == ["update"]:
            assert change["change"]["before"]["policy"] != change["change"]["after"]["policy"]
