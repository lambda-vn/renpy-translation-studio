"""Tests for core/validators.py."""

from pathlib import Path

import pytest

from core.validators import (
    is_recognized_language,
    resolve_safe_path,
    validate_language_code,
    validate_project_dir,
)


class TestValidateLanguageCode:
    """Tests for validate_language_code."""

    def test_valid_simple(self) -> None:
        """Simple lowercase word is valid."""
        assert validate_language_code("french") is True

    def test_valid_with_digits(self) -> None:
        """Code with trailing digits is valid."""
        assert validate_language_code("zh2") is True

    def test_valid_with_underscore(self) -> None:
        """Code with underscore is valid."""
        assert validate_language_code("zh_hans") is True

    def test_valid_min_length(self) -> None:
        """Two characters is the minimum valid length."""
        assert validate_language_code("fr") is True

    def test_invalid_uppercase(self) -> None:
        """Uppercase letters are not allowed."""
        assert validate_language_code("French") is False

    def test_invalid_starts_with_digit(self) -> None:
        """Code must not start with a digit."""
        assert validate_language_code("1french") is False

    def test_invalid_too_short(self) -> None:
        """Single character is too short."""
        assert validate_language_code("f") is False

    def test_invalid_too_long(self) -> None:
        """More than 32 characters is too long."""
        assert validate_language_code("a" * 33) is False

    def test_invalid_hyphen(self) -> None:
        """Hyphens are not allowed (only underscores)."""
        assert validate_language_code("zh-hans") is False

    def test_invalid_empty(self) -> None:
        """Empty string is invalid."""
        assert validate_language_code("") is False


class TestIsRecognizedLanguage:
    """Tests for is_recognized_language."""

    def test_known_language(self) -> None:
        """A language in the supported set is recognized."""
        assert is_recognized_language("french") is True

    def test_known_language_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        assert is_recognized_language("French") is True

    def test_custom_tl_folder_name_is_not_recognized(self) -> None:
        """A valid tl/ folder name that isn't a real language is rejected."""
        assert is_recognized_language("quebec_fr") is False

    def test_short_iso_code_is_not_recognized(self) -> None:
        """A short code like 'fr' isn't in the supported set either."""
        assert is_recognized_language("fr") is False


class TestResolveSafePath:
    """Tests for resolve_safe_path."""

    def test_valid_path_within_base(self, tmp_path: Path) -> None:
        """Path inside base resolves correctly."""
        sub = tmp_path / "sub"
        result = resolve_safe_path(str(sub), base=tmp_path)
        assert result == sub.resolve()

    def test_path_without_base(self, tmp_path: Path) -> None:
        """Path without base always resolves."""
        result = resolve_safe_path(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_path_traversal_raises(self, tmp_path: Path) -> None:
        """Path escaping the base raises ValueError."""
        with pytest.raises(ValueError, match="Path traversal"):
            resolve_safe_path(str(tmp_path / ".." / "escape"), base=tmp_path)

    def test_sibling_with_shared_prefix_raises(self, tmp_path: Path) -> None:
        """A sibling directory sharing the base's name as a prefix is rejected."""
        sibling = tmp_path.parent / f"{tmp_path.name}-evil"
        sibling.mkdir()
        with pytest.raises(ValueError, match="Path traversal"):
            resolve_safe_path(str(sibling), base=tmp_path)


class TestValidateProjectDir:
    """Tests for validate_project_dir."""

    def test_valid_project(self, tmp_path: Path) -> None:
        """Directory with game/ subdir is valid."""
        (tmp_path / "game").mkdir()
        assert validate_project_dir(tmp_path) is True

    def test_missing_game_dir(self, tmp_path: Path) -> None:
        """Directory without game/ subdir is invalid."""
        assert validate_project_dir(tmp_path) is False

    def test_not_a_directory(self, tmp_path: Path) -> None:
        """File path is not a valid project dir."""
        f = tmp_path / "file.txt"
        f.touch()
        assert validate_project_dir(f) is False
