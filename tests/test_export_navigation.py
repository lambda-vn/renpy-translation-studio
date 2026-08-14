"""Guard the one way into the export screen.

ExportView shipped unreachable: review_view held a _navigate_export()
nothing called, and the stepper built its third step with a hardcoded
None where the other two take a callback. Every other guard stayed green,
the view being wired in main.py and importable like any other.

So the assertions here follow the click rather than the definitions: they
build what the review screen builds, find the export step in it and press
it. A callback dropped anywhere along that chain fails the test.
"""

from collections.abc import Iterator

import flet as ft

from app.components.stepper import build_stepper
from app.views.review_view import ReviewView
from core.i18n import i18n


def _buttons(control: object) -> Iterator[ft.TextButton]:
    """Yield every button of a control tree, the root included.

    Args:
        control: The control to walk, or anything holding one.

    Yields:
        Each TextButton found, in tree order.
    """
    if isinstance(control, ft.TextButton):
        yield control
    for child in getattr(control, "controls", None) or []:
        yield from _buttons(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _buttons(content)


def _export_button(tree: object, *, label_key: str) -> ft.TextButton | None:
    """Return the button leading forward to the export step, if any.

    Args:
        tree: The built control tree to search.
        label_key: i18n key of the export step label, which differs
            between the review and the export views.

    Returns:
        The button whose tooltip announces going to the export step, or
        None when that step was not built as a button at all.
    """
    tooltip = i18n.t("project_setup.step_go_to").format(step=i18n.t(label_key))
    return next((btn for btn in _buttons(tree) if btn.tooltip == tooltip), None)


class _StubReview:
    """The members ReviewView.build() reaches, and nothing else.

    Standing in for a real view, which wants a Flet page and a connected
    database that this has nothing to say about.
    """

    def __init__(self) -> None:
        self.navigated = False

    def _on_setup_step_clicked(self, _: object) -> None:
        """Record nothing: the back step has its own confirmation test."""

    def _navigate_export(self) -> None:
        """Stand in for the real navigation, which disposes the view."""
        self.navigated = True

    def _build_left_panel(self) -> ft.Control:
        """Return a placeholder for the file list panel."""
        return ft.Container()

    def _build_right_panel(self) -> ft.Control:
        """Return a placeholder for the review panel."""
        return ft.Column()


class _StubNavigation:
    """A view whose disposal and navigation are only recorded."""

    def __init__(self, *, blocked: bool) -> None:
        self._blocked = blocked
        self.calls: list[str] = []

    def _blocked_by_running_job(self) -> bool:
        """Answer what the test asked for, having warned nobody."""
        return self._blocked

    def dispose(self) -> None:
        """Record the disposal."""
        self.calls.append("dispose")

    def _on_export(self) -> None:
        """Record the navigation."""
        self.calls.append("export")


class TestExportStep:
    """The stepper's third step, which is the entry point."""

    def test_a_pending_export_step_navigates(self) -> None:
        clicked: list[bool] = []
        tree = build_stepper(2, on_export=lambda: clicked.append(True))

        button = _export_button(tree, label_key="project_setup.step_export")

        assert button is not None
        assert button.on_click is not None
        button.on_click(None)
        assert clicked == [True]

    def test_no_callback_leaves_the_step_unclickable(self) -> None:
        """A caller with nowhere to go must not get a dead button."""
        tree = build_stepper(2)

        assert _export_button(tree, label_key="project_setup.step_export") is None
        assert list(_buttons(tree)) == []

    def test_the_active_export_step_does_not_navigate_to_itself(self) -> None:
        """The export view itself passes no callback, and gets no button."""
        tree = build_stepper(3, on_export=lambda: None)

        assert _export_button(tree, label_key="project_setup.step_export") is None

    def test_a_completed_step_still_goes_back(self) -> None:
        """The forward step must not have changed what steps 1 and 2 do."""
        tree = build_stepper(2, on_setup=lambda: None)
        label = i18n.t("project_setup.step_setup")
        tooltip = i18n.t("project_setup.step_back_to").format(step=label)

        assert [btn.tooltip for btn in _buttons(tree)] == [tooltip]


class TestReviewViewReachesTheExportView:
    """The review screen, which is the only screen that can open it."""

    def test_the_stepper_it_builds_calls_navigate_export(self) -> None:
        stub = _StubReview()

        tree = ReviewView.build(stub)  # type: ignore[arg-type]

        button = _export_button(tree, label_key="review.step_export")
        assert button is not None
        assert button.on_click is not None
        button.on_click(None)
        assert stub.navigated

    def test_navigate_export_disposes_before_leaving(self) -> None:
        stub = _StubNavigation(blocked=False)

        ReviewView._navigate_export(stub)  # type: ignore[arg-type]

        assert stub.calls == ["dispose", "export"]

    def test_a_running_job_keeps_the_view(self) -> None:
        stub = _StubNavigation(blocked=True)

        ReviewView._navigate_export(stub)  # type: ignore[arg-type]

        assert stub.calls == []
