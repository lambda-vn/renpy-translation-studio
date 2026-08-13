"""Active colour palette, border helper and focus wrapper for the UI.

The colours themselves are declared in app.palettes, one Palette per
theme. This module holds the one that is currently applied and exposes it
under names every view reads:

    from app import theme
    ...
    bgcolor=theme.BG_MENU

Import the module, never the names. `from app.theme import BG_MENU` binds
the string at import time, and switching theme would leave that module
drawing the previous palette until the process restarts.

Switching is modelled on core.i18n: a setter that rebinds, then notifies
listeners which rebuild what is on screen.
"""

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import flet as ft

from app import palettes
from core.settings import settings

# Every name below is rebound by _bind(). They are assigned rather than
# merely annotated because an annotation alone leaves the name unbound for
# ruff, which then reports every read of it as F821 -- and that report is
# the whole safety net of reading colours through this module.
_INITIAL = palettes.THEME_BY_CODE[palettes.SYSTEM_DARK]

ACCENT: str = _INITIAL.colors.ACCENT
ACCENT_ON: str = _INITIAL.colors.ACCENT_ON

BG: str = _INITIAL.colors.BG
BG_INPUT: str = _INITIAL.colors.BG_INPUT
BG_METHOD_SEL: str = _INITIAL.colors.BG_METHOD_SEL
BG_FILE_SEL: str = _INITIAL.colors.BG_FILE_SEL
BG_MENU: str = _INITIAL.colors.BG_MENU

BORDER: str = _INITIAL.colors.BORDER
BORDER_COLOR: str = _INITIAL.colors.BORDER_COLOR
BORDER_STRONG: str = _INITIAL.colors.BORDER_STRONG

TEXT_H: str = _INITIAL.colors.TEXT_H
TEXT: str = _INITIAL.colors.TEXT
TEXT_MUTED: str = _INITIAL.colors.TEXT_MUTED
TEXT_HINT: str = _INITIAL.colors.TEXT_HINT
TEXT_DIM: str = _INITIAL.colors.TEXT_DIM
TEXT_PATH: str = _INITIAL.colors.TEXT_PATH

SUCCESS: str = _INITIAL.colors.SUCCESS
ERROR: str = _INITIAL.colors.ERROR
WARNING: str = _INITIAL.colors.WARNING

DOT_NONE: str = _INITIAL.colors.DOT_NONE
DOT_DRAFT: str = _INITIAL.colors.DOT_DRAFT
DOT_IMPORTED: str = _INITIAL.colors.DOT_IMPORTED
DOT_AI: str = _INITIAL.colors.DOT_AI
DOT_HUMAN: str = _INITIAL.colors.DOT_HUMAN

SURFACE_DISABLED: str = _INITIAL.colors.SURFACE_DISABLED
BANNER_BG: str = _INITIAL.colors.BANNER_BG
TOOLBAR_BG: str = _INITIAL.colors.TOOLBAR_BG
TABLE_HEADER_BG: str = _INITIAL.colors.TABLE_HEADER_BG
PANEL_BG: str = _INITIAL.colors.PANEL_BG
TILE_BG: str = _INITIAL.colors.TILE_BG

BORDER_SUBTLE: str = _INITIAL.colors.BORDER_SUBTLE
BORDER_ROW: str = _INITIAL.colors.BORDER_ROW
DANGER_BORDER: str = _INITIAL.colors.DANGER_BORDER

TOAST_SUCCESS_BG: str = _INITIAL.colors.TOAST_SUCCESS_BG
TOAST_WARNING_BG: str = _INITIAL.colors.TOAST_WARNING_BG
TOAST_ERROR_BG: str = _INITIAL.colors.TOAST_ERROR_BG

SUCCESS_PANEL_BG: str = _INITIAL.colors.SUCCESS_PANEL_BG
SUCCESS_PANEL_BORDER: str = _INITIAL.colors.SUCCESS_PANEL_BORDER
SUCCESS_TITLE: str = _INITIAL.colors.SUCCESS_TITLE
SUCCESS_PATH: str = _INITIAL.colors.SUCCESS_PATH
ON_SUCCESS: str = _INITIAL.colors.ON_SUCCESS

STEP_DONE_BG: str = _INITIAL.colors.STEP_DONE_BG
STEP_TODO_BORDER: str = _INITIAL.colors.STEP_TODO_BORDER

