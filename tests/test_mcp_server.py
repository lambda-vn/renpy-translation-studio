"""Tests for the MCP server exposing the projects of a machine.

The tools are closures built by build_server(), so they are called the
way a client calls them, through call_tool(). That also covers the
schemas the SDK derives from their signatures, which a direct call would
skip.

anyio drives the coroutines rather than pytest-asyncio: it already comes
with the MCP SDK, and the suite has no other async test to justify a
plugin.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from core.storage.database import Database
from mcp_server import server as server_module
from mcp_server import session as session_module
from mcp_server.server import build_server
from mcp_server.session import (
    ProjectNotFoundError,
    ServerState,
    open_project,
)

_SCRIPT = "game/script.rpy"


def _unit(root: Path, block_id: str, source_text: str, line: int) -> dict[str, object]:
    """Build a unit carrying an absolute path, the way extraction stores it."""
    return {
        "block_id": block_id,
        "source_file": str(root / _SCRIPT),
        "source_line": line,
        "character_variable": "e",
        "source_text": source_text,
    }


def _make_project(root: Path) -> None:
    """Create an extracted project holding three lines."""
    db_path = Database.path_for(root)
    db_path.parent.mkdir(parents=True)
    db = Database(db_path)
    db.connect()
    db.close()

    opened = open_project(root)
    opened.units.bulk_insert(
        [
            _unit(root, "a", "Hello there.", 1),
            _unit(root, "b", "How are you, [player_name]?", 2),
            _unit(root, "c", "{i}Goodbye.{/i}", 3),
        ]
    )
    opened.meta.set("source_language", "english")
    opened.meta.set("target_language", "french")
    opened.close()


@pytest.fixture()
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ServerState]:
    """Provide a server holding one open project, registry included."""
    root = tmp_path / "game-one"
    root.mkdir()
    _make_project(root)
    registry = [root.resolve()]
    monkeypatch.setattr(session_module, "known_projects", lambda: registry)
    monkeypatch.setattr(server_module, "known_projects", lambda: registry)

    server_state = ServerState()
    server_state.use(root)
    yield server_state
    server_state.close()


def _call(state: ServerState, name: str, **arguments: Any) -> Any:
    """Call one tool the way a client would and return its payload."""
    server = build_server(state)

    async def _run() -> Any:
        result = await server.call_tool(name, arguments)
        return result.structured_content

    return anyio.run(_run)


def test_every_tool_is_advertised(state: ServerState) -> None:
    """The client must see the whole surface, names included."""
    names = {tool.name for tool in anyio.run(build_server(state).list_tools)}
    assert {
        "list_projects",
        "use_project",
        "list_files",
        "list_units",
        "get_unit_context",
        "project_progress",
        "submit_translations",
        "set_note",
        "set_needs_review",
        "fill_from_memory",
        "detect_characters",
        "list_characters",
        "upsert_character",
        "delete_character",
        "get_universe_summary",
        "set_universe_summary",
        "clear_translations",
    } <= names


def test_a_tool_without_a_project_says_what_to_call(tmp_path: Path) -> None:
    """The error has to name the way out, a client having no other clue."""
    with pytest.raises(ToolError, match="list_projects"):
        _call(ServerState(), "list_files")


def test_use_project_refuses_a_path_the_application_never_set_up(
    state: ServerState, tmp_path: Path
) -> None:
    """A model must not be able to name any folder on the disk.

    The registry is written by the application when a human sets a game
    up, so what is reachable is what the user built.
    """
    stranger = tmp_path / "elsewhere"
    stranger.mkdir()

    with pytest.raises(ToolError):
        _call(state, "use_project", project=str(stranger))


def test_list_projects_answers_from_the_registry(state: ServerState) -> None:
    payload = _call(state, "list_projects")

    assert [entry["name"] for entry in payload["projects"]] == ["game-one"]
    assert payload["projects"][0]["ready"] is True
    assert payload["open"].endswith("game-one")


def test_a_pinned_server_refuses_every_other_project(tmp_path: Path) -> None:
    root = tmp_path / "pinned"
    root.mkdir()
    _make_project(root)
    pinned = ServerState(pinned=root.resolve())
    pinned.use(root)

    with pytest.raises(ProjectNotFoundError, match="pinned"):
        pinned.use(tmp_path / "other")

    pinned.close()


def test_paths_are_relative_to_the_project(state: ServerState) -> None:
    """A stored path repeats the user's disk layout on every line."""
    payload = _call(state, "list_files")

    assert [entry["source_file"] for entry in payload["files"]] == [_SCRIPT]


def test_list_units_accepts_the_relative_path_it_gave(state: ServerState) -> None:
    payload = _call(state, "list_units", source_file=_SCRIPT, status="not_translated")

    assert payload["total"] == 3
    assert [unit["block_id"] for unit in payload["units"]] == ["a", "b", "c"]
    assert payload["units"][0]["source_file"] == _SCRIPT


def test_submit_translations_lands_as_a_suggestion(state: ServerState) -> None:
    payload = _call(
        state,
        "submit_translations",
        items=[{"block_id": "a", "translation": "Bonjour."}],
    )

    unit = next(u for u in state.require().units.get_all() if u.block_id == "a")
    assert payload["applied"] == 1
    assert payload["rejected"] == []
    assert unit.translated_text == "Bonjour."
    assert unit.status == "ai_suggested"


