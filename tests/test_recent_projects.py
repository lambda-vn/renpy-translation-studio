"""Tests for the global recent-projects registry."""

from pathlib import Path

from core.storage.recent_projects import RecentProjects


def test_all_missing_file_returns_empty(tmp_path: Path) -> None:
    repo = RecentProjects(tmp_path / "projects.json")
    assert repo.all() == []


def test_add_then_all_roundtrip(tmp_path: Path) -> None:
    repo = RecentProjects(tmp_path / "projects.json")
    project = tmp_path / "game_a"
    project.mkdir()
    repo.add(project)
    assert repo.all() == [project.resolve()]


def test_add_moves_existing_to_front(tmp_path: Path) -> None:
    repo = RecentProjects(tmp_path / "projects.json")
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    repo.add(first)
    repo.add(second)
    repo.add(first)
    assert repo.all() == [first.resolve(), second.resolve()]


def test_add_is_deduplicated(tmp_path: Path) -> None:
    repo = RecentProjects(tmp_path / "projects.json")
    project = tmp_path / "game"
    project.mkdir()
    repo.add(project)
    repo.add(project)
    assert repo.all() == [project.resolve()]


def test_remove_drops_entry(tmp_path: Path) -> None:
    repo = RecentProjects(tmp_path / "projects.json")
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    repo.add(first)
    repo.add(second)
    repo.remove(first)
    assert repo.all() == [second.resolve()]


def test_remove_absent_entry_is_noop(tmp_path: Path) -> None:
    repo = RecentProjects(tmp_path / "projects.json")
    project = tmp_path / "game"
    project.mkdir()
    repo.add(project)
    repo.remove(tmp_path / "never_added")
    assert repo.all() == [project.resolve()]


def test_corrupt_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    path.write_text("{ not json", encoding="utf-8")
    assert RecentProjects(path).all() == []


def test_non_list_json_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    path.write_text('{"foo": "bar"}', encoding="utf-8")
    assert RecentProjects(path).all() == []
