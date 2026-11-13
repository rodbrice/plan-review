"""The command line on the sample plans: printed report and exit status."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plan_review.cli import ExitCode, main

PLANS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "plans"

EXPECTED_EXIT: dict[str, ExitCode] = {
    "create_baseline": ExitCode.BLOCKING,
    "no_changes": ExitCode.OK,
    "iam_widened": ExitCode.BLOCKING,
    "exposure": ExitCode.BLOCKING,
    "destroy_stateful": ExitCode.BLOCKING,
    "replace_stateful": ExitCode.BLOCKING,
}


def plan_path(name: str) -> str:
    return str(PLANS_DIR / f"{name}.json")


@pytest.mark.parametrize("name", sorted(EXPECTED_EXIT))
def test_exit_status_on_each_fixture(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([plan_path(name)]) == EXPECTED_EXIT[name]
    assert capsys.readouterr().err == ""


def test_no_changes_prints_the_summary_and_no_findings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([plan_path("no_changes")]) == ExitCode.OK
    assert capsys.readouterr().out == ("Plan: 3 unchanged (Terraform 1.17.2)\n\nNo findings.\n")


def test_destroy_stateful_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([plan_path("destroy_stateful")]) == ExitCode.BLOCKING
    assert capsys.readouterr().out == (
        "Plan: 4 to destroy, 1 unchanged (Terraform 1.17.2)\n"
        "\n"
        "R1 high   aws_db_instance.orders\n"
        "    Destroyed, because it was removed from the configuration. It holds the databases on\n"
        "    the instance.\n"
        "\n"
        "R1 high   aws_efs_file_system.shared\n"
        "    Destroyed, because it was removed from the configuration. It holds the files in the\n"
        "    file system.\n"
        "\n"
        "R1 high   aws_s3_bucket.archive\n"
        "    Destroyed, because it was removed from the configuration. It holds the objects in\n"
        "    the bucket.\n"
        "\n"
        "3 findings, 3 blocking.\n"
    )


def test_replace_stateful_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([plan_path("replace_stateful")]) == ExitCode.BLOCKING
    assert capsys.readouterr().out == (
        "Plan: 4 to replace (Terraform 1.17.2)\n"
        "\n"
        "R2 high   aws_db_instance.orders\n"
        "    Replaced (delete, then create), because an attribute that cannot be updated in place\n"
        "    changed. Forced by: engine. It holds the databases on the instance, and the new\n"
        "    object starts empty.\n"
        "\n"
        "R2 high   aws_ebs_volume.data\n"
        "    Replaced (delete, then create), because an attribute that cannot be updated in place\n"
        "    changed. Forced by: availability_zone. It holds the data on the volume, and the new\n"
        "    object starts empty.\n"
        "\n"
        "R2 high   aws_s3_bucket.logs\n"
        "    Replaced (create, then delete), because an attribute that cannot be updated in place\n"
        "    changed. Forced by: bucket. It holds the objects in the bucket, and the new object\n"
        "    starts empty.\n"
        "\n"
        "3 findings, 3 blocking.\n"
    )


def test_replacements_that_keep_the_old_object_are_counted_and_do_not_hide_other_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def resource(address: str, actions: list[str]) -> dict[str, object]:
        resource_type, name = address.split(".")
        return {
            "address": address,
            "mode": "managed",
            "type": resource_type,
            "name": name,
            "change": {"actions": actions, "before": {}, "after": {}},
        }

    plan = {
        "format_version": "1.2",
        "resource_changes": [
            resource("aws_instance.web", ["forget", "create"]),
            resource("aws_instance.api", ["create", "forget"]),
            resource("aws_db_instance.main", ["delete"]),
        ],
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert main([str(path)]) == ExitCode.BLOCKING
    out = capsys.readouterr().out
    assert out.startswith("Plan: 2 to replace, 1 to destroy\n")
    assert "R1 high   aws_db_instance.main" in out
    assert out.endswith("1 finding, 1 blocking.\n")


@pytest.mark.parametrize(
    ("actions", "order"),
    [(["forget", "create"], "forget, then create"), (["create", "forget"], "create, then forget")],
)
def test_stateful_replacement_that_keeps_the_old_object_is_blocking(
    actions: list[str], order: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = json.loads((PLANS_DIR / "replace_stateful.json").read_text(encoding="utf-8"))
    orders = next(
        rc for rc in plan["resource_changes"] if rc["address"] == "aws_db_instance.orders"
    )
    orders["change"]["actions"] = actions
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert main([str(path)]) == ExitCode.BLOCKING
    out = capsys.readouterr().out
    assert out.startswith("Plan: 4 to replace (Terraform 1.17.2)\n")
    assert f"R2 high   aws_db_instance.orders\n    Replaced ({order})" in out
    assert "left running rather than destroyed" in out
    assert out.endswith("3 findings, 3 blocking.\n")


def test_missing_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "absent.json"
    assert main([str(missing)]) == ExitCode.INVALID_INPUT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"plan-review: error: cannot read {missing}: No such file or directory\n"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("not json", "not valid JSON"),
        ("{}", "format_version: Field required"),
        ('{"format_version": "2.0"}', "is not supported"),
        (
            '{"format_version": "1.2", "resource_changes": '
            '[{"address": "a.b", "mode": "managed", "type": "a", "name": "b",'
            ' "change": {"actions": ["delete", "delete"]}}]}',
            "unsupported action list",
        ),
    ],
)
def test_unusable_plan_exits_2(
    text: str, reason: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "plan.json"
    path.write_text(text, encoding="utf-8")
    assert main([str(path)]) == ExitCode.INVALID_INPUT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"plan-review: error: {path} is not a usable Terraform plan: ")
    assert reason in captured.err


def test_wrong_arguments_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == ExitCode.INVALID_INPUT
    assert "PLAN_JSON" in capsys.readouterr().err


# Report formats --------------------------------------------------------------------


def test_markdown_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--format", "markdown", plan_path("iam_widened")]) == ExitCode.BLOCKING
    assert capsys.readouterr().out == (
        "## plan-review\n"
        "\n"
        "Plan: 1 to create, 2 to update in place (Terraform 1.17.2)\n"
        "\n"
        "| Rule | Severity | Resource | Finding |\n"
        "|------|----------|----------|---------|\n"
        "| R3 IAM policy widened | **high** | `aws_iam_policy.break_glass` "
        "| New policy allows: \\* on \\*. |\n"
        "| R3 IAM policy widened | **high** | `aws_iam_policy.orders_reader` "
        "| Policy widened, now allows: dynamodb:\\* on \\*. |\n"
        "\n"
        "2 findings, 2 blocking.\n"
    )


def test_markdown_report_without_findings_has_no_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--format", "markdown", plan_path("no_changes")]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "|" not in out
    assert out.endswith("No findings.\n")


def test_markdown_escapes_table_separators(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = {
        "format_version": "1.2",
        "resource_changes": [
            {
                "address": 'aws_db_instance.db["a|b"]',
                "mode": "managed",
                "type": "aws_db_instance",
                "name": "db",
                "change": {"actions": ["delete"], "before": {}, "after": None},
            }
        ],
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    main(["--format", "markdown", str(path)])
    assert '`aws_db_instance.db["a\\|b"]`' in capsys.readouterr().out


def test_markdown_escapes_wildcards_outside_the_address(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    statement = {
        "Effect": "Allow",
        "Action": ["dynamodb:GetItem", "s3:*"],
        "Resource": ["arn:aws:dynamodb:*:*:table/orders", "arn:aws:s3:::bucket/*"],
    }
    plan = {
        "format_version": "1.2",
        "resource_changes": [
            {
                "address": 'aws_iam_policy.p["*"]',
                "mode": "managed",
                "type": "aws_iam_policy",
                "name": "p",
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {"policy": json.dumps({"Statement": [statement]})},
                },
            }
        ],
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert main(["--format", "markdown", str(path)]) == ExitCode.BLOCKING
    assert (
        '| R3 IAM policy widened | **high** | `aws_iam_policy.p["*"]` | New policy allows: '
        "dynamodb:getitem on arn:aws:dynamodb:\\*:\\*:table/orders, "
        "dynamodb:getitem on arn:aws:s3:::bucket/\\*, "
        "s3:\\* on arn:aws:dynamodb:\\*:\\*:table/orders, "
        "s3:\\* on arn:aws:s3:::bucket/\\*. |\n"
    ) in capsys.readouterr().out


def test_json_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--format", "json", plan_path("exposure")]) == ExitCode.BLOCKING
    report = json.loads(capsys.readouterr().out)
    assert report["version"] == 1
    assert report["terraform_version"] == "1.17.2"
    assert report["changes"] == {
        "create": 1,
        "update": 3,
        "replace": 0,
        "delete": 1,
        "read": 0,
        "forget": 0,
        "no-op": 2,
    }
    assert [(f["rule"], f["address"]) for f in report["findings"]] == [
        ("R5", "aws_s3_bucket_public_access_block.assets"),
        ("R5", "aws_s3_bucket_public_access_block.reports"),
        ("R4", "aws_vpc_security_group_ingress_rule.ssh"),
        ("R4", "aws_vpc_security_group_ingress_rule.ssh_ipv6"),
    ]
    assert report["findings"][2] == {
        "rule": "R4",
        "title": "Ingress open to the world",
        "severity": "high",
        "blocking": True,
        "address": "aws_vpc_security_group_ingress_rule.ssh",
        "message": "Ingress newly open to the internet: port 22/tcp from 0.0.0.0/0.",
    }
    assert report["blocking"] == 4
    assert report["ignored"] == 0


def test_unknown_format_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--format", "html", plan_path("no_changes")])
    assert raised.value.code == ExitCode.INVALID_INPUT
    assert "invalid choice" in capsys.readouterr().err


# Configuration ---------------------------------------------------------------------


def use_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    (tmp_path / ".plan-review.yml").write_text(text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)


def test_config_ignores_a_rule_and_lowers_another_to_non_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_config(tmp_path, monkeypatch, "ignore: [R5]\nseverity:\n  R4: medium\n")
    assert main([plan_path("exposure")]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "R5" not in out
    assert "R4 medium aws_vpc_security_group_ingress_rule.ssh\n" in out
    assert out.endswith("2 findings, 0 blocking. 2 ignored by configuration.\n")


def test_config_is_read_from_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_config(tmp_path, monkeypatch, "ignore: [R3]\n")
    assert main(["--format", "json", plan_path("iam_widened")]) == ExitCode.OK
    report = json.loads(capsys.readouterr().out)
    assert report["findings"] == []
    assert report["ignored"] == 2


def test_without_a_config_file_nothing_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main([plan_path("iam_widened")]) == ExitCode.BLOCKING


def test_unusable_config_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_config(tmp_path, monkeypatch, "ignore: [R9]\n")
    assert main([plan_path("no_changes")]) == ExitCode.INVALID_INPUT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(
        "plan-review: error: .plan-review.yml is not a usable configuration: "
        "ignore: unknown rule 'R9'"
    )
