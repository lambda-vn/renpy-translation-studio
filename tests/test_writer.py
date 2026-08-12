"""Tests for core/writer.py."""

from pathlib import Path

import pytest

from core.renpy.parser import TranslateBlockParser
from core.renpy.writer import TranslateBlockWriter, _escape_translation, _replace_quoted

_RPY_SIMPLE = """\
translate french start_abc:
    # e "Hello world"
    e ""

translate french narr_def:
    # "Narrator text."
    ""

"""

_RPY_ALREADY_TRANSLATED = """\
translate french start_abc:
    # e "Hello"
    e "Bonjour"

"""

_RPY_NO_MATCH = """\
translate french other_xyz:
    # e "Something else"
    e ""

"""

# Exactly what `renpy translate` writes: a file-reference comment, the
# header, a blank line, the commented source statement, then the editable
# line seeded with the source text.
_RPY_GENERATED = """\
# game/script.rpy:12
translate french start_abc:

    # e "Hello world"
    e "Hello world"

# game/script.rpy:13
translate french narr_def:

    # "Narrator text."
    "Narrator text."

"""


@pytest.fixture()
def tl_dir(tmp_path: Path) -> Path:
    """Create a temporary tl directory with a .rpy file."""
    d = tmp_path / "tl" / "french"
    d.mkdir(parents=True)
    (d / "script.rpy").write_text(_RPY_SIMPLE, encoding="utf-8")
    return d


@pytest.fixture()
def backup_dir(tmp_path: Path) -> Path:
    return tmp_path / "backups"


class TestReplaceQuoted:
    def test_character_dialogue(self) -> None:
        result = _replace_quoted('    e "Hello"\n', "Bonjour")
        assert result == '    e "Bonjour"\n'

    def test_narrator(self) -> None:
        result = _replace_quoted('    "Narrator"\n', "Narrateur")
        assert result == '    "Narrateur"\n'

    def test_empty_slot(self) -> None:
        result = _replace_quoted('    e ""\n', "Bonjour")
        assert result == '    e "Bonjour"\n'

    def test_no_quotes_returns_unchanged(self) -> None:
        line = "    no quotes here\n"
        result = _replace_quoted(line, "ignored")
        assert result == line

    def test_raw_quote_is_escaped(self) -> None:
        result = _replace_quoted('    e ""\n', 'Il a dit "oui"')
        assert result == '    e "Il a dit \\"oui\\""\n'

    def test_trailing_backslash_does_not_swallow_closing_quote(self) -> None:
        result = _replace_quoted('    e ""\n', "chemin C:\\")
        assert result == '    e "chemin C:\\\\"\n'

    def test_transition_is_preserved(self) -> None:
        result = _replace_quoted('    MC "*Cough*" with hpunch\n', "*Toux*")
        assert result == '    MC "*Toux*" with hpunch\n'

    def test_quoted_speaker_is_preserved(self) -> None:
        result = _replace_quoted('    "Store clerk" "" with hpunch\n', "Pas si vite !")
        assert result == '    "Store clerk" "Pas si vite !" with hpunch\n'

    def test_keyword_arguments_are_preserved(self) -> None:
        result = _replace_quoted('    e "" (what_color="#f00")\n', "Attention.")
        assert result == '    e "Attention." (what_color="#f00")\n'

    def test_image_attributes_are_preserved(self) -> None:
        result = _replace_quoted('    e happy ""\n', "Tu es venu !")
        assert result == '    e happy "Tu es venu !"\n'

    def test_strings_block_new_line(self) -> None:
        result = _replace_quoted('    new ""\n', "Continuer")
        assert result == '    new "Continuer"\n'

    def test_newline_injection_is_neutralized(self) -> None:
        payload = 'Bonjour"\n    $ evil()\n    e "suite'
        result = _replace_quoted('    e ""\n', payload)
        assert result == '    e "Bonjour\\"\\n    $ evil()\\n    e \\"suite"\n'
        assert result.count("\n") == 1


class TestEscapeTranslation:
    def test_plain_text_unchanged(self) -> None:
        assert _escape_translation("Bonjour le monde") == "Bonjour le monde"

    def test_unescaped_quote_escaped(self) -> None:
        assert _escape_translation('a "b" c') == 'a \\"b\\" c'

    def test_already_escaped_quote_untouched(self) -> None:
        assert _escape_translation('a \\"b\\" c') == 'a \\"b\\" c'

    def test_quote_after_escaped_backslash_escaped(self) -> None:
        assert _escape_translation('a \\\\" b') == 'a \\\\\\" b'

    def test_line_breaks_become_literal_sequences(self) -> None:
        assert _escape_translation("a\nb\r\nc\rd") == "a\\nb\\nc\\nd"

    def test_trailing_backslash_is_doubled(self) -> None:
        assert _escape_translation("chemin C:\\") == "chemin C:\\\\"

    def test_trailing_even_backslashes_untouched(self) -> None:
        assert _escape_translation("chemin C:\\\\") == "chemin C:\\\\"

    def test_escaping_is_idempotent_on_trailing_backslash(self) -> None:
        once = _escape_translation("chemin C:\\")
        assert _escape_translation(once) == once


