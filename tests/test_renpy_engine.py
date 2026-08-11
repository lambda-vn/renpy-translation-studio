"""Tests for core/renpy/engine.py."""

from pathlib import Path

import pytest

from core.renpy.engine import (
    EngineNotFoundError,
    can_use_game_engine,
    find_game_launcher,
    game_platforms,
    resolve_engine,
)

_WIN_LIB = ("py2-windows-i686", "py2-windows-x86_64", "python2.7")
_PC_LIB = ("py3-linux-x86_64", "py3-windows-x86_64", "python3.9")


def _make_game(
    root: Path,
    *,
    launchers: tuple[str, ...],
    lib_dirs: tuple[str, ...],
    with_renpy: bool = True,
) -> Path:
    """Build a folder shaped like a packaged Ren'Py game.

    Args:
        root: Folder to fill, created if needed.
        launchers: File names to drop at the root.
        lib_dirs: Subdirectory names of lib/.
        with_renpy: False leaves out the renpy/ folder every packaged
            game carries.

    Returns:
        The project root.
    """
    (root / "game").mkdir(parents=True, exist_ok=True)
    if with_renpy:
        (root / "renpy").mkdir(exist_ok=True)
    (root / "lib").mkdir(exist_ok=True)
    for name in lib_dirs:
        (root / "lib" / name).mkdir(exist_ok=True)
    for name in launchers:
        (root / name).touch()
    return root


def test_finds_the_windows_launcher_and_skips_the_32_bit_twin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The -32.exe is never the launcher to run."""
    monkeypatch.setattr("sys.platform", "win32")
    game = _make_game(
        tmp_path,
        launchers=("Stormside-32.exe", "Stormside.exe", "Stormside.py"),
        lib_dirs=_WIN_LIB,
    )
    assert find_game_launcher(game) == game / "Stormside.exe"


def test_prefers_the_shell_launcher_on_linux(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A -pc build offers both, and only the .sh runs there."""
    monkeypatch.setattr("sys.platform", "linux")
    game = _make_game(
        tmp_path,
        launchers=("Red_Veil.exe", "Red_Veil.sh", "Red_Veil.py"),
        lib_dirs=_PC_LIB,
    )
    assert find_game_launcher(game) == game / "Red_Veil.sh"


def test_finds_a_launcher_meant_for_another_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Windows build seen from Linux still yields its launcher.

    Naming it is what tells the two failures apart: a folder holding no
    engine, and one holding an engine for the wrong system.
    """
    monkeypatch.setattr("sys.platform", "linux")
    game = _make_game(
        tmp_path,
        launchers=("Stormside.exe", "Stormside.py"),
        lib_dirs=_WIN_LIB,
    )
    assert find_game_launcher(game) == game / "Stormside.exe"


def test_ignores_an_executable_without_its_python_twin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tool left in the folder never wins the pick over the launcher.

    Sorting alone would hand it the game whenever its name comes first.
    """
    monkeypatch.setattr("sys.platform", "win32")
    game = _make_game(
        tmp_path,
        launchers=("AAAUnRen.exe", "Stormside.exe", "Stormside.py"),
        lib_dirs=_WIN_LIB,
    )
    assert find_game_launcher(game) == game / "Stormside.exe"


def test_ignores_a_folder_holding_only_an_unpaired_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No launcher at all beats running something that is not one."""
    monkeypatch.setattr("sys.platform", "win32")
    game = _make_game(tmp_path, launchers=("UnRen.exe",), lib_dirs=_WIN_LIB)
    assert find_game_launcher(game) is None


def test_ignores_a_folder_without_the_engine_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stray script in a source folder is not a game launcher."""
    monkeypatch.setattr("sys.platform", "linux")
    game = _make_game(
        tmp_path,
        launchers=("build.py",),
        lib_dirs=(),
        with_renpy=False,
    )
    assert find_game_launcher(game) is None


def test_reads_the_platforms_from_the_lib_folder(tmp_path: Path) -> None:
    """lib/ names one directory per platform the build targets."""
    game = _make_game(tmp_path, launchers=("Red_Veil.sh",), lib_dirs=_PC_LIB)
    assert game_platforms(game) == {"linux", "windows"}


def test_reports_no_platform_without_a_lib_folder(tmp_path: Path) -> None:
    """A folder with no lib/ ships no runtime at all."""
    (tmp_path / "game").mkdir()
    assert game_platforms(tmp_path) == set()


def test_windows_build_is_unusable_on_linux(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The executable exists, the runtime next to it does not."""
    monkeypatch.setattr("sys.platform", "linux")
    game = _make_game(
        tmp_path, launchers=("Stormside.exe", "Stormside.py"), lib_dirs=_WIN_LIB
    )
    assert can_use_game_engine(game) is False


def test_windows_build_is_usable_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same build, run on the system it was made for."""
    monkeypatch.setattr("sys.platform", "win32")
    game = _make_game(
        tmp_path, launchers=("Stormside.exe", "Stormside.py"), lib_dirs=_WIN_LIB
    )
    assert can_use_game_engine(game) is True


def test_resolves_to_the_game_engine_over_the_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The game's own engine wins even when an SDK is configured."""
    monkeypatch.setattr("sys.platform", "win32")
    game = _make_game(
        tmp_path / "game-root",
        launchers=("Stormside.exe", "Stormside.py"),
        lib_dirs=_WIN_LIB,
    )
    sdk = tmp_path / "renpy.exe"
    sdk.touch()
    assert resolve_engine(game, sdk) == game / "Stormside.exe"


def test_falls_back_to_the_sdk_for_a_foreign_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Windows build on Linux is what the SDK is kept for."""
    monkeypatch.setattr("sys.platform", "linux")
    game = _make_game(
        tmp_path / "game-root",
        launchers=("Stormside.exe", "Stormside.py"),
        lib_dirs=_WIN_LIB,
    )
    sdk = tmp_path / "renpy.sh"
    sdk.touch()
    assert resolve_engine(game, sdk) == sdk


def test_names_the_platform_of_the_build_it_cannot_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure says which system the game was built for."""
    monkeypatch.setattr("sys.platform", "linux")
    game = _make_game(
        tmp_path, launchers=("Stormside.exe", "Stormside.py"), lib_dirs=_WIN_LIB
    )
    with pytest.raises(EngineNotFoundError, match="Windows"):
        resolve_engine(game, None)


def test_refuses_a_folder_holding_neither_engine_nor_sdk(tmp_path: Path) -> None:
    """Nothing to run, and nothing configured to run it with."""
    (tmp_path / "game").mkdir()
    with pytest.raises(EngineNotFoundError):
        resolve_engine(tmp_path, None)


def test_ignores_an_sdk_path_that_is_not_a_file(tmp_path: Path) -> None:
    """A settings entry left over from a deleted SDK resolves to nothing."""
    (tmp_path / "game").mkdir()
    with pytest.raises(EngineNotFoundError):
        resolve_engine(tmp_path, tmp_path / "gone" / "renpy.sh")
