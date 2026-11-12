"""Rules R3 (IAM widened), R4 (ingress open to the world) and R5 (bucket made public)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from plan_review.findings import Finding, Severity
from plan_review.model import ResourceChange, load_plan
from plan_review.rules import evaluate, r3_iam_widened, r4_ingress_open_to_world, r5_bucket_public

PLANS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "plans"


def fixture_findings(name: str) -> dict[str, Finding]:
    plan = load_plan((PLANS_DIR / f"{name}.json").read_bytes())
    return {finding.address: finding for finding in evaluate(plan)}


def change(resource_type: str, actions: list[str], **fields: Any) -> ResourceChange:
    return ResourceChange.model_validate(
        {
            "address": f"{resource_type}.example",
            "mode": fields.pop("mode", "managed"),
            "type": resource_type,
            "name": "example",
            "change": {"actions": actions, **fields},
        }
    )


def policy(action: str | list[str], resource: str | list[str], **extra: Any) -> str:
    statement = {"Effect": "Allow", "Action": action, "Resource": resource, **extra}
    return json.dumps({"Version": "2012-10-17", "Statement": [statement]})


def iam_update(before: str, after: str, **fields: Any) -> ResourceChange:
    return change(
        "aws_iam_policy", ["update"], before={"policy": before}, after={"policy": after}, **fields
    )


# R3 ---------------------------------------------------------------------------------


def test_r3_on_the_fixture_flags_the_widened_and_the_new_policy_only() -> None:
    findings = fixture_findings("iam_widened")
    assert sorted(findings) == ["aws_iam_policy.break_glass", "aws_iam_policy.orders_reader"]
    assert findings["aws_iam_policy.orders_reader"] == Finding(
        "R3",
        Severity.HIGH,
        "aws_iam_policy.orders_reader",
        "Policy widened, now allows: dynamodb:* on *.",
    )
    assert findings["aws_iam_policy.break_glass"].why == "New policy allows: * on *."


def test_r3_on_the_baseline_fixture_flags_the_object_path_wildcard_only() -> None:
    findings = fixture_findings("create_baseline")
    assert sorted(findings) == ["aws_iam_policy.assets_reader"]
    assert findings["aws_iam_policy.assets_reader"].why == (
        "New policy allows: s3:getobject on arn:aws:s3:::example-app-assets/*, "
        "s3:listbucket on arn:aws:s3:::example-app-assets/*."
    )


@pytest.mark.parametrize(
    "widened", ["arn:aws:dynamodb:*:*:table/orders", "arn:aws:iam::123456789012:role/*"]
)
def test_r3_flags_a_wildcard_in_any_segment_of_the_resource_arn(widened: str) -> None:
    scoped = policy("dynamodb:GetItem", "arn:aws:dynamodb:eu-central-1:123456789012:table/orders")
    (finding,) = r3_iam_widened(iam_update(scoped, policy("dynamodb:GetItem", widened)))
    assert finding == Finding(
        "R3",
        Severity.HIGH,
        "aws_iam_policy.example",
        f"Policy widened, now allows: dynamodb:getitem on {widened}.",
    )


def test_r3_ignores_a_narrowed_policy() -> None:
    # The fixture's deployer loses one action and keeps its scoped resource.
    assert "aws_iam_policy.deployer" not in fixture_findings("iam_widened")
    before = policy(["s3:PutObject", "s3:DeleteObject"], "arn:aws:s3:::bucket/*")
    assert r3_iam_widened(iam_update(before, policy("s3:PutObject", "arn:aws:s3:::bucket/*"))) == []


def test_r3_ignores_a_wildcard_that_was_already_granted() -> None:
    assert r3_iam_widened(iam_update(policy("s3:*", "*"), policy(["S3:*"], "*"))) == []


def test_r3_flags_a_wildcard_resource_combined_with_an_existing_wildcard_action() -> None:
    before = json.dumps(
        {
            "Statement": [
                {"Effect": "Allow", "Action": "s3:*", "Resource": "arn:aws:s3:::bucket"},
                {"Effect": "Allow", "Action": "ec2:DescribeInstances", "Resource": "*"},
            ]
        }
    )
    (finding,) = r3_iam_widened(iam_update(before, policy("s3:*", "*")))
    assert finding.why == "Policy widened, now allows: s3:* on *."


@pytest.mark.parametrize(
    "resource_type",
    ["aws_iam_policy", "aws_iam_role_policy", "aws_iam_user_policy", "aws_iam_group_policy"],
)
def test_r3_reads_every_identity_policy_type(resource_type: str) -> None:
    created = change(resource_type, ["create"], before=None, after={"policy": policy("*", "*")})
    assert [f.rule_id for f in r3_iam_widened(created)] == ["R3"]


def test_r3_ignores_other_types_deletions_and_data_sources() -> None:
    wide = {"policy": policy("*", "*")}
    assert r3_iam_widened(change("aws_s3_bucket_policy", ["create"], after=wide)) == []
    assert r3_iam_widened(change("aws_iam_policy", ["delete"], before=wide, after=None)) == []
    assert r3_iam_widened(change("aws_iam_policy", ["read"], after=wide, mode="data")) == []


def test_r3_lists_at_most_five_grants() -> None:
    actions = [f"service{i}:*" for i in range(7)]
    (finding,) = r3_iam_widened(
        iam_update(policy("s3:GetObject", "arn:x"), policy(actions, "arn:x"))
    )
    assert finding.why.endswith("service4:* on arn:x and 2 more.")


def test_r3_ignores_a_policy_known_only_after_apply_or_unreadable() -> None:
    unknown = change(
        "aws_iam_policy", ["create"], before=None, after={}, after_unknown={"policy": True}
    )
    assert r3_iam_widened(unknown) == []
    assert r3_iam_widened(iam_update(policy("s3:GetObject", "arn:x"), "{}")) == []


def test_r3_does_not_quote_a_sensitive_policy() -> None:
    sensitive = iam_update(
        policy("s3:GetObject", "arn:x"),
        policy("s3:*", "arn:x"),
        after_sensitive={"policy": True},
    )
    (finding,) = r3_iam_widened(sensitive)
    assert "s3:*" not in finding.why
    assert "1 new wildcard grant(s); the document is sensitive and not shown" in finding.why


# R4 ---------------------------------------------------------------------------------


def test_r4_on_the_fixture_flags_the_two_world_open_rules_only() -> None:
    findings = {a: f for a, f in fixture_findings("exposure").items() if f.rule_id == "R4"}
    assert sorted(findings) == [
        "aws_vpc_security_group_ingress_rule.ssh",
        "aws_vpc_security_group_ingress_rule.ssh_ipv6",
    ]
    assert findings["aws_vpc_security_group_ingress_rule.ssh"].why == (
        "Ingress newly open to the internet: port 22/tcp from 0.0.0.0/0."
    )
    assert findings["aws_vpc_security_group_ingress_rule.ssh_ipv6"].severity is Severity.HIGH


def ingress_rule(before: dict[str, Any] | None, after: dict[str, Any]) -> ResourceChange:
    actions = ["create"] if before is None else ["update"]
    base = {"from_port": 22, "to_port": 22, "ip_protocol": "tcp"}
    return change(
        "aws_vpc_security_group_ingress_rule",
        actions,
        before=None if before is None else {**base, **before},
        after={**base, **after},
    )


def test_r4_ignores_a_private_rule_and_a_rule_that_was_already_open() -> None:
    # The fixture's https_internal moves between private ranges.
    assert "aws_vpc_security_group_ingress_rule.https_internal" not in fixture_findings("exposure")
    assert r4_ingress_open_to_world(ingress_rule(None, {"cidr_ipv4": "10.0.0.0/8"})) == []
    world = {"cidr_ipv4": "0.0.0.0/0"}
    assert r4_ingress_open_to_world(ingress_rule(world, {**world, "description": "ssh"})) == []


def test_r4_ignores_a_world_open_rule_being_deleted() -> None:
    deleted = change(
        "aws_vpc_security_group_ingress_rule",
        ["delete"],
        before={"cidr_ipv4": "0.0.0.0/0", "from_port": 22, "to_port": 22, "ip_protocol": "tcp"},
        after=None,
    )
    assert r4_ingress_open_to_world(deleted) == []


def test_r4_reads_security_group_rule_ingress_but_not_egress() -> None:
    values = {
        "type": "ingress",
        "cidr_blocks": ["0.0.0.0/0"],
        "ipv6_cidr_blocks": ["::/0"],
        "from_port": 3000,
        "to_port": 3100,
        "protocol": "tcp",
    }
    (finding,) = r4_ingress_open_to_world(
        change("aws_security_group_rule", ["create"], after=values)
    )
    assert finding.why == (
        "Ingress newly open to the internet: ports 3000-3100/tcp from 0.0.0.0/0, "
        "ports 3000-3100/tcp from ::/0."
    )
    egress = {**values, "type": "egress"}
    assert (
        r4_ingress_open_to_world(change("aws_security_group_rule", ["create"], after=egress)) == []
    )


def test_r4_reads_inline_ingress_blocks_and_compares_them_with_before() -> None:
    def block(port: int, protocol: str = "tcp") -> dict[str, Any]:
        return {
            "cidr_blocks": ["0.0.0.0/0"],
            "from_port": port,
            "to_port": port,
            "protocol": protocol,
        }

    before = {"ingress": [block(443)]}
    after = {"ingress": [block(443), block(0, "-1")]}
    group = change("aws_security_group", ["update"], before=before, after=after)
    (finding,) = r4_ingress_open_to_world(group)
    assert finding.why == "Ingress newly open to the internet: all traffic from 0.0.0.0/0."


def test_r4_names_the_cidr_but_not_sensitive_ports() -> None:
    rule = ingress_rule(None, {"cidr_ipv4": "0.0.0.0/0"})
    sensitive = rule.model_copy(
        update={"change": rule.change.model_copy(update={"after_sensitive": {"from_port": True}})}
    )
    (finding,) = r4_ingress_open_to_world(sensitive)
    assert finding.why == "Ingress newly open to the internet: 0.0.0.0/0."


# R5 ---------------------------------------------------------------------------------

ALL_ON = {
    "block_public_acls": True,
    "block_public_policy": True,
    "ignore_public_acls": True,
    "restrict_public_buckets": True,
}


def test_r5_on_the_fixture_flags_the_relaxed_and_the_removed_block() -> None:
    findings = {a: f for a, f in fixture_findings("exposure").items() if f.rule_id == "R5"}
    assert sorted(findings) == [
        "aws_s3_bucket_public_access_block.assets",
        "aws_s3_bucket_public_access_block.reports",
    ]
    assert findings["aws_s3_bucket_public_access_block.assets"].why == (
        "Public access protection turned off for the bucket: block_public_acls, "
        "block_public_policy, ignore_public_acls, restrict_public_buckets."
    )
    assert findings["aws_s3_bucket_public_access_block.reports"].why.startswith(
        "Public access block removed; the bucket no longer has block_public_acls"
    )
    # The buckets themselves are unchanged and give nothing.
    assert "aws_s3_bucket.assets" not in fixture_findings("exposure")


def test_r5_names_only_the_settings_turned_off_and_reads_the_account_block() -> None:
    after = {**ALL_ON, "restrict_public_buckets": False}
    block = change("aws_s3_account_public_access_block", ["update"], before=ALL_ON, after=after)
    (finding,) = r5_bucket_public(block)
    assert (
        finding.why
        == "Public access protection turned off for the account: restrict_public_buckets."
    )


@pytest.mark.parametrize(
    ("actions", "before", "after"),
    [
        (["create"], None, {**ALL_ON, "block_public_acls": False}),
        (
            ["update"],
            {**ALL_ON, "block_public_acls": False},
            {**ALL_ON, "block_public_acls": False},
        ),
        (["update"], {**ALL_ON, "block_public_acls": False}, ALL_ON),
        (["delete"], dict.fromkeys(ALL_ON, False), None),
        (["forget"], ALL_ON, None),
    ],
)
def test_r5_ignores_blocks_that_lose_no_protection(
    actions: list[str], before: dict[str, Any] | None, after: dict[str, Any] | None
) -> None:
    block = change("aws_s3_bucket_public_access_block", actions, before=before, after=after)
    assert r5_bucket_public(block) == []


def test_r5_ignores_a_setting_known_only_after_apply() -> None:
    after = {key: value for key, value in ALL_ON.items() if key != "block_public_acls"}
    block = change(
        "aws_s3_bucket_public_access_block",
        ["update"],
        before=ALL_ON,
        after=after,
        after_unknown={"block_public_acls": True},
    )
    assert r5_bucket_public(block) == []


@pytest.mark.parametrize("resource_type", ["aws_s3_bucket_acl", "aws_s3_bucket"])
def test_r5_flags_a_public_canned_acl(resource_type: str) -> None:
    acl = change(resource_type, ["update"], before={"acl": "private"}, after={"acl": "public-read"})
    (finding,) = r5_bucket_public(acl)
    assert finding.why == "Bucket ACL set to public-read: anyone can list the bucket."


def test_r5_ignores_a_private_acl_and_one_that_was_already_public() -> None:
    private = change("aws_s3_bucket_acl", ["create"], before=None, after={"acl": "private"})
    assert r5_bucket_public(private) == []
    same = {"acl": "public-read"}
    assert r5_bucket_public(change("aws_s3_bucket_acl", ["update"], before=same, after=same)) == []


def bucket_policy(before: str | None, after: str, **fields: Any) -> ResourceChange:
    return change(
        "aws_s3_bucket_policy",
        ["create"] if before is None else ["update"],
        before=None if before is None else {"policy": before},
        after={"policy": after},
        **fields,
    )


def test_r5_flags_a_bucket_policy_that_allows_anyone() -> None:
    public = policy("s3:GetObject", "arn:aws:s3:::example-app-assets/*", Principal="*")
    (finding,) = r5_bucket_public(bucket_policy(None, public))
    assert finding.why == (
        "Bucket policy now allows anyone (Principal *) without a condition: "
        "s3:getobject on arn:aws:s3:::example-app-assets/*."
    )


def test_r5_describes_not_action_in_a_bucket_policy_as_r3_does() -> None:
    statement = {
        "Effect": "Allow",
        "Principal": "*",
        "NotAction": "s3:DeleteObject",
        "Resource": "arn:aws:s3:::example-app-assets/*",
    }
    text = json.dumps({"Version": "2012-10-17", "Statement": [statement]})
    (finding,) = r5_bucket_public(bucket_policy(None, text))
    assert finding.why == (
        "Bucket policy now allows anyone (Principal *) without a condition: every action "
        "except those listed in NotAction on arn:aws:s3:::example-app-assets/*."
    )


def test_r5_ignores_bucket_policies_that_are_conditional_scoped_or_unchanged() -> None:
    conditional = policy(
        "s3:GetObject",
        "arn:x",
        Principal="*",
        Condition={"StringEquals": {"aws:SourceVpce": "vpce-0123456789abcdef0"}},
    )
    scoped = policy("s3:GetObject", "arn:x", Principal={"AWS": "arn:aws:iam::123456789012:root"})
    public = policy("s3:GetObject", "arn:x", Principal="*")
    assert r5_bucket_public(bucket_policy(None, conditional)) == []
    assert r5_bucket_public(bucket_policy(None, scoped)) == []
    assert r5_bucket_public(bucket_policy(public, public)) == []


def test_r5_does_not_quote_a_sensitive_bucket_policy() -> None:
    public = policy("s3:GetObject", "arn:x", Principal="*")
    (finding,) = r5_bucket_public(bucket_policy(None, public, after_sensitive={"policy": True}))
    assert "arn:x" not in finding.why
    assert "1 action(s); the document is sensitive and not shown" in finding.why
