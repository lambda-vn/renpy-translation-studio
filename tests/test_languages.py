"""Tests for core/languages.py."""

from core.i18n import i18n
from core.languages import LANGUAGES, get_language, localized_label
from core.translation.providers.deepl import resolve_deepl_lang
from core.translation.providers.libretranslate import resolve_libretranslate_lang
from core.validators import is_recognized_language, validate_language_code


def test_codes_are_unique() -> None:
    codes = [lang.code for lang in LANGUAGES]
    assert len(codes) == len(set(codes))


def test_every_code_is_a_valid_renpy_tl_folder_name() -> None:
    for lang in LANGUAGES:
        assert validate_language_code(lang.code), lang.code


def test_every_language_has_label_and_iso() -> None:
    for lang in LANGUAGES:
        assert lang.label
        assert lang.iso == lang.iso.lower()


def test_long_code_falls_back_to_short_iso() -> None:
    english = get_language("english")
    english_us = get_language("english_us")
    assert english is not None and english.long_code == "en"
    assert english_us is not None and english_us.long_code == "en-US"


def test_get_language_is_case_insensitive() -> None:
    assert get_language("French") is not None
    assert get_language("unknown_lang") is None


def test_every_language_is_recognized_by_validators() -> None:
    for lang in LANGUAGES:
        assert is_recognized_language(lang.code), lang.code


def test_regional_variant_maps_to_base_iso_code() -> None:
    assert resolve_libretranslate_lang("english_us") == "en"
    assert resolve_deepl_lang("english_us") == "EN"


def test_traditional_chinese_diverges_per_provider() -> None:
    assert resolve_libretranslate_lang("tchinese") == "zt"
    assert resolve_deepl_lang("tchinese") == "ZH"


def test_localized_label_follows_the_interface_language() -> None:
    previous = i18n.locale
    try:
        i18n.set_locale("fr")
        assert localized_label("english") == "Anglais"
        assert localized_label("schinese") == "Chinois (simplifié)"
        i18n.set_locale("en")
        assert localized_label("english") == "English"
    finally:
        i18n.set_locale(previous)


def test_localized_label_falls_back_to_the_declared_label() -> None:
    assert localized_label("FRENCH") == localized_label("french")


def test_localized_label_of_an_undeclared_folder_is_the_folder() -> None:
    assert localized_label("french_canada") == "french_canada"
