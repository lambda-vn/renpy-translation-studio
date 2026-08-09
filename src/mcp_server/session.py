"""What the server holds: the permissions, and the project in hand.

One process serves whichever project the client asks for, chosen among
the ones already set up in the application. The permissions belong to the
process and never to a call: a client reads the game's own text, so a
line of dialogue asking for every validated translation to be dropped
would otherwise be a request the model is free to grant itself.

The same rule explains why use_project() only accepts a project the
registry already knows. The application writes that registry when a
human sets a game up, so the reachable set is one the user built, not one
the model names.
"""

from dataclasses import dataclass, field
from pathlib import Path

from core.storage.database import Database
from core.storage.recent_projects import recent_projects
from core.storage.repositories import (
    CharacterRepository,
    ProjectMetaRepository,
    TranslationUnitRepository,
)

UNIVERSE_SUMMARY_KEY = "universe_summary"


class ProjectNotFoundError(FileNotFoundError):
    """Raised when a path holds no database this server can serve."""


class NoProjectOpenError(RuntimeError):
    """Raised when a tool needing a project is called before one is opened."""


@dataclass
class ProjectSession:
    """An open project and the repositories reading it.

    Attributes:
        path: The Ren'Py project root.
        db: The open database, closed by close().
        units: Translation units of this project.
        characters: Character glossary of this project.
        meta: Key/value metadata, holding the languages and the universe
            summary.
    """

    path: Path
    db: Database
    units: TranslationUnitRepository
    characters: CharacterRepository
    meta: ProjectMetaRepository

    @property
    def source_language(self) -> str:
        """Language the game is written in, English when unrecorded."""
        return self.meta.get("source_language") or "english"

    @property
    def target_language(self) -> str:
        """Language being translated into, empty when unrecorded."""
        return self.meta.get("target_language") or ""

    def relative(self, source_file: str) -> str:
        """Shorten a stored path to what it is under the project root.

        Files are stored with the absolute path they had when the game
        was extracted. Sent as they are, they repeat the user's disk
        layout on every line of every page, and they are wrong as soon as
        the project moves.

        Args:
            source_file: The path as stored.

        Returns:
            The path relative to the project root, or the stored one when
            it lies elsewhere.
        """
        try:
            return Path(source_file).relative_to(self.path).as_posix()
        except ValueError:
            return source_file

    def absolute(self, source_file: str) -> str:
        """Turn a path a client sent back into the one the database holds.

        Accepts both forms, a client having no reason to know which one
        it was given.

        Args:
            source_file: A relative or absolute path.

        Returns:
            The path as the database stores it.
        """
        candidate = Path(source_file)
        if candidate.is_absolute():
            return source_file
        return str(self.path / candidate)

    def close(self) -> None:
        """Release the database connection."""
        self.db.close()


@dataclass
class ServerState:
    """The permissions of the process and the project currently open.

    Attributes:
        allow_overwrite_validated: Whether a submission may replace a
            line a human validated.
        allow_clear: Whether translations may be deleted in bulk.
        pinned: A project given on the command line, opened at startup
            and the only one reachable when set.
        current: The project in hand, None until one is opened.
    """

    allow_overwrite_validated: bool = False
    allow_clear: bool = False
    pinned: Path | None = None
    current: ProjectSession | None = field(default=None)

    def require(self) -> ProjectSession:
        """Return the open project.

        Returns:
            The project in hand.

        Raises:
            NoProjectOpenError: If no project is open yet.
        """
        if self.current is None:
            raise NoProjectOpenError(
                "No project open. Call list_projects to see the games set up "
                "in the application, then use_project to pick one."
            )
        return self.current

    def use(self, project: Path) -> ProjectSession:
        """Open a project, closing the one held before it.

        Args:
            project: The Ren'Py project root.

        Returns:
            The newly opened project.

        Raises:
            ProjectNotFoundError: If the path is not a known project or
                holds no database.
        """
        target = project.resolve()
        if self.pinned is not None and target != self.pinned:
            raise ProjectNotFoundError(
                f"This server was started pinned to {self.pinned}. "
                f"Restart it without --project to reach other projects."
            )
        if self.pinned is None and target not in known_projects():
            raise ProjectNotFoundError(
                f"{target} is not a project this server can open. Set it up "
                f"in the application first; list_projects shows the ones it "
                f"already knows."
            )

        session = open_project(target)
        self.close()
        self.current = session
        return session

    def close(self) -> None:
        """Release whatever project is held."""
        if self.current is not None:
            self.current.close()
            self.current = None


def known_projects() -> list[Path]:
    """List the projects the application has set up on this machine.

    Returns:
        The resolved roots, most recent first, whether or not each still
        holds a database.
    """
    return [path.resolve() for path in recent_projects.all()]


def open_project(project: Path) -> ProjectSession:
    """Open a project set up by the application.

    The database is never created here. A missing one means the path is
    not a project the application has extracted yet, and answering an
    empty project would look like a game with nothing to translate.

    Args:
        project: The Ren'Py project root.

    Returns:
        The open session.

    Raises:
        ProjectNotFoundError: If the project holds no database.
    """
    db_path = Database.path_for(project)
    if not db_path.is_file():
        raise ProjectNotFoundError(
            f"No project database at {db_path}. Open this game in the "
            f"application and extract it once first."
        )

    db = Database(db_path)
    db.connect()
    return ProjectSession(
        path=project,
        db=db,
        units=TranslationUnitRepository(db.conn, db.lock),
        characters=CharacterRepository(db.conn, db.lock),
        meta=ProjectMetaRepository(db.conn, db.lock),
    )
