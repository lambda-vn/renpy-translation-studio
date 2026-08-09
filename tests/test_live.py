"""Tests for the live notification channel.

The listener is driven for real rather than mocked: a socket is bound, a
notification is posted through httpx, and the callback is checked. The
point of this channel is that it works across two processes, and a test
faking the transport would prove nothing about the one part that can
break.
"""

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.live_server import LiveServer
from core.live import (
    AUTH_HEADER,
    LiveEndpoint,
    clear,
    endpoint_path,
    notify,
    notify_reload,
    publish,
    read,
)


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """Provide a project root with its .rts folder."""
    (tmp_path / ".rts").mkdir()
    yield tmp_path
    clear(tmp_path)


def test_publish_then_read_round_trip(project: Path) -> None:
    publish(project, LiveEndpoint(port=1234, token="secret"))

    endpoint = read(project)

    assert endpoint == LiveEndpoint(port=1234, token="secret")


def test_read_without_an_application_returns_none(project: Path) -> None:
    assert read(project) is None


def test_read_ignores_a_damaged_file(project: Path) -> None:
    """A truncated file is the ordinary shape of a crash, not an error."""
    endpoint_path(project).write_text("{ not json", encoding="utf-8")

    assert read(project) is None


def test_clear_withdraws_the_announcement(project: Path) -> None:
    publish(project, LiveEndpoint(port=1234, token="secret"))

    clear(project)

    assert read(project) is None


def test_notify_without_a_listener_is_silent(project: Path) -> None:
    """A closed application is the ordinary case, never a failure."""
    publish(project, LiveEndpoint(port=1, token="secret"))

    assert notify(project, ["a"]) is False


def test_notify_with_nothing_to_say_sends_nothing(project: Path) -> None:
    assert notify(project, []) is False


def test_a_notification_reaches_the_listener(project: Path) -> None:
    async def run() -> list[list[str] | None]:
        received: list[list[str] | None] = []
        server = LiveServer(project, received.append)
        await server.start()
        delivered = await asyncio.to_thread(notify, project, ["a", "b"])
        await server.stop()
        assert delivered is True
        return received

    assert asyncio.run(run()) == [["a", "b"]]


def test_a_wrong_token_is_refused(project: Path) -> None:
    """A browser can POST to a local port; it cannot read the disk."""
    import httpx

    async def run() -> tuple[list[list[str] | None], int]:
        received: list[list[str] | None] = []
        server = LiveServer(project, received.append)
        await server.start()
        port = json.loads(endpoint_path(project).read_text(encoding="utf-8"))["port"]
        response = await asyncio.to_thread(
            httpx.post,
            f"http://127.0.0.1:{port}/changed",
            json={"block_ids": ["a"]},
            headers={AUTH_HEADER: "guessed"},
            timeout=2,
        )
        await server.stop()
        return received, response.status_code

    received, status = asyncio.run(run())

    assert status == 403
    assert received == []


def test_stopping_withdraws_the_endpoint(project: Path) -> None:
    async def run() -> None:
        server = LiveServer(project, lambda _ids: None)
        await server.start()
        assert read(project) is not None
        await server.stop()

    asyncio.run(run())

    assert read(project) is None


def test_a_reload_signal_reaches_the_listener_as_none(project: Path) -> None:
    """A bulk action names no line, so the view is told to reload."""

    async def run() -> list[list[str] | None]:
        received: list[list[str] | None] = []
        server = LiveServer(project, received.append)
        await server.start()
        delivered = await asyncio.to_thread(notify_reload, project)
        await server.stop()
        assert delivered is True
        return received

    assert asyncio.run(run()) == [None]


def test_notify_reload_without_a_listener_is_silent(project: Path) -> None:
    publish(project, LiveEndpoint(port=1, token="secret"))

    assert notify_reload(project) is False
