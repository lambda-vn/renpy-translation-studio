"""Tests for the review snapshot kept in app/state.py."""

from pathlib import Path

from app.state import AppState, ReviewViewState
from app.views.review_view import _filter_key


class TestReviewStatePersistence:
    """What survives leaving the review screen, and what must not."""

    def test_snapshot_survives_a_round_trip(self) -> None:
        state = AppState(project_path=Path("/games/one"))
        snapshot = state.review_state()
        snapshot.status_filter = "ai_suggested"
        snapshot.selected_file = "game/script.rpy"
        snapshot.current_page = 3
        snapshot.search_query = "love"

        again = state.review_state()

        assert again.status_filter == "ai_suggested"
        assert again.selected_file == "game/script.rpy"
        assert again.current_page == 3
        assert again.search_query == "love"

    def test_another_project_starts_from_the_defaults(self) -> None:
        state = AppState(project_path=Path("/games/one"))
        state.review_state().selected_file = "game/script.rpy"

        state.project_path = Path("/games/two")
        snapshot = state.review_state()

        assert snapshot.selected_file is None
        assert snapshot.current_page == 0
        assert snapshot.status_filter == "not_translated"

    def test_returning_to_the_first_project_does_not_restore_it(self) -> None:
        """A snapshot is dropped when the project changes, not parked."""
        state = AppState(project_path=Path("/games/one"))
        state.review_state().selected_file = "game/script.rpy"
        state.project_path = Path("/games/two")
        state.review_state()

        state.project_path = Path("/games/one")

        assert state.review_state().selected_file is None

    def test_default_filter_is_the_untranslated_lines(self) -> None:
        assert AppState().review_state().status_filter == "not_translated"


class TestFilterKey:
    """Putting the toolbar dropdown back on a restored filter."""

    def test_status_filter(self) -> None:
        assert _filter_key(ReviewViewState(status_filter="human_validated")) == (
            "human_validated"
        )

    def test_no_filter(self) -> None:
        assert _filter_key(ReviewViewState(status_filter=None)) == ""

    def test_errors_replace_the_status(self) -> None:
        state = ReviewViewState(status_filter=None, errors_only=True)
        assert _filter_key(state) == "blocking_error"

    def test_review_flag_replaces_the_status(self) -> None:
        state = ReviewViewState(status_filter=None, review_only=True)
        assert _filter_key(state) == "needs_review"
