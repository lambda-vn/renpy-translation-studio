"""Translation quality checks applied before validation."""

import re
from dataclasses import dataclass

from core.i18n import i18n

LENGTH_WARNING_KIND = "length_warning"

TAG_PATTERN = re.compile(r"\{/?[a-z]+[^}]*\}")
_VAR_PATTERN = re.compile(r"\[[^\]]+\]")
_HTMLTAG_PATTERN = re.compile(r"<[a-zA-Z/][^<>]*>")

_LENGTH_RATIO_THRESHOLD = 1.3
_MIN_LENGTH_DIFF_FOR_WARNING = 15


@dataclass
class QualityIssue:
    """A single quality problem detected between source and translation."""

    kind: str
    detail: str


def check(source: str, translation: str) -> list[QualityIssue]:
    """Run all quality checks between source and translation.

    Checks:
    - All Ren'Py text tags in source are present in translation.
    - No extra tags were added in translation.
    - All Python interpolations [var] from source are in translation.
    - No interpolation appears in the translation that the source did not
      already have. Ren'Py evaluates whatever stands between square
      brackets as a Python expression, so an interpolation added by a
      translation is code the game will run when it displays the line.
      A translation reaching the .rpy files from outside (a bilingual
      file returned by a reviewer, a provider response) therefore gets
      code execution on every player of the shipped game, and the writer
      cannot stop it: the payload never leaves the string literal, so
      escaping it is not the answer. Refused rather than warned about,
      which is why this check is symmetric like the tag one.
    - Translation is not both >30% longer AND at least
      _MIN_LENGTH_DIFF_FOR_WARNING characters longer than the source. The
      absolute-difference floor keeps short strings (menu labels, button
      text) from tripping this on entirely normal translations — "Back"
      to "Retour" is 50% longer by ratio alone, but only 2 characters.
    - No HTML-like tags (<a>, <h1>, ...) were introduced in translation.
      Ren'Py uses {tag} markup, never HTML — a <tag> is a sign the
      provider hallucinated instead of translating.

    Args:
        source: The original source text.
        translation: The translated text to validate.

    Returns:
        List of QualityIssue instances; empty list means no problems.
    """
    issues: list[QualityIssue] = []

    source_tags = set(TAG_PATTERN.findall(source))
    translation_tags = set(TAG_PATTERN.findall(translation))
    for tag in source_tags - translation_tags:
        issues.append(
            QualityIssue("missing_tag", i18n.t("quality.missing_tag").format(tag=tag))
        )
    for tag in translation_tags - source_tags:
        issues.append(
            QualityIssue("extra_tag", i18n.t("quality.extra_tag").format(tag=tag))
        )

    source_vars = set(_VAR_PATTERN.findall(source))
    translation_vars = set(_VAR_PATTERN.findall(translation))
    for var in source_vars - translation_vars:
        issues.append(
            QualityIssue("missing_var", i18n.t("quality.missing_var").format(var=var))
        )
    for var in translation_vars - source_vars:
        issues.append(
            QualityIssue("extra_var", i18n.t("quality.extra_var").format(var=var))
        )

    source_html_tags = set(_HTMLTAG_PATTERN.findall(source))
    translation_html_tags = set(_HTMLTAG_PATTERN.findall(translation))
    for tag in translation_html_tags - source_html_tags:
        issues.append(
            QualityIssue(
                "unexpected_html",
                i18n.t("quality.unexpected_html").format(value=tag),
            )
        )

    length_diff = len(translation) - len(source)
    if (
        source
        and length_diff >= _MIN_LENGTH_DIFF_FOR_WARNING
        and len(translation) > len(source) * _LENGTH_RATIO_THRESHOLD
    ):
        percent = f"{length_diff / len(source):.0%}"
        issues.append(
            QualityIssue(
                LENGTH_WARNING_KIND,
                i18n.t("quality.length_warning").format(percent=percent),
            )
        )

    return issues
