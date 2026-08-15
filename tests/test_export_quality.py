"""What the export warning says about the project-wide quality pass.

The assertions read the numbers and the file names rather than the
sentences around them: the strings come from whichever locale the suite
happens to have loaded, and a wording change is not a regression.
"""

from app.views.export_view import _MAX_NAMED_FILES, _quality_messages


def test_nothing_failing_says_nothing() -> None:
    assert _quality_messages({}) == []


def test_the_total_and_the_file_count_are_stated() -> None:
    messages = _quality_messages({"game/a.rpy": 2, "game/b.rpy": 3})

    assert "5" in messages[0]
    assert "2" in messages[0]


def test_files_are_named_worst_first() -> None:
    messages = _quality_messages(
        {"game/small.rpy": 1, "game/worst.rpy": 9, "game/mid.rpy": 4}
    )

    named = messages[1:]
    assert "game/worst.rpy" in named[0]
    assert "game/mid.rpy" in named[1]
    assert "game/small.rpy" in named[2]


def test_files_sharing_a_count_keep_a_stable_order() -> None:
    messages = _quality_messages({"game/b.rpy": 2, "game/a.rpy": 2})

    assert "game/a.rpy" in messages[1]
    assert "game/b.rpy" in messages[2]


def test_the_tail_becomes_a_count() -> None:
    failing = {f"game/f{index}.rpy": index + 1 for index in range(_MAX_NAMED_FILES + 3)}

    messages = _quality_messages(failing)

    assert len(messages) == _MAX_NAMED_FILES + 2
    assert "3" in messages[-1]


def test_exactly_the_cap_names_them_all() -> None:
    failing = {f"game/f{index}.rpy": 1 for index in range(_MAX_NAMED_FILES)}

    messages = _quality_messages(failing)

    assert len(messages) == _MAX_NAMED_FILES + 1
