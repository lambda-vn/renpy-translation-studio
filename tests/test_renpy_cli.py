"""Tests for core/renpy/cli.py."""

from core.renpy.cli import parse_failed_files

_SDK_OUTPUT = """\
File "game/MechanicalScripts/Phone.rpy", line 249: the box_wrap keyword \
argument was not given a value.
    vbox spacing 3 box_wrap:
                   ^

File "game/MechanicalScripts/Phone.rpy", line 270: the box_wrap keyword \
argument was not given a value.
    vbox spacing 3 box_wrap:
                   ^

File "game/Events/Day1.rpy", line 12: expected statement.
"""


def test_parses_each_blamed_file_once() -> None:
    """A file blamed several times is reported once, in order."""
    assert parse_failed_files(_SDK_OUTPUT) == [
        "game/MechanicalScripts/Phone.rpy",
        "game/Events/Day1.rpy",
    ]


def test_returns_empty_without_a_file_reference() -> None:
    """Output carrying no file reference yields nothing to discard."""
    assert parse_failed_files("Ren'Py SDK failed (exit 1):\nSomething broke") == []


def test_ignores_a_file_reference_without_a_line_number() -> None:
    """Only Ren'Py's 'File "x", line N' shape counts."""
    assert parse_failed_files('File "game/x.rpy" was mentioned') == []
