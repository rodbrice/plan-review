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
    ],
)
def test_every_documented_action_list_is_classified(actions: list[str], kind: ChangeKind) -> None:
    assert classify(actions) is kind


def test_only_the_two_replacement_orderings_are_replacements() -> None:
    replacements = {kind for kind in ChangeKind if kind.is_replacement}
    assert replacements == {ChangeKind.REPLACE_DELETE_FIRST, ChangeKind.REPLACE_CREATE_FIRST}


@pytest.mark.parametrize(
    "actions",
    [[], ["destroy"], ["update", "delete"], ["create", "create"], ["delete", "create", "delete"]],
)
def test_unknown_action_lists_are_rejected(actions: list[str]) -> None:
    with pytest.raises(ValueError, match="unsupported action list"):
        classify(actions)
