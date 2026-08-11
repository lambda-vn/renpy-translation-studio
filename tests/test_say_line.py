"""Tests for core/renpy/say_line.py."""

from core.renpy.say_line import split_say_line


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
