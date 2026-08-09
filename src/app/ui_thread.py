"""Handing UI work back to the event loop from a background thread."""

from collections.abc import Callable
from functools import partial

import flet as ft


def safe_update(page: ft.Page) -> None:
    """Push pending UI changes to the client, safely from any thread.

    page.update() ultimately calls asyncio.Queue.put_nowait() to hand the
    outbound message to the connection (flet's
    FletSocketServer.send_message()). asyncio.Queue isn't thread-safe:
    when put_nowait() runs on a thread other than the event loop's (e.g.
    inside a callback dispatched via page.run_thread()), the notification
    that's supposed to wake the loop doesn't reliably do so — the message
    sits queued until some unrelated client round-trip (a window resize, a
    click) happens to pump the loop. Routing through call_soon_threadsafe
    schedules the actual page.update() call to run on the loop's own
    thread, which is the standard, reliable way to hand off to asyncio
    from any thread.

    Args:
        page: The page whose pending changes must reach the client.
    """
    page.session.connection.loop.call_soon_threadsafe(page.update)


def on_ui_thread[**P](page: ft.Page, handler: Callable[P, None]) -> Callable[P, None]:
    """Wrap a callback so its whole body runs on the event loop.

    For the callbacks that mutate the control tree itself, adding to or
    replacing a controls list (a Column's children, a Dropdown's options).
    page.update() diffs that same tree on the loop's thread, and flet's
    patch builder raises IndexError when a controls list is mutated
    mid-diff. Scheduling the entire handler through call_soon_threadsafe
    serializes mutations and diffs on the loop's single thread;
    call_soon_threadsafe preserves ordering, so events stay in sequence.

    Setting a property of an existing control (a Text's value, a
    Container's visible) mutates no list and needs no wrapping: such a
    callback only has to reach for safe_update() when it is done.

    Args:
        page: The page the callback draws on.
        handler: The UI-mutating callback to protect.

    Returns:
        A callable with the same signature, safe to invoke from any
        thread.
    """

    def _scheduled(*args: P.args, **kwargs: P.kwargs) -> None:
        page.session.connection.loop.call_soon_threadsafe(
            partial(handler, *args, **kwargs)
        )

    return _scheduled