# Le focus se declare ici et nulle part ailleurs, pour les deux familles de
# controles qui peuvent le prendre : les boutons, via focusable() ci-dessous,
# et les champs de saisie, via focused_border_color / focused_border_width.
# Flet 0.85 n'expose pas de theme de decoration d'entree, donc chaque champ
# doit poser la propriete lui-meme ; il pointe la valeur d'ici plutot que de la
# reecrire, sinon un bouton et un champ finissent avec deux focus differents.
FOCUS_RING: str = _INITIAL.colors.FOCUS_RING
HOVER_TINT: str = _INITIAL.colors.HOVER_TINT
HOVER_RING: str = _INITIAL.colors.HOVER_RING

FOCUS_RING_WIDTH = 3
_TRANSPARENT = "#00000000"

_active: palettes.Theme = _INITIAL
_listeners: list[Callable[[], None]] = []


def _bind(theme: palettes.Theme) -> None:
    """Make a theme the active one, without telling anybody.

    Args:
        theme: The theme whose palette becomes the module's colours.
    """
    global _active
    _active = theme
    globals().update(asdict(theme.colors))


def active_theme() -> palettes.Theme:
    """Return the theme currently applied.

    Callers needing more than a colour read it from here, the logo folder
    above all: naming the theme is what spares every view a test on light
    or dark.

    Returns:
        The active Theme entry.
    """
    return _active


def set_theme(code: str) -> None:
    """Apply a theme and notify every listener.

    Asking for the theme already in force does nothing at all. A listener
    here rebuilds the whole screen, which on the review view means
    querying the database and building hundreds of controls, so notifying
    when no colour moved is not a wasted call but a frozen interface. It
    is also what keeps the platform-brightness handler from feeding
    itself: applying a theme sets page.theme_mode, which the client may
    answer with a brightness event, which would apply a theme again.

    Args:
        code: Identifier of a theme declared in palettes.THEMES.

    Raises:
        ValueError: If no theme carries that identifier. Callers handling
            values that come from a settings file should go through
            apply_setting(), which falls back instead of raising.
    """
    theme = palettes.get_theme(code)
    if theme is None:
        raise ValueError(f"Unknown theme: {code}")
    if theme is _active:
        return
    _bind(theme)
    for listener in _listeners:
        listener()


def apply_setting(brightness: ft.Brightness | None) -> None:
    """Apply the theme the saved settings ask for.

    The stored value is either a theme identifier or palettes.SYSTEM, in
    which case the host platform decides. Anything else is treated as a
    dark request: the value comes from a file a previous version wrote,
    and a theme dropped since must not stop the application from starting.

    Args:
        brightness: What the host platform reports, or None when it has
            not said yet, which is the case on the very first frame.
    """
    code = settings.get("theme") or palettes.SYSTEM
    if code == palettes.SYSTEM:
        light = brightness is ft.Brightness.LIGHT
        code = palettes.SYSTEM_LIGHT if light else palettes.SYSTEM_DARK
    elif palettes.get_theme(code) is None:
        code = palettes.SYSTEM_DARK
    set_theme(code)


def on_theme_change(listener: Callable[[], None]) -> None:
    """Register a callback to be called when the theme changes.

    Args:
        listener: Callable invoked on every theme switch.
    """
    _listeners.append(listener)


def remove_listener(listener: Callable[[], None]) -> None:
    """Unregister a previously registered listener.

    Args:
        listener: The callable to remove.
    """
    global _listeners
    _listeners = [ln for ln in _listeners if ln is not listener]


def border_all(width: float, color: str) -> ft.Border:
    """Create a uniform border on all four sides.

    Args:
        width: Border width in pixels.
        color: Border color as a hex string.

    Returns:
        A Border with the same side on all four edges.
    """
    side = ft.BorderSide(width, color)
    return ft.Border(left=side, right=side, top=side, bottom=side)


