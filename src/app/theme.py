"""Shared color palette, border helper and focus wrapper for the UI.

Centralizes the dark-theme colors previously duplicated in every view and
component module. Import the named colors directly:

    from app.theme import ACCENT, TEXT_H, border_all
"""

from collections.abc import Callable
from typing import Any

import flet as ft

ACCENT = "#cbbdff"
ACCENT_ON = "#241a52"

BG = "#141318"
BG_INPUT = "#1d1c24"
BG_METHOD_SEL = "#201c2e"
BG_FILE_SEL = "#252336"
BG_MENU = "#1a1822"

BORDER = "#1a1820"
BORDER_COLOR = "#3a3744"
BORDER_STRONG = "#4b4856"

TEXT_H = "#ece7f2"
TEXT = "#e4dfee"
TEXT_MUTED = "#9b96a6"
TEXT_HINT = "#6f6b79"
TEXT_DIM = "#8e8a98"
TEXT_PATH = "#cdc8d8"

SUCCESS = "#7ddf9b"
ERROR = "#ff8a80"
WARNING = "#ffc947"

DOT_NONE = "#4a4759"
DOT_DRAFT = "#7fbfff"
DOT_IMPORTED = "#c9a5ff"
DOT_AI = "#ffc947"
DOT_HUMAN = "#7ddf9b"


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


# Le focus se declare ici et nulle part ailleurs, pour les deux familles de
# controles qui peuvent le prendre : les boutons, via focusable() ci-dessous,
# et les champs de saisie, via focused_border_color / focused_border_width.
# Flet 0.85 n'expose pas de theme de decoration d'entree, donc chaque champ
# doit poser la propriete lui-meme ; il pointe la valeur d'ici plutot que de la
# reecrire, sinon un bouton et un champ finissent avec deux focus differents.
FOCUS_RING = "#4fd1ff"
FOCUS_RING_WIDTH = 3
HOVER_TINT = ft.Colors.with_opacity(0.09, ft.Colors.WHITE)
HOVER_RING = ft.Colors.with_opacity(0.28, ft.Colors.WHITE)
_TRANSPARENT = "#00000000"


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
