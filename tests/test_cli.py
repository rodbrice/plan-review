"""The command line on the sample plans: printed report and exit status."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from plan_review.cli import ExitCode, main

PLANS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "plans"

EXPECTED_EXIT: dict[str, ExitCode] = {
    "create_baseline": ExitCode.OK,
    "no_changes": ExitCode.OK,
    "iam_widened": ExitCode.OK,  # R3 lands in a later milestone
    "exposure": ExitCode.OK,  # R4 and R5 land in a later milestone
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


def test_reads_the_plan_from_standard_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data = (PLANS_DIR / "destroy_stateful.json").read_bytes()
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(data)))
    assert main(["-"]) == ExitCode.BLOCKING
    assert "3 findings, 3 blocking." in capsys.readouterr().out


def test_forget_with_create_is_counted_and_does_not_hide_other_findings(
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
            resource("aws_instance.moved", ["create", "forget"]),
            resource("aws_instance.renamed", ["forget", "create"]),
            resource("aws_db_instance.main", ["delete"]),
        ],
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert main([str(path)]) == ExitCode.BLOCKING
    out = capsys.readouterr().out
    assert out.startswith("Plan: 1 to destroy, 2 to forget and recreate\n")
    assert "R1 high   aws_db_instance.main" in out
    assert out.endswith("1 finding, 1 blocking.\n")


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


def test_unusable_standard_input_is_named_in_the_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"{}")))
    assert main(["-"]) == ExitCode.INVALID_INPUT
    assert "standard input is not a usable Terraform plan" in capsys.readouterr().err


def test_wrong_arguments_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == ExitCode.INVALID_INPUT
    assert "PLAN_JSON" in capsys.readouterr().err