class TestTranslateBlockWriter:
    def test_write_replaces_editable_line(self, tl_dir: Path, backup_dir: Path) -> None:
        writer = TranslateBlockWriter(tl_dir, backup_dir)
        writer.write_all({"start_abc": "Bonjour le monde"})
        content = (tl_dir / "script.rpy").read_text(encoding="utf-8")
        assert 'e "Bonjour le monde"' in content

    def test_comment_line_preserved(self, tl_dir: Path, backup_dir: Path) -> None:
        writer = TranslateBlockWriter(tl_dir, backup_dir)
        writer.write_all({"start_abc": "Bonjour"})
        content = (tl_dir / "script.rpy").read_text(encoding="utf-8")
        assert '# e "Hello world"' in content

    def test_unmatched_block_unchanged(self, tl_dir: Path, backup_dir: Path) -> None:
        writer = TranslateBlockWriter(tl_dir, backup_dir)
        writer.write_all({"start_abc": "Bonjour"})
        content = (tl_dir / "script.rpy").read_text(encoding="utf-8")
        assert '""' in content

    def test_backup_created_on_change(self, tl_dir: Path, backup_dir: Path) -> None:
        writer = TranslateBlockWriter(tl_dir, backup_dir)
        writer.write_all({"start_abc": "Bonjour"})
        assert (backup_dir / "script.rpy").exists()

    def test_no_backup_if_unchanged(self, tl_dir: Path, backup_dir: Path) -> None:
        writer = TranslateBlockWriter(tl_dir, backup_dir)
        writer.write_all({})
        assert not backup_dir.exists() or not (backup_dir / "script.rpy").exists()

    def test_multiple_blocks_in_one_file(self, tl_dir: Path, backup_dir: Path) -> None:
        writer = TranslateBlockWriter(tl_dir, backup_dir)
        writer.write_all(
            {
                "start_abc": "Bonjour le monde",
                "narr_def": "Texte narrateur",
            }
        )
        content = (tl_dir / "script.rpy").read_text(encoding="utf-8")
        assert '"Bonjour le monde"' in content
        assert '"Texte narrateur"' in content

    def test_already_translated_block_updated(
        self, tmp_path: Path, backup_dir: Path
    ) -> None:
        d = tmp_path / "tl2" / "french"
        d.mkdir(parents=True)
        (d / "script.rpy").write_text(_RPY_ALREADY_TRANSLATED, encoding="utf-8")
        writer = TranslateBlockWriter(d, backup_dir)
        writer.write_all({"start_abc": "Au revoir"})
        content = (d / "script.rpy").read_text(encoding="utf-8")
        assert '"Au revoir"' in content
        assert "Bonjour" not in content

    def test_source_text_restores_the_original_line(
        self, tmp_path: Path, backup_dir: Path
    ) -> None:
        d = tmp_path / "tl4" / "french"
        d.mkdir(parents=True)
        (d / "script.rpy").write_text(_RPY_ALREADY_TRANSLATED, encoding="utf-8")
        writer = TranslateBlockWriter(d, backup_dir)
        writer.write_all({"start_abc": "Hello"})
        content = (d / "script.rpy").read_text(encoding="utf-8")
        assert (
            content == 'translate french start_abc:\n    # e "Hello"\n    e "Hello"\n\n'
        )

    def test_blank_line_after_header_does_not_stop_the_write(
        self, tmp_path: Path, backup_dir: Path
    ) -> None:
        """A generated file has a blank line under every header.

        Skipping only comments left the writer standing on that blank
        line, where it wrote nothing and moved on. Every real project was
        in that shape, so the save button rewrote none of them.
        """
        d = tmp_path / "generated" / "french"
        d.mkdir(parents=True)
        (d / "script.rpy").write_text(_RPY_GENERATED, encoding="utf-8")
        writer = TranslateBlockWriter(d, backup_dir)
        writer.write_all({"start_abc": "Bonjour le monde", "narr_def": "Narration."})
        content = (d / "script.rpy").read_text(encoding="utf-8")
        assert '    e "Bonjour le monde"\n' in content
        assert '    "Narration."\n' in content
        assert '    # e "Hello world"\n' in content

    def test_voice_statement_is_not_written_over(
        self, tmp_path: Path, backup_dir: Path
    ) -> None:
        """Ren'Py groups the voice of a line with the line itself.

        Writing into the first statement of the block replaced the audio
        path with the translation, so the line lost its voice and kept
        its English text.
        """
        d = tmp_path / "voiced" / "french"
        d.mkdir(parents=True)
        (d / "script.rpy").write_text(
            "translate french start_abc:\n\n"
            '    # voice "voice/e01.ogg"\n'
            '    # e "Hello world"\n'
            '    voice "voice/e01.ogg"\n'
            '    e "Hello world"\n',
            encoding="utf-8",
        )
        writer = TranslateBlockWriter(d, backup_dir)
        writer.write_all({"start_abc": "Bonjour le monde"})
        content = (d / "script.rpy").read_text(encoding="utf-8")
        assert '    voice "voice/e01.ogg"\n' in content
        assert '    e "Bonjour le monde"\n' in content

    def test_statement_without_a_string_does_not_stop_the_write(
        self, tmp_path: Path, backup_dir: Path
    ) -> None:
        """An `nvl clear` under the header used to swallow the write."""
        d = tmp_path / "nvl" / "french"
        d.mkdir(parents=True)
        (d / "script.rpy").write_text(
            "translate french start_abc:\n\n"
            "    # nvl clear\n"
            '    # e "Hello world"\n'
            "    nvl clear\n"
            '    e "Hello world"\n',
            encoding="utf-8",
        )
        writer = TranslateBlockWriter(d, backup_dir)
        writer.write_all({"start_abc": "Bonjour le monde"})
        content = (d / "script.rpy").read_text(encoding="utf-8")
        assert "    nvl clear\n" in content
        assert '    e "Bonjour le monde"\n' in content

    def test_multiline_block_is_left_alone(
        self, tmp_path: Path, backup_dir: Path
    ) -> None:
        """Its text spans lines, so no single line can be replaced.

        The closing `\"\"\"` reads as an empty string, and writing the
        translation there would leave a literal running to the end of the
        file.
        """
        original = (
            "translate french multi_abc:\n\n"
            '    # e """\n'
            "    # Hello world.\n"
            '    # """\n'
            '    e """\n'
            "    Hello world.\n"
            '    """\n'
        )
        d = tmp_path / "multi" / "french"
        d.mkdir(parents=True)
        (d / "script.rpy").write_text(original, encoding="utf-8")
        writer = TranslateBlockWriter(d, backup_dir)
        writer.write_all({"multi_abc": "Bonjour le monde."})
        assert (d / "script.rpy").read_text(encoding="utf-8") == original

    def test_empty_block_leaves_the_next_header_alone(
        self, tmp_path: Path, backup_dir: Path
    ) -> None:
        """A block with no editable line must not eat what follows it."""
        d = tmp_path / "empty" / "french"
        d.mkdir(parents=True)
        (d / "script.rpy").write_text(
            "translate french start_abc:\n\ntranslate french narr_def:\n\n"
            '    # "Narrator text."\n    "Narrator text."\n',
            encoding="utf-8",
        )
        writer = TranslateBlockWriter(d, backup_dir)
        writer.write_all({"start_abc": "Bonjour", "narr_def": "Narration."})
        content = (d / "script.rpy").read_text(encoding="utf-8")
        assert "translate french narr_def:\n" in content
        assert '    "Narration."\n' in content

    def test_say_statement_survives_a_round_trip(
        self, tmp_path: Path, backup_dir: Path
    ) -> None:
        """What the parser read back is what the writer put in.

        The fixture holds the statement shapes a translation could be
        written into the wrong part of: a quoted speaker, a transition,
        keyword arguments. Parsing the rewritten file is what proves the
        two agree, since a writer that overwrote the speaker would still
        produce a file the parser reads without complaining.
        """
        source = Path(__file__).parent / "fixtures" / "say_suffixes.rpy"
        d = tmp_path / "roundtrip" / "french"
        d.mkdir(parents=True)
        (d / "script.rpy").write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )
        writer = TranslateBlockWriter(d, backup_dir)
        writer.write_all(
            {
                "clerk_1a2b3c4d": "Pas si vite !",
                "knock_5e6f7a8b": "{b}{i}*Toc toc*{/i}{/b}",
                "cough_9c0d1e2f": "{b}{i}*Toux*{/i}{b}",
                "greet_3a4b5c6d": "Tu es venu !",
            }
        )
        content = (d / "script.rpy").read_text(encoding="utf-8")
        assert '    "Store clerk" "Pas si vite !" with hpunch\n' in content
        assert '    "{b}{i}*Toc toc*{/i}{/b}" with vpunch\n' in content
        assert '    MC "{b}{i}*Toux*{/i}{b}" with hpunch\n' in content
        assert '    e happy "Tu es venu !" nointeract\n' in content

        blocks = TranslateBlockParser().parse_file(d / "script.rpy")
        assert [block.translated_text for block in blocks[:4]] == [
            "Pas si vite !",
            "{b}{i}*Toc toc*{/i}{/b}",
            "{b}{i}*Toux*{/i}{b}",
            "Tu es venu !",
        ]
        assert [block.character_variable for block in blocks[:4]] == [
            "Store clerk",
            None,
            "MC",
            "e",
        ]

    def test_no_match_leaves_file_untouched(
        self, tmp_path: Path, backup_dir: Path
    ) -> None:
        d = tmp_path / "tl3" / "french"
        d.mkdir(parents=True)
        (d / "script.rpy").write_text(_RPY_NO_MATCH, encoding="utf-8")
        writer = TranslateBlockWriter(d, backup_dir)
        writer.write_all({"start_abc": "Bonjour"})
        content = (d / "script.rpy").read_text(encoding="utf-8")
        assert content == _RPY_NO_MATCH


