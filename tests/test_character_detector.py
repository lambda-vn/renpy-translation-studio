"""Tests for core/character_detector.py."""

from pathlib import Path

from core.renpy.character_detector import CharacterDetector


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detects_define_character(tmp_path: Path) -> None:
    _write(tmp_path / "game" / "script.rpy", 'define e = Character("Eileen")\n')
    detected = CharacterDetector().detect(tmp_path)
    assert len(detected) == 1
    assert detected[0].variable == "e"
    assert detected[0].display_name == "Eileen"


def test_detects_bare_assignment_character(tmp_path: Path) -> None:
    _write(tmp_path / "game" / "script.rpy", 'm = Character("Mary")\n')
    detected = CharacterDetector().detect(tmp_path)
    assert len(detected) == 1
    assert detected[0].variable == "m"
    assert detected[0].display_name == "Mary"


def test_excludes_tl_directory(tmp_path: Path) -> None:
    _write(tmp_path / "game" / "script.rpy", 'define e = Character("Eileen")\n')
    _write(
        tmp_path / "game" / "tl" / "french" / "script.rpy",
        'define e = Character("Eileen FR")\n',
    )
    detected = CharacterDetector().detect(tmp_path)
    assert len(detected) == 1
    assert detected[0].display_name == "Eileen"


def test_dedup_first_match_wins(tmp_path: Path) -> None:
    _write(
        tmp_path / "game" / "script.rpy",
        'define e = Character("Eileen")\ndefine e = Character("Eileen Again")\n',
    )
    detected = CharacterDetector().detect(tmp_path)
    assert len(detected) == 1
    assert detected[0].display_name == "Eileen"


def test_records_source_file(tmp_path: Path) -> None:
    _write(tmp_path / "game" / "chapter1.rpy", 'define e = Character("Eileen")\n')
    detected = CharacterDetector().detect(tmp_path)
    assert detected[0].source_file == str(Path("game") / "chapter1.rpy")


def test_no_characters_found_returns_empty_list(tmp_path: Path) -> None:
    _write(tmp_path / "game" / "script.rpy", 'label start:\n    "Hello"\n')
    detected = CharacterDetector().detect(tmp_path)
    assert detected == []
