"""Rules R1 (stateful resource destroyed) and R2 (stateful resource replaced)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from plan_review.findings import Finding, Severity
from plan_review.model import Plan, ResourceChange, load_plan
from plan_review.report import render_text
from plan_review.rules import evaluate, r1_stateful_destroyed, r2_stateful_replaced
from plan_review.stateful import STATEFUL_TYPES

PLANS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "plans"
SENSITIVE_VALUE = "example-sensitive-value"


def fixture_dict(name: str) -> dict[str, Any]:
    with (PLANS_DIR / f"{name}.json").open(encoding="utf-8") as handle:
        plan: dict[str, Any] = json.load(handle)
    return plan


def fixture_plan(name: str) -> Plan:
    return load_plan(json.dumps(fixture_dict(name)))


def make_change(
    actions: list[str],
    *,
    resource_type: str = "aws_db_instance",
    mode: str = "managed",
    action_reason: str | None = None,
    **change: Any,
) -> ResourceChange:
    return ResourceChange.model_validate(
        {
            "address": f"{resource_type}.example",
            "mode": mode,
            "type": resource_type,
            "name": "example",
            "action_reason": action_reason,
            "change": {"actions": actions, **change},
        }
    )


def found(plan: Plan) -> list[tuple[str, str]]:
    return [(finding.rule_id, finding.address) for finding in evaluate(plan)]


# R1 ---------------------------------------------------------------------------------


def test_r1_flags_each_stateful_destruction() -> None:
    assert found(fixture_plan("destroy_stateful")) == [
        ("R1", "aws_db_instance.orders"),
        ("R1", "aws_efs_file_system.shared"),
        ("R1", "aws_s3_bucket.archive"),
    ]


def test_r1_finding_explains_what_is_lost_and_why() -> None:
    (finding,) = r1_stateful_destroyed(
        make_change(["delete"], action_reason="delete_because_no_resource_config")
    )
    assert finding == Finding(
        rule_id="R1",
        severity=Severity.HIGH,
        address="aws_db_instance.example",
        why=(
            "Destroyed, because it was removed from the configuration. "
            "It holds the databases on the instance."
        ),
    )
    assert finding.is_blocking


def test_r1_ignores_the_destruction_of_a_stateless_resource() -> None:
    # destroy_stateful also deletes aws_iam_policy.archive_reader, which holds no data.
    assert "aws_iam_policy" not in STATEFUL_TYPES
    assert r1_stateful_destroyed(make_change(["delete"], resource_type="aws_iam_policy")) == []


@pytest.mark.parametrize(
    "actions",
    [
        ["no-op"],
        ["create"],
        ["update"],
        ["read"],
        ["forget"],
        ["create", "forget"],
        ["forget", "create"],
        ["delete", "create"],
    ],
)
def test_r1_ignores_stateful_resources_that_are_not_destroyed(actions: list[str]) -> None:
    # forget leaves the object running; a replacement, however the old object is handled,
    # is R2's business.
    assert r1_stateful_destroyed(make_change(actions)) == []


def test_r1_ignores_data_sources() -> None:
    assert r1_stateful_destroyed(make_change(["delete"], mode="data")) == []


# R2 ---------------------------------------------------------------------------------


def test_r2_flags_both_replacement_orderings_of_stateful_resources() -> None:
    assert found(fixture_plan("replace_stateful")) == [
        ("R2", "aws_db_instance.orders"),
        ("R2", "aws_ebs_volume.data"),
        ("R2", "aws_s3_bucket.logs"),
    ]


def test_r2_finding_names_the_order_and_the_attribute_that_forced_it() -> None:
    by_address = {f.address: f for f in evaluate(fixture_plan("replace_stateful"))}
    assert by_address["aws_db_instance.orders"].why == (
        "Replaced (delete, then create), because an attribute that cannot be updated in "
        "place changed. Forced by: engine. It holds the databases on the instance, and the "
        "new object starts empty."
    )
    assert by_address["aws_s3_bucket.logs"].why.startswith("Replaced (create, then delete)")
    assert all(f.severity is Severity.HIGH for f in by_address.values())


@pytest.mark.parametrize(
    ("actions", "order"),
    [(["forget", "create"], "forget, then create"), (["create", "forget"], "create, then forget")],
)
def test_r2_flags_a_replacement_that_keeps_the_old_object(actions: list[str], order: str) -> None:
    # lifecycle { destroy = false } on a resource that must be replaced: the old database is
    # left running outside state and the managed one starts empty.
    plan = fixture_dict("replace_stateful")
    orders = next(
        rc for rc in plan["resource_changes"] if rc["address"] == "aws_db_instance.orders"
    )
    orders["change"]["actions"] = actions
    findings = evaluate(load_plan(json.dumps(plan)))
    assert [(f.rule_id, f.address) for f in findings] == [
        ("R2", "aws_db_instance.orders"),
        ("R2", "aws_ebs_volume.data"),
        ("R2", "aws_s3_bucket.logs"),
    ]
    assert findings[0].severity is Severity.HIGH
    assert findings[0].why == (
        f"Replaced ({order}), because an attribute that cannot be updated in place changed. "
        "Forced by: engine. It holds the databases on the instance; the old object is "
        "removed from Terraform state and left running rather than destroyed, and the "
        "managed object at this address starts empty."
    )


def test_r2_ignores_the_replacement_of_a_stateless_resource() -> None:
    # replace_stateful also replaces the ingress rule, which holds no data.
    change = make_change(["delete", "create"], resource_type="aws_vpc_security_group_ingress_rule")
    assert r2_stateful_replaced(change) == []


@pytest.mark.parametrize("actions", [["no-op"], ["create"], ["update"], ["delete"], ["forget"]])
def test_r2_ignores_stateful_resources_that_are_not_replaced(actions: list[str]) -> None:
    assert r2_stateful_replaced(make_change(actions)) == []


def test_r2_formats_nested_replace_paths() -> None:
    change = make_change(
        ["delete", "create"],
        replace_paths=[["engine"], ["blue_green_update", 0, "enabled"]],
    )
    (finding,) = r2_stateful_replaced(change)
    assert "Forced by: engine, blue_green_update[0].enabled." in finding.why


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (
            "replace_because_tainted",
            "Replaced (delete, then create), because the object is tainted.",
        ),
        ("replace_by_request", "because replacement was requested with -replace."),
        ("replace_some_future_reason", "(Terraform reason: replace_some_future_reason)."),
        (None, "Replaced (delete, then create). It holds"),
    ],
)
def test_r2_states_the_reason_terraform_gives(reason: str | None, expected: str) -> None:
    (finding,) = r2_stateful_replaced(make_change(["delete", "create"], action_reason=reason))
    assert expected in finding.why


# Plans that must produce nothing ------------------------------------------------------


@pytest.mark.parametrize("name", ["no_changes", "create_baseline"])
def test_plans_without_destruction_or_replacement_give_no_findings(name: str) -> None:
    assert evaluate(fixture_plan(name)) == []


def test_an_empty_plan_gives_no_findings() -> None:
    assert evaluate(load_plan('{"format_version": "1.2", "resource_changes": []}')) == []


# Known after apply --------------------------------------------------------------------


def test_replacement_forced_by_a_value_known_only_after_apply_says_so() -> None:
    # A force-new attribute that depends on another resource being created is unknown at
    # plan time, so Terraform plans a replacement without knowing the new value.
    change = make_change(
        ["delete", "create"],
        action_reason="replace_because_cannot_update",
        before={"identifier": "example-orders", "kms_key_id": "key-old"},
        after={"identifier": "example-orders", "kms_key_id": None},
        after_unknown={"kms_key_id": True},
        replace_paths=[["kms_key_id"]],
    )
    (finding,) = r2_stateful_replaced(change)
    assert "Forced by: kms_key_id (known after apply)." in finding.why


def test_creation_with_every_value_known_after_apply_is_not_a_finding() -> None:
    change = make_change(["create"], before=None, after=None, after_unknown=True)
    assert r1_stateful_destroyed(change) == []
    assert r2_stateful_replaced(change) == []


def test_unknown_values_in_the_fixture_do_not_change_the_findings() -> None:
    plan = fixture_plan("replace_stateful")
    database = next(c for c in plan.resource_changes if c.address == "aws_db_instance.orders")
    assert database.change.is_unknown_after(["arn"])
    assert "(known after apply)" not in r2_stateful_replaced(database)[0].why


# Sensitive values ---------------------------------------------------------------------


def with_sensitive_password(name: str, address: str, *, force_replacement: bool) -> Plan:
    """Copy a fixture and give one database a sensitive password in before and after."""
    plan = fixture_dict(name)
    resource = next(c for c in plan["resource_changes"] if c["address"] == address)
    change = resource["change"]
    for side in ("before", "after"):
        if change[side] is not None:
            change[side]["password"] = SENSITIVE_VALUE
            change[f"{side}_sensitive"]["password"] = True
    if force_replacement:
        change["replace_paths"].append(["password"])
    return load_plan(json.dumps(plan))


@pytest.mark.parametrize(
    ("name", "address", "force_replacement"),
    [
        ("destroy_stateful", "aws_db_instance.orders", False),
        ("replace_stateful", "aws_db_instance.orders", False),
        ("replace_stateful", "aws_db_instance.orders", True),
    ],
)
def test_sensitive_values_never_reach_findings_or_report(
    name: str, address: str, force_replacement: bool
) -> None:
    plan = with_sensitive_password(name, address, force_replacement=force_replacement)
    findings = evaluate(plan)
    assert address in [f.address for f in findings]
    assert all(SENSITIVE_VALUE not in f.why for f in findings)
    assert SENSITIVE_VALUE not in render_text(plan, findings)


def test_a_sensitive_attribute_that_forces_replacement_is_named_not_shown() -> None:
    plan = with_sensitive_password(
        "replace_stateful", "aws_db_instance.orders", force_replacement=True
    )
    (database,) = (f for f in evaluate(plan) if f.address == "aws_db_instance.orders")
    assert "Forced by: engine, password." in database.why