_RPY_STRINGS = """\
translate french strings:

    old "Continue"
    new "Continue"

    old "Return"
    new "Return"

"""

_RPY_STRINGS_TRANSLATED = """\
translate french strings:

    old "Continue"
    new "Continuer"

"""


class TestTranslateBlockWriterStrings:
    """Writer tests for translate ... strings: blocks."""

    @pytest.fixture()
    def tl_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "tl" / "french"
        d.mkdir(parents=True)
        return d

    @pytest.fixture()
    def backup_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "backup"

    def test_strings_new_line_replaced(self, tl_dir: Path, backup_dir: Path) -> None:
        (tl_dir / "common.rpy").write_text(_RPY_STRINGS, encoding="utf-8")
        writer = TranslateBlockWriter(tl_dir, backup_dir)
        writer.write_all({}, old_to_new={"Continue": "Continuer"})
        content = (tl_dir / "common.rpy").read_text(encoding="utf-8")
        assert 'new "Continuer"' in content

    def test_strings_untranslated_lines_unchanged(
        self, tl_dir: Path, backup_dir: Path
    ) -> None:
        (tl_dir / "common.rpy").write_text(_RPY_STRINGS, encoding="utf-8")
        writer = TranslateBlockWriter(tl_dir, backup_dir)
        writer.write_all({}, old_to_new={"Continue": "Continuer"})
        content = (tl_dir / "common.rpy").read_text(encoding="utf-8")
        # "Return" was not in old_to_new, so stays unchanged
        assert 'new "Return"' in content

    def test_strings_old_text_restores_the_original_new_line(
        self, tl_dir: Path, backup_dir: Path
    ) -> None:
        (tl_dir / "common.rpy").write_text(_RPY_STRINGS_TRANSLATED, encoding="utf-8")
        writer = TranslateBlockWriter(tl_dir, backup_dir)
        writer.write_all({}, old_to_new={"Continue": "Continue"})
        content = (tl_dir / "common.rpy").read_text(encoding="utf-8")
        assert 'new "Continue"' in content
        assert "Continuer" not in content

    def test_strings_backup_created_when_changed(
        self, tl_dir: Path, backup_dir: Path
    ) -> None:
        (tl_dir / "common.rpy").write_text(_RPY_STRINGS, encoding="utf-8")
        writer = TranslateBlockWriter(tl_dir, backup_dir)
        writer.write_all({}, old_to_new={"Continue": "Continuer"})
        assert (backup_dir / "common.rpy").exists()

    def test_dialogue_and_strings_in_same_pass(
        self, tl_dir: Path, backup_dir: Path
    ) -> None:
        mixed = (
            "translate french start_abc:\n"
            '    # e "Hello"\n'
            '    e ""\n\n'
            "translate french strings:\n\n"
            '    old "Yes"\n'
            '    new "Yes"\n\n'
        )
        (tl_dir / "mixed.rpy").write_text(mixed, encoding="utf-8")
        writer = TranslateBlockWriter(tl_dir, backup_dir)
        writer.write_all({"start_abc": "Bonjour"}, old_to_new={"Yes": "Oui"})
        content = (tl_dir / "mixed.rpy").read_text(encoding="utf-8")
        assert 'e "Bonjour"' in content
        assert 'new "Oui"' in content
