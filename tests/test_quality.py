"""Tests for core/quality.py."""

from core.translation.quality import LENGTH_WARNING_KIND, check, has_blocking_issue


def test_no_issues() -> None:
    issues = check("Hello [name]!", "Bonjour [name]!")
    assert issues == []


def test_no_issues_simple() -> None:
    issues = check("Hello world !", "Bonjour!")
    assert issues == []


def test_missing_tag_single() -> None:
    issues = check("{b}Hello{/b}", "Bonjour")
    kinds = [i.kind for i in issues]
    assert "missing_tag" in kinds


def test_missing_tag_partial() -> None:
    issues = check("{b}Hello{/b}", "{b}Bonjour")
    kinds = [i.kind for i in issues]
    assert "missing_tag" in kinds


def test_extra_tag() -> None:
    issues = check("Hello", "{b}Bonjour{/b}")
    kinds = [i.kind for i in issues]
    assert "extra_tag" in kinds


def test_missing_var() -> None:
    issues = check("Hello [player_name]!", "Bonjour!")
    kinds = [i.kind for i in issues]
    assert "missing_var" in kinds


def test_var_preserved() -> None:
    issues = check("Score: [score]", "Score: [score]")
    assert issues == []


def test_extra_var() -> None:
    issues = check("Hello!", "Bonjour [player_name] !")
    kinds = [i.kind for i in issues]
    assert "extra_var" in kinds


def test_injected_python_expression_is_refused() -> None:
    """An interpolation carrying code must be refused, not warned about.

    Ren'Py evaluates whatever stands between square brackets, so this
    runs on every player of the shipped game. The kind must therefore be
    anything but LENGTH_WARNING_KIND, which is the one the review screen
    and the import let through.
    """
    issues = check("Hello!", "Bonjour [__import__('os').system('id')] !")
    blocking = [i for i in issues if i.kind != LENGTH_WARNING_KIND]
    assert any(i.kind == "extra_var" for i in blocking)


def test_var_renamed_flags_both_directions() -> None:
    issues = check("Hello [name]!", "Bonjour [nom] !")
    kinds = [i.kind for i in issues]
    assert "missing_var" in kinds
    assert "extra_var" in kinds


def test_length_warning() -> None:
    source = "Hi"
    translation = "A" * 100
    issues = check(source, translation)
    kinds = [i.kind for i in issues]
    assert "length_warning" in kinds


def test_length_ok_at_130_percent() -> None:
    source = "Hello world"
    translation = "A" * int(len(source) * 1.3)
    issues = check(source, translation)
    assert not any(i.kind == "length_warning" for i in issues)


def test_short_string_expansion_not_flagged() -> None:
    """A short word naturally expanding in French must not warn.

    "Back" -> "Retour" is 50% longer by ratio alone, but only 2
    characters — below the absolute-difference floor that filters out
    this kind of normal short-string variation (menu labels, buttons).
    """
    issues = check("Back", "Retour")
    assert not any(i.kind == "length_warning" for i in issues)


def test_length_warning_message_shows_the_increase_not_the_ratio() -> None:
    """The message must state how much longer, not the new/old ratio.

    A translation twice as long as the source is "100% longer", not
    "200%" (the ratio itself, easily mistaken for the increase).
    """
    issues = check("A" * 20, "A" * 40)
    warning = next(i for i in issues if i.kind == "length_warning")
    assert "100%" in warning.detail


def test_empty_translation_no_crash() -> None:
    issues = check("Hello", "")
    assert isinstance(issues, list)


def test_empty_source_no_length_warning() -> None:
    issues = check("", "Some text")
    assert not any(i.kind == "length_warning" for i in issues)


def test_unexpected_html_tag() -> None:
    issues = check("{a=link}Auto Page{/a}", '<a href="link">Auto Page</a>')
    kinds = [i.kind for i in issues]
    assert "unexpected_html" in kinds


def test_html_lookalike_in_source_not_flagged() -> None:
    issues = check("<b>", "<b>")
    assert not any(i.kind == "unexpected_html" for i in issues)


def test_multiple_issues() -> None:
    issues = check("{b}Hello [name]{/b}", "Bonjour")
    kinds = [i.kind for i in issues]
    assert "missing_tag" in kinds
    assert "missing_var" in kinds


class TestHasBlockingIssue:
    """The shared definition of a translation that must not ship."""

    def test_a_clean_translation_blocks_nothing(self) -> None:
        assert not has_blocking_issue("Hello [name]!", "Bonjour [name] !")

    def test_a_lost_tag_blocks(self) -> None:
        assert has_blocking_issue("{b}Hello{/b}", "Bonjour")

    def test_an_invented_interpolation_blocks(self) -> None:
        """The security check: Ren'Py runs what stands in the brackets."""
        assert has_blocking_issue("Hello", "Bonjour [player_name]")

    def test_a_length_warning_alone_does_not_block(self) -> None:
        source = "Back"
        translation = "Retourner au menu principal du jeu"
        assert any(i.kind == LENGTH_WARNING_KIND for i in check(source, translation))
        assert not has_blocking_issue(source, translation)
