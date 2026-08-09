"""Tests for ProjectSetupView._only_common_rpy."""

from app.views.project_setup import ProjectSetupView
from core.renpy.parser import TranslationBlock


def _block(source_file: str) -> TranslationBlock:
    """Build a minimal dialogue block attributed to the given source file."""
    return TranslationBlock(
        block_id="start_1",
        source_file=source_file,
        source_line=1,
        character_variable=None,
        source_text="Hello!",
        translated_text="",
    )


def test_true_when_every_block_is_from_common_rpy() -> None:
    """A run producing only engine strings is flagged."""
    blocks = [
        _block("C:/game/tl/french/common.rpy"),
        _block("C:/game/tl/french/common.rpy"),
    ]
    assert ProjectSetupView._only_common_rpy(blocks) is True


def test_false_when_a_game_script_is_present() -> None:
    """A single block from a real game script clears the diagnostic."""
    blocks = [
        _block("C:/game/tl/french/common.rpy"),
        _block("C:/game/tl/french/Script.rpy"),
    ]
    assert ProjectSetupView._only_common_rpy(blocks) is False


def test_false_when_no_blocks() -> None:
    """An empty extraction is not this diagnostic's concern."""
    assert ProjectSetupView._only_common_rpy([]) is False


def test_matches_by_file_name_not_by_substring() -> None:
    """A script merely containing "common.rpy" in its path does not match."""
    blocks = [_block("C:/game/tl/french/notcommon.rpy")]
    assert ProjectSetupView._only_common_rpy(blocks) is False
