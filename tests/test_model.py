"""Loading plan JSON into the typed model, including unknown and sensitive values."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from plan_review.actions import ChangeKind
from plan_review.model import Plan, PlanError, is_marked, load_plan

PLANS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "plans"
FIXTURES = sorted(path.stem for path in PLANS_DIR.glob("*.json"))


def load_fixture(name: str) -> Plan:
    return load_plan((PLANS_DIR / f"{name}.json").read_bytes())


def by_address(plan: Plan) -> dict[str, Any]:
    return {change.address: change for change in plan.resource_changes}


@pytest.mark.parametrize("name", FIXTURES)
def test_every_fixture_loads(name: str) -> None:
    plan = load_fixture(name)
    assert plan.format_version.startswith("1.")
    assert plan.terraform_version == "1.17.2"
    assert plan.resource_changes


def test_replacement_orderings_are_classified_from_the_plan() -> None:
    changes = by_address(load_fixture("replace_stateful"))
    assert changes["aws_db_instance.orders"].change.kind is ChangeKind.REPLACE_DELETE_FIRST
    assert changes["aws_s3_bucket.logs"].change.kind is ChangeKind.REPLACE_CREATE_FIRST
    assert changes["aws_db_instance.orders"].change.replace_paths == (("engine",),)
    assert changes["aws_db_instance.orders"].action_reason == "replace_because_cannot_update"


def test_known_after_apply_values_are_missing_from_after_and_marked_in_after_unknown() -> None:
    database = by_address(load_fixture("replace_stateful"))["aws_db_instance.orders"].change
    assert isinstance(database.after, dict)
    assert "arn" not in database.after
    assert database.is_unknown_after(["arn"])
    assert database.after["engine"] == "mysql"
    assert not database.is_unknown_after(["engine"])


def test_deleted_resources_have_no_after() -> None:
    database = by_address(load_fixture("destroy_stateful"))["aws_db_instance.orders"].change
    assert database.kind is ChangeKind.DELETE
    assert database.after is None
    assert isinstance(database.before, dict)


def test_sensitive_marks_are_loaded() -> None:
    database = by_address(load_fixture("destroy_stateful"))["aws_db_instance.orders"].change
    assert is_marked(database.before_sensitive, ["password"])
    assert not is_marked(database.before_sensitive, ["engine"])


@pytest.mark.parametrize(
    ("marks", "path", "expected"),
    [
        (True, ["anything", 0, "below"], True),
        ({"tags": True}, ["tags", "Name"], True),
        ({"rule": [{"cidr": False}, {"cidr": True}]}, ["rule", 1, "cidr"], True),
        ({"rule": [{"cidr": False}, {"cidr": True}]}, ["rule", 0, "cidr"], False),
        ({"rule": [{"cidr": True}]}, ["rule", 5, "cidr"], False),
        ({"name": True}, ["other"], False),
        ({"name": {}}, ["name"], False),
        (None, ["name"], False),
        (False, [], False),
    ],
)
def test_is_marked_follows_the_mirrored_structure(
    marks: Any, path: list[str | int], expected: bool
) -> None:
    assert is_marked(marks, path) is expected


def test_a_plan_without_resource_changes_is_empty() -> None:
    plan = load_plan('{"format_version": "1.2"}')
    assert plan.resource_changes == ()
    assert plan.terraform_version is None


def minimal_plan(**resource_overrides: Any) -> str:
    resource: dict[str, Any] = {
        "address": "aws_s3_bucket.example",
        "mode": "managed",
        "type": "aws_s3_bucket",
        "name": "example",
        "change": {"actions": ["create"], "before": None, "after": {}},
    }
    resource.update(resource_overrides)
    return json.dumps({"format_version": "1.2", "resource_changes": [resource]})


def test_minimal_plan_is_valid() -> None:
    assert load_plan(minimal_plan()).resource_changes[0].change.kind is ChangeKind.CREATE


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "not valid JSON"),
        ("{not json", "not valid JSON"),
        ("[]", "top level"),
        ('{"resource_changes": []}', "format_version: Field required"),
        ('{"format_version": "2.0"}', "format_version '2.0' is not supported"),
        (minimal_plan(change={"actions": ["update", "delete"]}), "unsupported action list"),
        (minimal_plan(change={}), "resource_changes.0.change.actions: Field required"),
        (minimal_plan(mode="unexpected"), "resource_changes.0.mode"),
    ],
)
def test_unusable_input_raises_plan_error(text: str, message: str) -> None:
    with pytest.raises(PlanError, match=message):
        load_plan(text)


def test_error_messages_do_not_echo_input_values() -> None:
    sensitive = "example-sensitive-value"
    with pytest.raises(PlanError) as raised:
        load_plan(minimal_plan(mode=sensitive, address=12345))
    assert sensitive not in str(raised.value)
    assert "and 1 more" in str(raised.value)