def test_submit_translations_refuses_an_injected_interpolation(
    state: ServerState,
) -> None:
    """The tool must refuse what the review screen refuses.

    Ren'Py runs what stands between square brackets, and this is the one
    input a client can be talked into producing by the game's own text.
    """
    payload = _call(
        state,
        "submit_translations",
        items=[
            {"block_id": "a", "translation": "Bonjour [__import__('os').system('id')]."}
        ],
    )

    unit = next(u for u in state.require().units.get_all() if u.block_id == "a")
    assert payload["applied"] == 0
    assert payload["rejected"][0]["block_id"] == "a"
    assert unit.status == "not_translated"


def test_submit_translations_refuses_a_dropped_interpolation(
    state: ServerState,
) -> None:
    payload = _call(
        state,
        "submit_translations",
        items=[{"block_id": "b", "translation": "Comment vas-tu ?"}],
    )

    assert payload["applied"] == 0
    assert payload["rejected"][0]["block_id"] == "b"


def test_submit_translations_applies_the_rest_of_a_batch(state: ServerState) -> None:
    payload = _call(
        state,
        "submit_translations",
        items=[
            {"block_id": "a", "translation": "Bonjour."},
            {"block_id": "zzz", "translation": "Inconnu."},
            {"block_id": "c", "translation": "{i}Au revoir.{/i}"},
        ],
    )

    assert payload["applied"] == 2
    assert [r["block_id"] for r in payload["rejected"]] == ["zzz"]


def test_submit_translations_spares_a_validated_line(state: ServerState) -> None:
    state.require().units.update_translation("a", "Salut.", "human_validated")

    payload = _call(
        state,
        "submit_translations",
        items=[{"block_id": "a", "translation": "Bonjour."}],
    )

    unit = next(u for u in state.require().units.get_all() if u.block_id == "a")
    assert payload["applied"] == 0
    assert unit.translated_text == "Salut."
    assert unit.status == "human_validated"


def test_submit_translations_overwrites_a_validated_line_when_allowed(
    state: ServerState,
) -> None:
    """The permission lives on the command line, never in the call.

    A client reads the game's text, so a line of dialogue asking for this
    must not be able to grant it.
    """
    state.require().units.update_translation("a", "Salut.", "human_validated")
    state.allow_overwrite_validated = True

    _call(
        state,
        "submit_translations",
        items=[{"block_id": "a", "translation": "Bonjour."}],
    )

    unit = next(u for u in state.require().units.get_all() if u.block_id == "a")
    assert unit.translated_text == "Bonjour."
    assert unit.status == "draft"


def test_clear_translations_is_refused_by_default(state: ServerState) -> None:
    state.require().units.update_translation("a", "Bonjour.", "ai_suggested")

    with pytest.raises(ToolError, match="--allow-clear"):
        _call(state, "clear_translations")

    unit = next(u for u in state.require().units.get_all() if u.block_id == "a")
    assert unit.translated_text == "Bonjour."


def test_clear_translations_runs_when_allowed(state: ServerState) -> None:
    state.require().units.update_translation("a", "Bonjour.", "ai_suggested")
    state.allow_clear = True

    payload = _call(state, "clear_translations", statuses=["ai_suggested"])

    unit = next(u for u in state.require().units.get_all() if u.block_id == "a")
    assert payload["cleared"] == 1
    assert unit.status == "not_translated"


def test_set_note_flags_the_line(state: ServerState) -> None:
    """A note on an unflagged line would sit where the screen never shows it."""
    payload = _call(state, "set_note", block_id="a", note="Pun, needs a second look.")

    assert payload["note"] == "Pun, needs a second look."
    assert payload["needs_review"] is True


def test_set_note_clears_the_flag_when_emptied(state: ServerState) -> None:
    _call(state, "set_note", block_id="a", note="Something")
    payload = _call(state, "set_note", block_id="a", note="")

    assert payload["needs_review"] is False


def test_get_unit_context_answers_with_the_surrounding_lines(
    state: ServerState,
) -> None:
    session = state.require()
    session.characters.upsert("e", "Eileen")
    session.characters.update_notes("e", "female, informal")
    session.meta.set("universe_summary", "A school story.")

    payload = _call(state, "get_unit_context", block_id="b")

    assert payload["unit"]["block_id"] == "b"
    assert [u["block_id"] for u in payload["window"]] == ["a", "b", "c"]
    assert payload["speaker"]["notes"] == "female, informal"
    assert payload["universe_summary"] == "A school story."


def test_upsert_character_leaves_the_notes_alone(state: ServerState) -> None:
    _call(state, "upsert_character", variable="e", display_name="Eileen")
    _call(state, "upsert_character", variable="e", display_name="Eileen", notes="shy")
    payload = _call(state, "upsert_character", variable="e", display_name="Eileen R.")

    entry = next(c for c in payload["characters"] if c["variable"] == "e")
    assert entry["display_name"] == "Eileen R."
    assert entry["notes"] == "shy"


def test_universe_summary_round_trip(state: ServerState) -> None:
    _call(state, "set_universe_summary", summary="A rainy port town.")

    assert _call(state, "get_universe_summary")["summary"] == "A rainy port town."


def test_open_project_refuses_a_path_without_a_database(tmp_path: Path) -> None:
    with pytest.raises(ProjectNotFoundError):
        open_project(tmp_path / "not-a-project")