def focusable(
    content: ft.Control,
    *,
    on_click: Callable[[Any], Any],
    tooltip: str | None = None,
    radius: float = 8,
    width: float | None = None,
    height: float | None = None,
    expand: bool = False,
    disabled: bool = False,
    visible: bool = True,
    on_focus: Callable[[Any], None] | None = None,
    on_blur: Callable[[Any], None] | None = None,
) -> ft.TextButton:
    """Make an existing control operable by the keyboard, unchanged.

    A Container carrying on_click is a gesture detector: the pointer
    reaches it, the keyboard never does, and a screen reader announces no
    role. Wrapping it in a real button fixes all three at once, and this
    wraps rather than replaces on purpose. Rebuilding each action as a
    Material button meant reproducing its padding, its type and its size
    by hand, and Flet exposes no way to lift the minimum size Material
    then imposes; the buttons came out uneven and undersized. Here the
    wrapper draws nothing of its own: the control passed in is the whole
    look, and stays whatever it already was.

    The focus ring and the hover tint are drawn by a container wrapped
    *around* that control, not by the button underneath it. Material
    paints both `side` and `overlay_color` below the button's child, so an
    opaque control simply covered them: the ring showed only where the
    control happened to be transparent, which is exactly what made it
    look absent on some buttons and sunken on others. A border on an
    enclosing container is painted outside the control's own box and
    nothing can come over it.

    The ring's width is reserved whether it shows or not, so taking the
    focus never nudges the layout.

    The two colours it draws with are read from the module at call time,
    so a wrapper built after a theme switch is already right.

    Args:
        content: The control to show, usually the Container already
            written for this action, minus its on_click and its tooltip.
        on_click: Called on click, on Enter and on Space; may be a
            coroutine function, as Flet awaits those itself.
        tooltip: What the action does. Also its accessible name, so it is
            required for anything whose content is an icon alone.
        radius: Corner radius of the control being wrapped; the ring is
            drawn one width larger so the two stay concentric.
        width: Fixed width of the control, ring excluded. Needed on small
            controls: Material imposes a minimum size on a button, which a
            fixed size overrides.
        height: Fixed height of the control, ring excluded.
        expand: True to take the space its row leaves, for a control whose
            whole surface is meant to be clickable.
        disabled: True to refuse the action and drop it from the focus
            order, which is what an unavailable action must do rather
            than sit there looking clickable.
        visible: Whether the control is rendered at all.
        on_focus: Called once the ring is painted, for a caller that has
            to know where the keyboard sits and not merely show it.
        on_blur: Called once the ring is cleared. Beware that it may
            arrive after the next control's on_focus, so a caller
            tracking the focused control has to check it is clearing its
            own and not the one that just took over.

    Returns:
        The wrapped control, focusable and announced as a button.
    """
    ring = ft.Container(
        content=content,
        border=border_all(FOCUS_RING_WIDTH, _TRANSPARENT),
        border_radius=radius + FOCUS_RING_WIDTH,
    )

    def _paint(*, focused: bool, hovered: bool) -> None:
        """Show the ring in the state the two pointers agree on.

        Hover is drawn on the ring as well as behind the control, since
        the tint alone only reaches the buttons whose fill is
        transparent: on an accent button it would be hidden by the very
        thing it is meant to highlight. Focus always wins, so a pointer
        resting elsewhere never dulls the ring somebody is navigating by.
        """
        if focused:
            edge = FOCUS_RING
        elif hovered:
            edge = HOVER_RING
        else:
            edge = _TRANSPARENT
        ring.border = border_all(FOCUS_RING_WIDTH, edge)
        ring.bgcolor = HOVER_TINT if hovered and not focused else None
        ring.update()

    state = {"focused": False, "hovered": False}

    def _on_focus(e: Any) -> None:
        state["focused"] = True
        _paint(focused=True, hovered=state["hovered"])
        if on_focus is not None:
            on_focus(e)

    def _on_blur(e: Any) -> None:
        state["focused"] = False
        _paint(focused=False, hovered=state["hovered"])
        if on_blur is not None:
            on_blur(e)

    def _on_hover(e: Any) -> None:
        state["hovered"] = bool(e.data)
        _paint(focused=state["focused"], hovered=state["hovered"])

    inset = 2 * FOCUS_RING_WIDTH
    return ft.TextButton(
        content=ring,
        tooltip=tooltip,
        on_click=on_click,
        on_focus=_on_focus,
        on_blur=_on_blur,
        on_hover=_on_hover,
        width=None if width is None else width + inset,
        height=None if height is None else height + inset,
        expand=expand,
        disabled=disabled,
        visible=visible,
        style=ft.ButtonStyle(
            bgcolor=_TRANSPARENT,
            overlay_color=_TRANSPARENT,
            shadow_color=_TRANSPARENT,
            elevation=0,
            padding=ft.Padding.all(0),
            shape=ft.RoundedRectangleBorder(radius=radius + FOCUS_RING_WIDTH),
            visual_density=ft.VisualDensity.COMPACT,
        ),
    )
