"""Tests for core/exporter.py."""

import zipfile
from pathlib import Path

from core.exporter import GameNameResolver, TranslationZipExporter


def _make_tl_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a tl/<lang>/ directory with given files."""
    tl = tmp_path / "tl" / "french"
    tl.mkdir(parents=True)
    for name, content in files.items():
        f = tl / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
    return tl


class TestGameNameResolver:
    """Tests for GameNameResolver.resolve."""

    def test_reads_build_name(self, tmp_path: Path) -> None:
        """build.name is read from options.rpy."""
        game = tmp_path / "game"
        game.mkdir()
        (game / "options.rpy").write_text(
            'define build.name = "My Awesome Game"', encoding="utf-8"
        )
        name = GameNameResolver().resolve(tmp_path)
        assert name == "My-Awesome-Game"

    def test_single_quote_build_name(self, tmp_path: Path) -> None:
        """build.name with single quotes is also parsed."""
        game = tmp_path / "game"
        game.mkdir()
        (game / "options.rpy").write_text(
            "define build.name = 'Cool Game'", encoding="utf-8"
        )
        name = GameNameResolver().resolve(tmp_path)
        assert name == "Cool-Game"

    def test_falls_back_to_dir_name(self, tmp_path: Path) -> None:
        """Directory name is used when options.rpy is absent."""
        name = GameNameResolver().resolve(tmp_path)
        assert name == tmp_path.name

    def test_sanitizes_special_chars(self, tmp_path: Path) -> None:
        """Special characters in game name are replaced by hyphens."""
        game = tmp_path / "game"
        game.mkdir()
        (game / "options.rpy").write_text(
            'define build.name = "My Game: Special Edition"', encoding="utf-8"
        )
        name = GameNameResolver().resolve(tmp_path)
        assert " " not in name
        assert ":" not in name


class TestTranslationZipExporter:
    """Tests for TranslationZipExporter.export."""

    def test_creates_zip(self, tmp_path: Path) -> None:
        """A zip file is created at the output path."""
        tl = _make_tl_dir(tmp_path, {"script.rpy": "translate french x:\n"})
        out = tmp_path / "out.zip"
        TranslationZipExporter().export(tl, "mygame", "french", out)
        assert out.exists()

    def test_zip_structure(self, tmp_path: Path) -> None:
        """Zip entries follow the expected path structure."""
        tl = _make_tl_dir(tmp_path, {"script.rpy": "translate french x:\n"})
        out = tmp_path / "out.zip"
        TranslationZipExporter().export(tl, "mygame", "french", out)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert "mygame/game/tl/french/script.rpy" in names

    def test_excludes_rpyc(self, tmp_path: Path) -> None:
        """.rpyc files are excluded from the zip."""
        tl = _make_tl_dir(tmp_path, {"script.rpy": "translate french x:\n"})
        (tl / "script.rpyc").write_bytes(b"\x00compiled")
        out = tmp_path / "out.zip"
        TranslationZipExporter().export(tl, "mygame", "french", out)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert all(not n.endswith(".rpyc") for n in names)

    def test_nested_files_included(self, tmp_path: Path) -> None:
        """Files in subdirectories are included with correct paths."""
        tl = _make_tl_dir(tmp_path, {"sub/scene.rpy": "translate french y:\n"})
        out = tmp_path / "out.zip"
        TranslationZipExporter().export(tl, "mygame", "french", out)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert "mygame/game/tl/french/sub/scene.rpy" in names
