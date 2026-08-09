"""Central language list: the single place to add a supported language.

Each Language entry drives everything at once: the setup dropdowns, the
recognized-language check, and the codes sent to MT providers. To support
a new language, append one entry to LANGUAGES — nothing else to change.

The `code` doubles as the Ren'Py tl/<code>/ folder name, so it must
satisfy core.validators.validate_language_code (lowercase identifier).
Regional variants (e.g. "english_us") keep a distinct folder name but map
to their base ISO code for MT providers, which mostly ignore regions.
"""

from dataclasses import dataclass

from core.i18n import i18n


@dataclass(frozen=True)
class Language:
    """One supported language and its provider-specific codes.

    Attributes:
        code: Internal identifier, also used as the Ren'Py tl folder name.
        label: Human-readable name shown in dropdowns.
        iso: Short ISO 639 code sent to LibreTranslate (lowercase).
        iso_long: Full BCP-47 tag with region or script (e.g. "en-US",
            "zh-Hant"), for providers that support regional variants. A
            provider expecting underscores can derive "en_US" with
            iso_long.replace("-", "_").
        deepl: DeepL code, only when it differs from iso uppercased.
    """

    code: str
    label: str
    iso: str
    iso_long: str | None = None
    deepl: str | None = None

    @property
    def long_code(self) -> str:
        """Return the regional tag, falling back to the short ISO code."""
        return self.iso_long or self.iso


LANGUAGES: list[Language] = [
    Language("english", "English", "en"),
    Language("english_us", "English (US)", "en", iso_long="en-US"),
    Language("english_gb", "English (UK)", "en", iso_long="en-GB"),
    Language("french", "French", "fr"),
    Language("german", "German", "de"),
    Language("spanish", "Spanish", "es"),
    Language("italian", "Italian", "it"),
    Language("portuguese", "Portuguese", "pt"),
    Language("brazilian", "Portuguese (Brazil)", "pt", iso_long="pt-BR"),
    Language("dutch", "Dutch", "nl"),
    Language("polish", "Polish", "pl"),
    Language("russian", "Russian", "ru"),
    Language("ukrainian", "Ukrainian", "uk"),
    Language("turkish", "Turkish", "tr"),
    Language("arabic", "Arabic", "ar"),
    Language("japanese", "Japanese", "ja"),
    Language("korean", "Korean", "ko"),
    Language("schinese", "Chinese (Simplified)", "zh", iso_long="zh-Hans"),
    Language("tchinese", "Chinese (Traditional)", "zt", iso_long="zh-Hant", deepl="ZH"),
]

LANGUAGE_BY_CODE: dict[str, Language] = {lang.code: lang for lang in LANGUAGES}


def get_language(code: str) -> Language | None:
    """Return the Language entry for an internal identifier, if known.

    Args:
        code: The language identifier to look up (case-insensitive).

    Returns:
        The matching Language, or None for unknown identifiers.
    """
    return LANGUAGE_BY_CODE.get(code.lower())


def localized_label(code: str) -> str:
    """Return a language's name in the language of the interface.

    Every screen names a language this way. Only what is written to disk
    keeps the raw code: the tl/ folder and the name of the exported zip.

    Adding a language still takes a single entry in LANGUAGES: without a
    languages.<code> key in the locale files, the name simply stays the
    English label declared there.

    Args:
        code: The language identifier to name (case-insensitive).

    Returns:
        The translated name, the English label, or the code itself for a
        folder nobody declared.
    """
    key = f"languages.{code.lower()}"
    translated = i18n.t(key)
    if translated != key:
        return translated
    language = get_language(code)
    return language.label if language else code
