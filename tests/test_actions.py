"""Classification of change.actions lists."""

from __future__ import annotations

import pytest

from plan_review.actions import ChangeKind, classify


@pytest.mark.parametrize(
    ("actions", "kind"),
    [
        (["no-op"], ChangeKind.NO_OP),
        (["create"], ChangeKind.CREATE),
        (["read"], ChangeKind.READ),
        (["update"], ChangeKind.UPDATE),
        (["delete"], ChangeKind.DELETE),
        (["delete", "create"], ChangeKind.REPLACE_DELETE_FIRST),
        (["create", "delete"], ChangeKind.REPLACE_CREATE_FIRST),
        (["forget"], ChangeKind.FORGET),
        (["forget", "create"], ChangeKind.REPLACE_FORGET_FIRST),
        (["create", "forget"], ChangeKind.REPLACE_CREATE_FIRST_KEEP_OLD),
    ],
)
def test_every_documented_action_list_is_classified(actions: list[str], kind: ChangeKind) -> None:
    assert classify(actions) is kind


def test_the_four_two_step_action_lists_are_replacements() -> None:
    replacements = {kind for kind in ChangeKind if kind.is_replacement}
    assert replacements == {
        ChangeKind.REPLACE_DELETE_FIRST,
        ChangeKind.REPLACE_CREATE_FIRST,
        ChangeKind.REPLACE_FORGET_FIRST,
        ChangeKind.REPLACE_CREATE_FIRST_KEEP_OLD,
    }


def test_only_forget_replacements_keep_the_old_object() -> None:
    kept = {kind for kind in ChangeKind if kind.keeps_old_object}
    assert kept == {ChangeKind.REPLACE_FORGET_FIRST, ChangeKind.REPLACE_CREATE_FIRST_KEEP_OLD}
    assert all(kind.is_replacement for kind in kept)


@pytest.mark.parametrize(
    "actions",
    [
        [],
        ["destroy"],
        ["update", "delete"],
        ["create", "create"],
        ["delete", "forget"],
        ["delete", "create", "delete"],
    ],
)
def test_unknown_action_lists_are_rejected(actions: list[str]) -> None:
    with pytest.raises(ValueError, match="unsupported action list"):
        classify(actions)
