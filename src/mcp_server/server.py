"""The tools a client gets, one per action the application offers.

Everything a translation goes through in the review screen it goes
through here: a submission is quality-checked and refused on the same
grounds, and it lands in ai_suggested because a machine wrote it. The
screen stays where a human validates.

The read tools exist so the client can work like a translator rather
than a batch: which files are left, what surrounds a line, who says it,
and what the glossary says about them.

Paths are relative to the project root in both directions. Stored ones
are absolute, dating from the extraction, and repeating a user's disk
layout on every line of every page serves nobody.
"""

from pathlib import Path
from typing import TypedDict

from mcp.server import MCPServer

from core import project_actions
from core.live import notify, notify_reload
from core.storage.database import Database
from core.storage.repositories import TranslationStatus, TranslationUnit
from core.translation.quality import LENGTH_WARNING_KIND
from core.translation.quality import check as quality_check
from mcp_server.session import (
    UNIVERSE_SUMMARY_KEY,
    ProjectSession,
    ServerState,
    known_projects,
)

_CONTEXT_RADIUS = 2

_INSTRUCTIONS = """\
Translate a Ren'Py visual novel through the studio holding the project.

Start with list_projects and use_project, unless one is already open.
Then read a file's untranslated lines with list_units, ask
get_unit_context for what surrounds a line you are unsure of, and send
batches back with submit_translations.

Copy every {tag} and every [interpolation] of the source verbatim: a
submission that drops one, or that invents one the source did not have,
is refused. Never write an interpolation of your own, the engine runs
what is between square brackets as Python.

Translations land as suggestions. A human reviews them in the
application, and lines they already validated are left alone.\
"""


class TranslationSubmission(TypedDict):
    """One translated line on its way back to the project."""

    block_id: str
    translation: str


class SubmissionRejection(TypedDict):
    """One submission that was not applied, and why."""

    block_id: str
    reason: str


def _unit_payload(session: ProjectSession, unit: TranslationUnit) -> dict[str, object]:
    """Describe a unit for a client, keeping the fields it can act on."""
    return {
        "block_id": unit.block_id,
        "source_file": session.relative(unit.source_file),
        "source_line": unit.source_line,
        "speaker": unit.character_variable,
        "source_text": unit.source_text,
        "translated_text": unit.translated_text,
        "status": unit.status,
        "needs_review": unit.needs_review,
        "note": unit.note,
    }


