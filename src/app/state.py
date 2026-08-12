"""Global application state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.renpy.parser import TranslationBlock
from core.storage.database import Database
from core.storage.repositories import FileStats, TranslationUnit


@dataclass
class ReviewViewState:
    """What the review screen is currently showing.

    Lives here rather than inside the view because leaving the review,
    for the provider settings or the character glossary, destroys the
    view and builds a new one on the way back. Kept inside, the filter,
    the open file, the page and the search all went back to their
    defaults on every round trip, which on a long script means finding
    one's place again after a two-click detour.

    current_units and file_stats are caches, rebuilt by the first load of
    the new view; they are here only because they belong to the same
    snapshot.
    """

    selected_file: str | None = None
    current_page: int = 0
    status_filter: str | None = "not_translated"
    character_filter: str | None = None
    errors_only: bool = False
    review_only: bool = False
    search_query: str = ""
    current_units: list[TranslationUnit] = field(default_factory=list)
    total_units: int = 0
    file_stats: dict[str, FileStats] = field(default_factory=dict)


@dataclass
class AppState:
    """Shared mutable state passed between views."""

    project_path: Path | None = None
    source_language: str = "english"
    target_language: str = ""
    sdk_path: str = ""
    game_name: str = ""
    blocks: list[TranslationBlock] = field(default_factory=list)
    tl_output_dir: Path | None = None
    db: Database | None = None
    review: ReviewViewState = field(default_factory=ReviewViewState)
    review_project: Path | None = None

    def review_state(self) -> ReviewViewState:
        """Return the review snapshot of the project being worked on.

        Tied to the project rather than reset by whoever opens one: a
        file name and a page number mean nothing in another game, and
        the paths that open a project are not the only ones that ever
        will be. Comparing here is what keeps a stale snapshot from
        outliving the project it describes without every future caller
        having to remember to clear it.

        Returns:
            The stored snapshot, or a fresh one when the open project is
            not the one it was taken from.
        """
        if self.review_project != self.project_path:
            self.review = ReviewViewState()
            self.review_project = self.project_path
        return self.review
