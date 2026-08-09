"""Tests for the desktop file manager helper."""

import subprocess
from pathlib import Path

import pytest

from core.file_reveal import RevealError, _reveal_command, reveal_in_file_manager


def test_windows_command_selects_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.file_reveal.sys.platform", "win32")
    command = _reveal_command(Path(r"C:\game\tl\french\script.rpy"))
    assert command == ["explorer", r"/select,C:\game\tl\french\script.rpy"]


def test_macos_command_selects_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.file_reveal.sys.platform", "darwin")
    target = Path("/game/tl/french/script.rpy")
    assert _reveal_command(target) == ["open", "-R", str(target)]


def test_linux_command_asks_dbus_to_select_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("core.file_reveal.sys.platform", "linux")
    target = tmp_path / "script.rpy"
    command = _reveal_command(target)
    assert command[0] == "dbus-send"
    assert command[-2] == f"array:string:{target.as_uri()}"


def test_reveal_runs_without_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.file_reveal.sys.platform", "win32")
    target = tmp_path / "script.rpy"
    target.write_text("", encoding="utf-8")
    calls: list[tuple[list[str], bool]] = []

    def _fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, bool(kwargs["shell"])))
        return subprocess.CompletedProcess(args=command, returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    reveal_in_file_manager(target)

    assert len(calls) == 1
    command, shell = calls[0]
    assert shell is False
    assert command == _reveal_command(target)


def test_reveal_ignores_a_non_zero_return_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.file_reveal.sys.platform", "win32")
    target = tmp_path / "script.rpy"
    target.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=1),
    )
    reveal_in_file_manager(target)


def test_reveal_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RevealError):
        reveal_in_file_manager(tmp_path / "gone.rpy")


def test_reveal_reports_a_missing_file_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.file_reveal.sys.platform", "win32")
    target = tmp_path / "script.rpy"
    target.write_text("", encoding="utf-8")

    def _raise(*_a: object, **_k: object) -> None:
        raise OSError("file manager not found")

    monkeypatch.setattr(subprocess, "run", _raise)
    with pytest.raises(RevealError):
        reveal_in_file_manager(target)


def test_linux_reveal_uses_dbus_when_a_file_manager_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.file_reveal.sys.platform", "linux")
    target = tmp_path / "script.rpy"
    target.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def _fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(args=command, returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    reveal_in_file_manager(target)

    assert len(calls) == 1
    assert calls[0][0] == "dbus-send"


def test_linux_reveal_falls_back_to_xdg_open_when_dbus_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.file_reveal.sys.platform", "linux")
    target = tmp_path / "script.rpy"
    target.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def _fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(args=command, returncode=1)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    reveal_in_file_manager(target)

    assert len(calls) == 2
    assert calls[0][0] == "dbus-send"
    assert calls[1] == ["xdg-open", str(target.parent)]


def test_linux_reveal_falls_back_to_xdg_open_when_dbus_send_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.file_reveal.sys.platform", "linux")
    target = tmp_path / "script.rpy"
    target.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def _fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        if command[0] == "dbus-send":
            raise OSError("dbus-send not found")
        calls.append(command)
        return subprocess.CompletedProcess(args=command, returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    reveal_in_file_manager(target)

    assert calls == [["xdg-open", str(target.parent)]]


def test_linux_reveal_reports_a_missing_file_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.file_reveal.sys.platform", "linux")
    target = tmp_path / "script.rpy"
    target.write_text("", encoding="utf-8")

    def _raise(*_a: object, **_k: object) -> subprocess.CompletedProcess[bytes]:
        raise OSError("no file manager available")

    monkeypatch.setattr(subprocess, "run", _raise)
    with pytest.raises(RevealError):
        reveal_in_file_manager(target)
