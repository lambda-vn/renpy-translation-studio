"""Tests for core/renpy/say_line.py."""

from core.renpy.say_line import block_lines, find_say, split_say_line


class TestSpokenString:
    """The string a translator sees, whatever surrounds it."""

    def test_character_dialogue(self) -> None:
        say = split_say_line('    e "Hello"')
        assert say is not None
        assert (say.prefix, say.text, say.suffix) == ("    e ", "Hello", "")

    def test_narration(self) -> None:
        say = split_say_line('    "The sun was setting."')
        assert say is not None
        assert say.text == "The sun was setting."
        assert say.who is None

    def test_with_clause_is_kept_out_of_the_text(self) -> None:
        say = split_say_line('    MC "{b}*Cough*{/b}" with hpunch')
        assert say is not None
        assert say.text == "{b}*Cough*{/b}"
        assert say.suffix == " with hpunch"
        assert say.who == "MC"

    def test_narration_with_clause(self) -> None:
        say = split_say_line('    "{i}*Knock knock*{/i}" with vpunch')
        assert say is not None
        assert say.text == "{i}*Knock knock*{/i}"
        assert say.who is None

    def test_image_attributes_stay_in_the_prefix(self) -> None:
        say = split_say_line('    e happy "You made it!"')
        assert say is not None
        assert say.prefix == "    e happy "
        assert say.text == "You made it!"
        assert say.who == "e"

    def test_temporary_image_attributes(self) -> None:
        say = split_say_line('    e @ happy "You made it!"')
        assert say is not None
        assert say.text == "You made it!"
        assert say.who == "e"

    def test_quoted_speaker(self) -> None:
        say = split_say_line('    "Store clerk" "Not so fast!" with hpunch')
        assert say is not None
        assert say.prefix == '    "Store clerk" '
        assert say.text == "Not so fast!"
        assert say.suffix == " with hpunch"
        assert say.who == "Store clerk"

    def test_keyword_arguments(self) -> None:
        say = split_say_line('    e "Careful." (what_color="#f00")')
        assert say is not None
        assert say.text == "Careful."
        assert say.suffix == ' (what_color="#f00")'

    def test_nointeract(self) -> None:
        say = split_say_line('    e "Hello" nointeract')
        assert say is not None
        assert say.text == "Hello"
        assert say.suffix == " nointeract"

    def test_trailing_newline_stays_in_the_suffix(self) -> None:
        say = split_say_line('    e "Hello" with hpunch\n')
        assert say is not None
        assert say.suffix == " with hpunch\n"

    def test_escaped_quote_does_not_close_the_string(self) -> None:
        say = split_say_line('    e "He said \\"hi\\" twice"')
        assert say is not None
        assert say.text == 'He said \\"hi\\" twice'

    def test_empty_translation_slot(self) -> None:
        say = split_say_line('    e ""')
        assert say is not None
        assert say.text == ""

    def test_no_indentation(self) -> None:
        say = split_say_line('e "Hello"')
        assert say is not None
        assert say.text == "Hello"


class TestRefusedLines:
    """Lines holding no string a translation could replace."""

    def test_blank_line(self) -> None:
        assert split_say_line("") is None

    def test_statement_without_a_string(self) -> None:
        assert split_say_line("    nvl clear\n") is None

    def test_unterminated_literal(self) -> None:
        assert split_say_line('    e "Hello\n') is None

    def test_multiline_marker(self) -> None:
        assert split_say_line('    e """') is None

    def test_leading_punctuation(self) -> None:
        assert split_say_line('    $ name = "Eileen"') is None


class TestSpeakerResolution:
    """What ends up in character_variable."""

    def test_second_literal_is_the_text_when_a_name_precedes_it(self) -> None:
        """A malformed line keeps its first string rather than the second.

        Only a line whose speaker is written as a string may promote its
        second literal, so `e "a" "b"` cannot silently translate "b".
        """
        say = split_say_line('    e "a" "b"')
        assert say is not None
        assert say.text == "a"
        assert say.suffix == ' "b"'

    def test_unusable_speaker_shape_is_dropped(self) -> None:
        say = split_say_line('    @ "Hello"')
        assert say is not None
        assert say.who is None


class TestFindSay:
    """Which line of a block carries the dialogue."""

    def test_single_statement(self) -> None:
        found = find_say(['    e "Hello"\n'])
        assert found is not None
        assert (found[0], found[1].text) == (0, "Hello")

    def test_voice_is_not_taken_for_the_dialogue(self) -> None:
        """A `voice` answers split_say_line() just as a say does.

        Taking the first line put its audio path where the dialogue was
        supposed to be: read as the text to translate, and overwritten
        with the translation on the way back out.
        """
        found = find_say(['    voice "voice/e01.ogg"\n', '    e "Hello"\n'])
        assert found is not None
        assert (found[0], found[1].text, found[1].who) == (1, "Hello", "e")

    def test_statement_without_a_string_is_skipped(self) -> None:
        found = find_say(["    nvl clear\n", '    e "Hello"\n'])
        assert found is not None
        assert (found[0], found[1].text) == (1, "Hello")

    def test_comments_are_never_taken(self) -> None:
        found = find_say(["\n", '    # e "Hello"\n', '    e ""\n'])
        assert found is not None
        assert (found[0], found[1].text) == (2, "")

    def test_comment_contents_are_read_the_same_way(self) -> None:
        """The comments mirror the statements, so the rule is the same."""
        found = find_say(['voice "voice/e01.ogg"', 'e "Hello"'])
        assert found is not None
        assert (found[0], found[1].text) == (1, "Hello")

    def test_block_without_a_say(self) -> None:
        assert find_say(["\n", "    nvl clear\n"]) is None

    def test_multiline_block_is_refused(self) -> None:
        """Its text spans lines, so no single line can be pointed at.

        The closing `\"\"\"` reads as an empty string and would be taken
        as the last say of the block if the opener did not stop this.
        """
        assert find_say(['    e """\n', "    Hello\n", '    """\n']) is None

    def test_empty_block(self) -> None:
        assert find_say([]) is None


class TestBlockLines:
    """Where a translate block's body ends."""

    def test_stops_at_the_next_header(self) -> None:
        lines = [
            "translate french a:\n",
            "\n",
            '    # e "Hello"\n',
            '    e ""\n',
            "\n",
            "translate french b:\n",
        ]
        assert block_lines(lines, 1) == lines[1:5]

    def test_stops_at_a_file_reference_comment(self) -> None:
        lines = ['    e ""\n', "# game/script.rpy:13\n", "translate french b:\n"]
        assert block_lines(lines, 0) == ['    e ""\n']

    def test_last_block_runs_to_the_end(self) -> None:
        lines = ['    # e "Hello"\n', '    e ""\n']
        assert block_lines(lines, 0) == lines
