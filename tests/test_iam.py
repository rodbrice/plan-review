"""The IAM policy parser and the wildcard grants rule R3 compares."""

from __future__ import annotations

import json
from typing import Any

import pytest

from plan_review.iam import (
    ALL_ACTIONS_EXCEPT,
    ALL_RESOURCES_EXCEPT,
    Grant,
    PolicyError,
    Statement,
    is_public_principal,
    is_wildcard_action,
    is_wildcard_resource,
    parse_policy,
    wide_grants,
)


def policy(*statements: dict[str, Any]) -> str:
    return json.dumps({"Version": "2012-10-17", "Statement": list(statements)})


def grants(*statements: dict[str, Any]) -> set[Grant]:
    return wide_grants(parse_policy(policy(*statements)))


def test_a_single_statement_object_and_string_fields_are_normalised() -> None:
    text = json.dumps(
        {"Statement": {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:x"}}
    )
    assert parse_policy(text) == [
        Statement(effect="Allow", actions=("s3:GetObject",), resources=("arn:x",))
    ]


def test_principals_and_conditions_are_read() -> None:
    (statement,) = parse_policy(
        policy(
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*", "arn:aws:iam::123456789012:root"]},
                "Action": "s3:GetObject",
                "Resource": "*",
                "Condition": {"Bool": {"aws:SecureTransport": "true"}},
            }
        )
    )
    assert statement.principals == ("*", "arn:aws:iam::123456789012:root")
    assert statement.has_condition
    assert is_public_principal(statement)
    (anyone,) = parse_policy(policy({"Effect": "Allow", "Principal": "*", "Action": "s3:*"}))
    assert is_public_principal(anyone)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("not json", "not valid JSON"),
        ("[]", "not a JSON object"),
        ("{}", "has no Statement"),
        (policy({"Action": "*"}), "Statement[0].Effect must be Allow or Deny"),
        (policy({"Effect": "Allow", "Action": 3}), "Statement[0].Action must be a string"),
        (policy({"Effect": "Allow", "Principal": 3}), "Statement[0].Principal must be"),
        (policy({"Effect": "Allow", "Principal": {"AWS": [1]}}), "Principal values"),
        (json.dumps({"Statement": ["x"]}), "Statement[0] is not a JSON object"),
    ],
)
def test_documents_that_are_not_policies_are_rejected(text: str, reason: str) -> None:
    with pytest.raises(PolicyError, match=reason.replace("[", r"\[").replace("]", r"\]")):
        parse_policy(text)


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("*", True),
        ("s3:*", True),
        ("s3:Get*", True),
        ("s3:?etObject", True),
        ("s3:GetObject", False),
    ],
)
def test_wildcard_actions(action: str, expected: bool) -> None:
    assert is_wildcard_action(action) is expected


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        ("*", True),
        ("arn:aws:s3:::*", True),
        ("arn:aws:dynamodb:eu-central-1:123456789012:*", True),
        ("arn:aws:s3:::example-app-assets/*", False),
        ("arn:aws:dynamodb:eu-central-1:123456789012:table/orders", False),
    ],
)
def test_wildcard_resources(resource: str, expected: bool) -> None:
    assert is_wildcard_resource(resource) is expected


def test_wide_grants_pair_each_action_with_each_resource() -> None:
    assert grants(
        {"Effect": "Allow", "Action": ["S3:*", "s3:GetObject"], "Resource": ["arn:x", "*"]}
    ) == {
        Grant("s3:*", "arn:x"),
        Grant("s3:*", "*"),
        Grant("s3:getobject", "*"),
    }


def test_scoped_statements_and_deny_statements_grant_nothing_wide() -> None:
    assert (
        grants(
            {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::bucket/*"},
            {"Effect": "Deny", "Action": "*", "Resource": "*"},
        )
        == set()
    )


def test_not_action_and_not_resource_in_an_allow_count_as_wildcards() -> None:
    assert grants(
        {"Effect": "Allow", "NotAction": "iam:*", "Resource": "arn:x"},
        {"Effect": "Allow", "Action": "s3:GetObject", "NotResource": "arn:y"},
    ) == {Grant(ALL_ACTIONS_EXCEPT, "arn:x"), Grant("s3:getobject", ALL_RESOURCES_EXCEPT)}


def test_grant_descriptions() -> None:
    assert Grant("s3:*", "*").describe() == "s3:* on *"
    assert Grant(ALL_ACTIONS_EXCEPT, ALL_RESOURCES_EXCEPT).describe() == (
        "every action except those listed in NotAction on "
        "every resource except those listed in NotResource"
    )