def build_server(state: ServerState) -> MCPServer:
    """Wire every tool to one server state.

    Args:
        state: The permissions of the process and the project it holds.

    Returns:
        The server, ready to run over any transport.
    """
    mcp = MCPServer(
        name="renpy-translation-studio",
        instructions=_INSTRUCTIONS,
        version="0.1.0",
    )

    @mcp.tool()
    def list_projects() -> dict[str, object]:
        """List the games set up in the application on this machine.

        Returns:
            One entry per project, its folder name being what a user
            calls it, plus which one is open.
        """
        return {
            "projects": [
                {
                    "name": path.name,
                    "path": str(path),
                    "ready": Database.path_for(path).is_file(),
                }
                for path in known_projects()
            ],
            "open": None if state.current is None else str(state.current.path),
        }

    @mcp.tool()
    def use_project(project: str) -> dict[str, object]:
        """Open one of the games the application knows, by path.

        Args:
            project: The path as given by list_projects.

        Returns:
            What the project holds, so the next call needs no lookup.

        Raises:
            ProjectNotFoundError: If the path is not one the application
                set up, or holds no database.
        """
        session = state.use(Path(project))
        return {
            "open": str(session.path),
            "source_language": session.source_language,
            "target_language": session.target_language,
            "by_status": session.units.count_by_status(),
        }

    @mcp.tool()
    def list_files() -> dict[str, object]:
        """List the game's translatable files with their progress."""
        session = state.require()
        return {
            "files": [
                {**stats, "source_file": session.relative(stats["source_file"])}
                for stats in session.units.get_files()
            ]
        }

    @mcp.tool()
    def project_progress() -> dict[str, object]:
        """Report how much of the whole project is translated."""
        session = state.require()
        return {
            **session.units.project_progress(),
            "by_status": session.units.count_by_status(),
            "source_language": session.source_language,
            "target_language": session.target_language,
        }

    @mcp.tool()
    def list_units(
        source_file: str,
        status: str | None = None,
        search: str = "",
        speaker: str | None = None,
        needs_review: bool = False,
        page: int = 0,
        page_size: int = 50,
    ) -> dict[str, object]:
        """List one page of a file's lines, filtered like the review screen.

        Args:
            source_file: Path as returned by list_files.
            status: Keep only this status, e.g. 'not_translated'.
            search: Substring to look for in source or translation.
            speaker: Ren'Py character variable the lines belong to.
            needs_review: Keep only the lines flagged for a second look.
            page: Zero-based page index.
            page_size: Lines per page.

        Returns:
            The page's units, the total matching them, and the page asked
            for.
        """
        session = state.require()
        units, total = session.units.get_page(
            session.absolute(source_file),
            page,
            page_size,
            status_filter=status,
            search_query=search,
            character=speaker,
            needs_review=needs_review,
        )
        return {
            "units": [_unit_payload(session, unit) for unit in units],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @mcp.tool()
    def get_unit_context(block_id: str) -> dict[str, object]:
        """Show the lines surrounding one line, in file order.

        Args:
            block_id: Identifier of the line to centre on.

        Returns:
            The window around the line, the line itself included, plus
            the speaker's glossary entry when there is one.

        Raises:
            ValueError: If no line carries this identifier.
        """
        session = state.require()
        unit = _require_unit(session, block_id)
        window = session.units.get_neighbours(
            unit.source_file, unit.source_line, _CONTEXT_RADIUS
        )
        speaker = next(
            (
                character
                for character in session.characters.get_all()
                if character.variable == unit.character_variable
            ),
            None,
        )
        return {
            "unit": _unit_payload(session, unit),
            "window": [_unit_payload(session, other) for other in window],
            "speaker": None
            if speaker is None
            else {
                "variable": speaker.variable,
                "display_name": speaker.display_name,
                "notes": speaker.notes,
            },
            "universe_summary": session.meta.get(UNIVERSE_SUMMARY_KEY),
        }

    @mcp.tool()
    def submit_translations(
        items: list[TranslationSubmission],
    ) -> dict[str, object]:
        """Send translations back, one batch at a time.

        Each is checked the way the review screen checks a human's: a
        lost {tag} or [interpolation], one invented, an HTML tag. A
        refused line is reported rather than written, and the rest of the
        batch still applies.

        Args:
            items: Pairs of block_id and translation.

        Returns:
            How many were applied, and every rejection with its reason.
        """
        session = state.require()
        known = {unit.block_id: unit for unit in session.units.get_all()}
        accepted: list[tuple[str, str, TranslationStatus]] = []
        rejected: list[SubmissionRejection] = []

        for item in items:
            block_id = item["block_id"]
            translation = item["translation"]
            unit = known.get(block_id)
            if unit is None:
                rejected.append({"block_id": block_id, "reason": "Unknown block_id."})
                continue
            if not translation.strip():
                rejected.append({"block_id": block_id, "reason": "Empty translation."})
                continue
            issues = [
                issue.detail
                for issue in quality_check(unit.source_text, translation)
                if issue.kind != LENGTH_WARNING_KIND
            ]
            if issues:
                rejected.append({"block_id": block_id, "reason": " ".join(issues)})
                continue
            if unit.status == "human_validated":
                if not state.allow_overwrite_validated:
                    rejected.append(
                        {
                            "block_id": block_id,
                            "reason": "Validated by a human. The server was "
                            "not started with --allow-overwrite-validated.",
                        }
                    )
                    continue
                session.units.mark_as_draft(block_id, translation)
                continue
            accepted.append((block_id, translation, "ai_suggested"))

        applied = session.units.update_translations(accepted)
        notify(session.path, [block_id for block_id, _, _ in accepted])
        return {"applied": applied, "rejected": rejected}

    @mcp.tool()
    def set_note(block_id: str, note: str) -> dict[str, object]:
        """Leave a note on a line and flag it for a second look.

        The flag comes with the note because the review screen only shows
        a note on a flagged line: writing one without it would leave it
        where nobody reads it.

        Args:
            block_id: Identifier of the line.
            note: What to say about it; an empty note clears both.

        Returns:
            The line as it now stands.
        """
        session = state.require()
        _require_unit(session, block_id)
        session.units.set_note(block_id, note)
        session.units.set_needs_review(block_id, bool(note.strip()))
        notify(session.path, [block_id])
        return _unit_payload(session, _require_unit(session, block_id))

    @mcp.tool()
    def set_needs_review(block_id: str, needs_review: bool) -> dict[str, object]:
        """Flag a line for a second look, or clear the flag.

        Args:
            block_id: Identifier of the line.
            needs_review: True to flag it, False to clear it.

        Returns:
            The line as it now stands.
        """
        session = state.require()
        _require_unit(session, block_id)
        session.units.set_needs_review(block_id, needs_review)
        notify(session.path, [block_id])
        return _unit_payload(session, _require_unit(session, block_id))

    @mcp.tool()
    def fill_from_memory() -> dict[str, object]:
        """Fill untranslated lines the shared memory already answers for.

        Exact matches only, taken from the translations validated by hand
        in other projects. Nothing already translated is touched.

        Returns:
            How many lines were filled.
        """
        session = state.require()
        filled = project_actions.fill_from_memory(
            session.units,
            source_language=session.source_language,
            target_language=session.target_language,
        )
        if filled:
            notify_reload(session.path)
        return {"filled": filled}

    @mcp.tool()
    def detect_characters() -> dict[str, object]:
        """Scan the game's sources for Character() definitions and store them.

        Returns:
            How many the scan found, and the glossary as it now stands.
        """
        session = state.require()
        found = project_actions.detect_and_store_characters(
            session.characters, session.path
        )
        return {"found": found, "characters": _characters(session)}

    @mcp.tool()
    def list_characters() -> dict[str, object]:
        """List the character glossary."""
        return {"characters": _characters(state.require())}

    @mcp.tool()
    def upsert_character(
        variable: str, display_name: str, notes: str | None = None
    ) -> dict[str, object]:
        """Add a character or rename one, and optionally set its notes.

        Notes are what providers read for gender, register and how a name
        must be translated. They are left untouched when not given, being
        the field no scan produces.

        Args:
            variable: The Ren'Py variable the character is defined as.
            display_name: The name shown to players.
            notes: Free-form notes, or None to leave them as they are.

        Returns:
            The glossary as it now stands.
        """
        session = state.require()
        session.characters.upsert(variable, display_name)
        if notes is not None:
            session.characters.update_notes(variable, notes)
        return {"characters": _characters(session)}

    @mcp.tool()
    def delete_character(variable: str) -> dict[str, object]:
        """Remove a character from the glossary.

        Args:
            variable: The Ren'Py variable identifying the character.

        Returns:
            The glossary as it now stands.
        """
        session = state.require()
        session.characters.delete(variable)
        return {"characters": _characters(session)}

    @mcp.tool()
    def get_universe_summary() -> dict[str, object]:
        """Read the free-form description of the game's setting."""
        return {"summary": state.require().meta.get(UNIVERSE_SUMMARY_KEY)}

    @mcp.tool()
    def set_universe_summary(summary: str) -> dict[str, object]:
        """Replace the description of the game's setting.

        It is sent to providers ahead of every batch, so it earns its
        length: a few sentences on the tone, the period and the relations
        between characters.

        Args:
            summary: The new description; an empty string clears it.

        Returns:
            The summary as stored.
        """
        session = state.require()
        session.meta.set(UNIVERSE_SUMMARY_KEY, summary)
        return {"summary": session.meta.get(UNIVERSE_SUMMARY_KEY)}

    @mcp.tool()
    def clear_translations(
        source_file: str | None = None,
        statuses: list[str] | None = None,
    ) -> dict[str, object]:
        """Delete translations in bulk, back to not_translated.

        Refused unless the server was started with --allow-clear, this
        being the one tool that destroys work in a single call.

        Args:
            source_file: Limit to one file; the whole project otherwise.
            statuses: Limit to these statuses, e.g. ['ai_suggested'] to
                drop a bad run without touching reviewed work.

        Returns:
            How many lines were cleared.

        Raises:
            ValueError: If the server was not started with --allow-clear.
        """
        session = state.require()
        if not state.allow_clear:
            raise ValueError("Refused: the server was not started with --allow-clear.")
        cleared = session.units.clear_translations(
            source_file=None if source_file is None else session.absolute(source_file),
            statuses=None if statuses is None else _as_statuses(statuses),
        )
        if cleared:
            notify_reload(session.path)
        return {"cleared": cleared}

    return mcp


def _characters(session: ProjectSession) -> list[dict[str, object]]:
    """Describe the whole glossary for a client."""
    return [
        {
            "variable": character.variable,
            "display_name": character.display_name,
            "notes": character.notes,
        }
        for character in session.characters.get_all()
    ]


def _require_unit(session: ProjectSession, block_id: str) -> TranslationUnit:
    """Return one unit by identifier.

    Args:
        session: The open project.
        block_id: Identifier to look for.

    Returns:
        The matching unit.

    Raises:
        ValueError: If no line carries this identifier.
    """
    for unit in session.units.get_all():
        if unit.block_id == block_id:
            return unit
    raise ValueError(f"Unknown block_id: {block_id}")


def _as_statuses(statuses: list[str]) -> list[TranslationStatus]:
    """Check that a client's status names are ones the schema allows.

    Args:
        statuses: Status names as received.

    Returns:
        The same names, typed.

    Raises:
        ValueError: If one of them is not a status.
    """
    allowed: set[str] = {
        "not_translated",
        "draft",
        "imported",
        "ai_suggested",
        "human_validated",
    }
    unknown = sorted(set(statuses) - allowed)
    if unknown:
        raise ValueError(f"Unknown status: {', '.join(unknown)}")
    return [status for status in statuses]  # type: ignore[misc]
