"""Shared three-step progress bar: Setup -> Review -> Export."""

from collections.abc import Callable

import flet as ft

from app import theme
from app.theme import border_all, focusable
from core.i18n import i18n


def _circle(number: int, *, active: bool, done: bool) -> ft.Container:
    """Build a single numbered stepper circle.

    Args:
        number: Step number shown when the step is not completed.
        active: Whether this step is the current one.
        done: Whether this step is completed.

    Returns:
        A styled circle Container.
    """
    icon: ft.Control
    if done:
        icon = ft.Icon(
            ft.Icons.CHECK,
            color=theme.ACCENT,
            size=14,
            semantics_label=i18n.t("project_setup.step_done"),
        )
        bg = theme.STEP_DONE_BG
        border: ft.Border | None = None
    elif active:
        icon = ft.Text(
            str(number), color=theme.ACCENT_ON, size=13, weight=ft.FontWeight.W_600
        )
        bg = theme.ACCENT
        border = None
    else:
        icon = ft.Text(
            str(number), color=theme.TEXT_HINT, size=13, weight=ft.FontWeight.W_600
        )
        bg = "transparent"
        border = border_all(1.5, theme.STEP_TODO_BORDER)
    return ft.Container(
        content=icon,
        width=30,
        height=30,
        border_radius=15,
        bgcolor=bg,
        border=border,
        alignment=ft.Alignment(x=0, y=0),
    )


def _step(
    number: int,
    label_key: str,
    active_step: int,
    on_click: Callable[[], None] | None,
) -> ft.Control:
    """Build one step (circle plus label), clickable when it navigates.

    Args:
        number: Step number (1, 2 or 3).
        label_key: i18n key for the step label.
        active_step: The currently active step.
        on_click: Navigation callback, wired for every step but the
            current one. A completed step goes back, a pending one goes
            forward, and the tooltip says which.

    Returns:
        A Row, or a focusable button wrapping it for navigable steps.
    """
    done = number < active_step
    active = number == active_step
    if done:
        label_color = theme.TEXT_MUTED
    elif active:
        label_color = theme.TEXT
    else:
        label_color = theme.TEXT_HINT
    label = i18n.t(label_key)
    row = ft.Row(
        [
            _circle(number, active=active, done=done),
            ft.Text(
                label,
                size=14,
                weight=ft.FontWeight.W_600,
                color=label_color,
            ),
        ],
        spacing=11,
        tight=True,
    )
    if on_click is not None and not active:
        if done:
            tooltip = i18n.t("project_setup.step_back_to")
        else:
            tooltip = i18n.t("project_setup.step_go_to")
        return focusable(
            ft.Container(content=row, ink=True, border_radius=8),
            on_click=lambda _e: on_click(),
            tooltip=tooltip.format(step=label),
        )
    return row


def _connector(*, done: bool) -> ft.Container:
    """Build the horizontal line between two steps.

    Args:
        done: Whether the step on the left is completed.

    Returns:
        A thin Container colored to reflect progress.
    """
    return ft.Container(
        expand=True,
        height=2,
        border_radius=2,
        bgcolor=theme.ACCENT if done else theme.BORDER_SUBTLE,
    )


def build_stepper(
    active_step: int,
    *,
    on_setup: Callable[[], None] | None = None,
    on_review: Callable[[], None] | None = None,
    on_export: Callable[[], None] | None = None,
    export_label_key: str = "project_setup.step_export",
) -> ft.Container:
    """Build the three-step progress bar shown at the top of each main view.

    Args:
        active_step: The current step (1 = Setup, 2 = Review, 3 = Export).
        on_setup: Navigation callback for the Setup step, wired only once
            that step is completed.
        on_review: Navigation callback for the Review step, wired only once
            that step is completed.
        on_export: Navigation callback for the Export step. This one leads
            forward rather than back, and it is the only way into the
            export screen: nothing else in the review view opens it.
        export_label_key: i18n key for the Export step label, which differs
            between the review and export views.

    Returns:
        A Container spanning the page width with the stepper row.
    """
    return ft.Container(
        content=ft.Row(
            [
                _step(1, "project_setup.step_setup", active_step, on_setup),
                _connector(done=active_step > 1),
                _step(2, "project_setup.step_review", active_step, on_review),
                _connector(done=active_step > 2),
                _step(3, export_label_key, active_step, on_export),
            ],
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(left=40, right=40, top=22, bottom=18),
        border=ft.Border(bottom=ft.BorderSide(1, theme.BORDER)),
    )
