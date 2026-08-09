"""Tests for core/parser.py."""

from pathlib import Path

import pytest

from core.renpy.parser import (
    ParseError,
    TranslateBlockParser,
    TranslationBlock,
    is_translated,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestTranslateBlockParserDialogue:
    """Parser tests using simple_dialogue.rpy fixture."""

    def setup_method(self) -> None:
        """Set up parser instance."""
        self.parser = TranslateBlockParser()
        self.blocks = self.parser.parse_file(FIXTURES / "simple_dialogue.rpy")

    def test_correct_block_count(self) -> None:
        """Three dialogue blocks are parsed."""
        assert len(self.blocks) == 3

    def test_block_id(self) -> None:
        """Block ID matches fixture value."""
        assert self.blocks[0].block_id == "start_636ae3f5"

    def test_character_variable(self) -> None:
        """Character variable is extracted correctly."""
        assert self.blocks[0].character_variable == "e"
        assert self.blocks[2].character_variable == "m"

    def test_source_text(self) -> None:
        """Source text is extracted from comment."""
        assert self.blocks[0].source_text == "Hello, how are you today?"

    def test_translated_text_empty(self) -> None:
        """Untranslated blocks have empty translated_text."""
        assert self.blocks[0].translated_text == ""

    def test_source_line(self) -> None:
        """Source line number points to the translate header."""
        assert self.blocks[0].source_line == 1


class TestTranslateBlockParserNarrator:
    """Parser tests using narrator.rpy fixture."""

    def setup_method(self) -> None:
        """Set up parser instance."""
        self.parser = TranslateBlockParser()
        self.blocks = self.parser.parse_file(FIXTURES / "narrator.rpy")

    def test_block_count(self) -> None:
        """Two narrator blocks are parsed."""
        assert len(self.blocks) == 2

    def test_no_character_variable(self) -> None:
        """Narrator blocks have no character variable."""
        for block in self.blocks:
            assert block.character_variable is None

    def test_source_text(self) -> None:
        """Narrator source text is extracted correctly."""
        assert self.blocks[0].source_text == "The sun was setting over the city."


class TestTranslateBlockParserMenu:
    """Parser tests using menu_choice.rpy fixture."""

    def setup_method(self) -> None:
        """Set up parser instance."""
        self.parser = TranslateBlockParser()
        self.blocks = self.parser.parse_file(FIXTURES / "menu_choice.rpy")

    def test_block_count(self) -> None:
        """Three menu choice blocks are parsed."""
        assert len(self.blocks) == 3

    def test_no_character_variable(self) -> None:
        """Menu choice blocks have no character variable."""
        for block in self.blocks:
            assert block.character_variable is None

    def test_source_text(self) -> None:
        """Menu choice text is extracted correctly."""
        assert self.blocks[0].source_text == "Yes, let's go."


class TestTranslateBlockParserMultiline:
    """Parser tests using multiline.rpy fixture."""

    def setup_method(self) -> None:
        """Set up parser instance."""
        self.parser = TranslateBlockParser()
        self.blocks = self.parser.parse_file(FIXTURES / "multiline.rpy")

    def test_block_count(self) -> None:
        """Two blocks are parsed (multiline and interpolation)."""
        assert len(self.blocks) == 2

    def test_multiline_character_variable(self) -> None:
        """Multiline block has correct character variable."""
        assert self.blocks[0].character_variable == "e"

    def test_multiline_source_text(self) -> None:
        """Multiline source text spans three lines joined by newline."""
        expected = (
            "This is the first line.\nThis is the second line.\nAnd this is the third."
        )
        assert self.blocks[0].source_text == expected

    def test_interpolation_source_text(self) -> None:
        """Interpolation tags are preserved in source text."""
        assert "[player_name]" in self.blocks[1].source_text
        assert "{b}" in self.blocks[1].source_text


class TestTranslateBlockParserDirectory:
    """Parser directory scan tests."""

    def test_parse_directory(self) -> None:
        """parse_directory returns blocks from all fixture files."""
        parser = TranslateBlockParser()
        blocks = parser.parse_directory(FIXTURES)
        assert len(blocks) > 5

    def test_all_blocks_are_translation_blocks(self) -> None:
        """Every returned item is a TranslationBlock."""
        parser = TranslateBlockParser()
        blocks = parser.parse_directory(FIXTURES)
        for block in blocks:
            assert isinstance(block, TranslationBlock)


class TestTranslateBlockParserStringsBlock:
    """Parser tests for translate ... strings: blocks (SDK format)."""

    def _make_file(self, tmp_path: Path, content: str) -> Path:
        rpy = tmp_path / "strings.rpy"
        rpy.write_text(content, encoding="utf-8")
        return rpy

    def test_strings_block_produces_blocks(self, tmp_path: Path) -> None:
        """Each old/new pair in a strings block becomes one TranslationBlock."""
        rpy = self._make_file(
            tmp_path,
            "translate french strings:\n\n"
            '    old "Continue"\n'
            '    new "Continuer"\n\n'
            '    old "Return"\n'
            '    new "Retour"\n',
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert len(blocks) == 2

    def test_strings_block_source_text(self, tmp_path: Path) -> None:
        """source_text is the old string."""
        rpy = self._make_file(
            tmp_path,
            'translate french strings:\n    old "Hello"\n    new "Bonjour"\n',
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert blocks[0].source_text == "Hello"
        assert blocks[0].translated_text == "Bonjour"

    def test_strings_block_empty_new(self, tmp_path: Path) -> None:
        """Empty new string is stored as empty translated_text."""
        rpy = self._make_file(
            tmp_path,
            'translate french strings:\n    old "Hi"\n    new ""\n',
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert blocks[0].translated_text == ""

    def test_strings_block_id_prefix(self, tmp_path: Path) -> None:
        """block_id for strings blocks starts with 'strings_'."""
        rpy = self._make_file(
            tmp_path,
            'translate french strings:\n    old "X"\n    new "Y"\n',
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert blocks[0].block_id.startswith("strings_")

    def test_strings_and_dialogue_in_same_file(self, tmp_path: Path) -> None:
        """A file can contain both dialogue blocks and strings blocks."""
        rpy = self._make_file(
            tmp_path,
            'translate french abc123:\n    # e "Hi"\n    e "Hi"\n\n'
            'translate french strings:\n    old "Yes"\n    new "Oui"\n',
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert len(blocks) == 2
        block_ids = {b.block_id for b in blocks}
        assert any(bid.startswith("strings_") for bid in block_ids)
        assert any(not bid.startswith("strings_") for bid in block_ids)

    def test_strings_block_no_character_variable(self, tmp_path: Path) -> None:
        """Strings blocks never have a character_variable."""
        rpy = self._make_file(
            tmp_path,
            'translate french strings:\n    old "Test"\n    new "Test"\n',
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert blocks[0].character_variable is None


class TestTranslateBlockParserStringCharacter:
    """Parser tests for string-named character blocks."""

    def test_string_char_source_text(self, tmp_path: Path) -> None:
        """String-named character: source text is the dialogue, not the name."""
        rpy = tmp_path / "s.rpy"
        rpy.write_text(
            'translate french x:\n    # "Soul Weaver" "What are you doing here?"\n'
            '    "Soul Weaver" "What are you doing here?"\n',
            encoding="utf-8",
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert len(blocks) == 1
        assert blocks[0].source_text == "What are you doing here?"
        assert blocks[0].character_variable == "Soul Weaver"

    def test_string_char_translated_text(self, tmp_path: Path) -> None:
        """String-named character: translated_text is captured correctly."""
        rpy = tmp_path / "s.rpy"
        rpy.write_text(
            'translate french x:\n    # "???" "Hello"\n    "???" "Bonjour"\n',
            encoding="utf-8",
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert len(blocks) == 1
        assert blocks[0].translated_text == "Bonjour"
        assert blocks[0].character_variable == "???"


class TestTranslateBlockParserSdkFormat:
    """Parser tests for SDK-generated files (blank line after header)."""

    def test_sdk_blank_line_dialogue(self, tmp_path: Path) -> None:
        """SDK format with blank line between header and comment is parsed."""
        rpy = tmp_path / "script.rpy"
        rpy.write_text(
            'translate french start_abc123:\n\n    # e "Hello"\n    e ""\n',
            encoding="utf-8",
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert len(blocks) == 1
        assert blocks[0].source_text == "Hello"
        assert blocks[0].character_variable == "e"

    def test_sdk_blank_line_narrator(self, tmp_path: Path) -> None:
        """SDK format narrator block with blank line is parsed."""
        rpy = tmp_path / "narr.rpy"
        rpy.write_text(
            'translate french narr_abc:\n\n    # "Some text."\n    ""\n',
            encoding="utf-8",
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert len(blocks) == 1
        assert blocks[0].source_text == "Some text."
        assert blocks[0].character_variable is None

    def test_sdk_multiple_blocks(self, tmp_path: Path) -> None:
        """Multiple SDK-format blocks in one file are all parsed."""
        rpy = tmp_path / "multi.rpy"
        rpy.write_text(
            'translate french a1:\n\n    # e "First"\n    e ""\n\n'
            'translate french a2:\n\n    # e "Second"\n    e ""\n',
            encoding="utf-8",
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert len(blocks) == 2
        assert blocks[0].source_text == "First"
        assert blocks[1].source_text == "Second"


class TestTranslateBlockParserReferenceComment:
    """Parser tests for SDK file-reference comments before source text."""

    def test_file_ref_comment_skipped(self, tmp_path: Path) -> None:
        """SDK file-reference comment before source is not used as source_text."""
        rpy = tmp_path / "common.rpy"
        rpy.write_text(
            "translate french abc123:\n\n"
            "    # renpy/common/000statements.rpy:28\n"
            '    # "Continue"\n'
            '    ""\n',
            encoding="utf-8",
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert len(blocks) == 1
        assert blocks[0].source_text == "Continue"

    def test_file_ref_comment_with_char(self, tmp_path: Path) -> None:
        """SDK file-reference comment before character dialogue is skipped."""
        rpy = tmp_path / "script.rpy"
        rpy.write_text(
            "translate french abc456:\n\n"
            "    # game/script.rpy:351\n"
            '    # e "Hello world"\n'
            '    e ""\n',
            encoding="utf-8",
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert len(blocks) == 1
        assert blocks[0].source_text == "Hello world"
        assert blocks[0].character_variable == "e"

    def test_curly_brace_text_preserved(self, tmp_path: Path) -> None:
        """Text starting with Ren'Py tags like {i} is not treated as file ref."""
        rpy = tmp_path / "tagged.rpy"
        rpy.write_text(
            "translate french abc789:\n\n"
            "    # {i}Some italic text.{/i}\n"
            '    "{i}Some italic text.{/i}"\n',
            encoding="utf-8",
        )
        blocks = TranslateBlockParser().parse_file(rpy)
        assert len(blocks) == 1
        assert "{i}" in blocks[0].source_text


class TestTranslateBlockParserErrors:
    """Parser error handling tests."""

    def test_missing_file_raises_parse_error(self, tmp_path: Path) -> None:
        """ParseError is raised for a non-existent file."""
        parser = TranslateBlockParser()
        with pytest.raises(ParseError):
            parser.parse_file(tmp_path / "nonexistent.rpy")


class TestIsTranslated:
    """Detection of blocks already translated on disk."""

    @staticmethod
    def _block(source: str, translated: str) -> TranslationBlock:
        """Build a dialogue block with the given source and translation."""
        return TranslationBlock(
            block_id="abc123",
            source_file="script.rpy",
            source_line=1,
            character_variable=None,
            source_text=source,
            translated_text=translated,
        )

    def test_differing_text_is_translated(self) -> None:
        """A translation differing from its source counts as translated."""
        assert is_translated(self._block("Hello!", "Bonjour !")) is True

    def test_copy_of_source_is_not_translated(self) -> None:
        """A fresh SDK stub repeats the source and is not a translation."""
        assert is_translated(self._block("Hello!", "Hello!")) is False

    def test_empty_translation_is_not_translated(self) -> None:
        """A block with no translation line is not translated."""
        assert is_translated(self._block("Hello!", "")) is False

    def test_multiline_block_is_not_translated(self) -> None:
        """Multiline blocks are skipped: their translation is unreadable."""
        assert is_translated(self._block("One\nTwo", '"')) is False
