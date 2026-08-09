"""How a running application tells whoever else writes its project.

The MCP server writes a project whether or not the application is open,
so the notification is a bonus and never a dependency: it is sent when
somebody is listening and dropped otherwise. Nothing waits for it and
nothing fails without it.

The application is the one that listens, the MCP server being spawned by
its client on demand and dying with it, so it has no address anybody
could keep. It publishes where it listens in the project itself, beside
the database it is showing.

The token is what a browser cannot have. A server bound to 127.0.0.1 is
reachable by any page open in a browser, a plain POST not being held
back by a preflight, so the endpoint asks for a value only something
with access to the disk can read. It stops nothing else: a program
running as the user could read the file, or simply write the database
itself.
"""

import json
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path

import httpx

_logger = logging.getLogger(__name__)

AUTH_HEADER = "X-Rts-Token"

_FILE_NAME = "live.json"
_TIMEOUT_SECONDS = 0.5


@dataclass(frozen=True)
class LiveEndpoint:
    """Where a running application listens for change notifications."""

    port: int
    token: str


def endpoint_path(project: Path) -> Path:
    """Return where a project's live endpoint is published.

    Args:
        project: The Ren'Py project root.

    Returns:
        The live.json path beside the project database.
    """
    return project / ".rts" / _FILE_NAME


def new_token() -> str:
    """Return a fresh token for one application session."""
    return secrets.token_urlsafe(24)


def publish(project: Path, endpoint: LiveEndpoint) -> None:
    """Announce where this application is listening.

    Args:
        project: The Ren'Py project root.
        endpoint: The port and token to publish.
    """
    path = endpoint_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"port": endpoint.port, "token": endpoint.token}),
        encoding="utf-8",
    )


def read(project: Path) -> LiveEndpoint | None:
    """Read where the application of a project listens, if it says.

    Args:
        project: The Ren'Py project root.

    Returns:
        The endpoint, or None when no application published one or the
        file cannot be understood. A stale file left by a crash reads
        fine and simply fails to answer later.
    """
    path = endpoint_path(project)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return LiveEndpoint(port=int(raw["port"]), token=str(raw["token"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def clear(project: Path) -> None:
    """Withdraw the announcement, on the way out.

    Args:
        project: The Ren'Py project root.
    """
    endpoint_path(project).unlink(missing_ok=True)


def notify(project: Path, block_ids: list[str]) -> bool:
    """Tell the application which lines just changed, if it is listening.

    Never raises. A refused connection is the ordinary case, the
    application being closed, and a caller that had to handle it would
    make the notification a dependency rather than a bonus.

    Args:
        project: The Ren'Py project root.
        block_ids: Identifiers of the units that changed.

    Returns:
        True when the application acknowledged, False in every other
        case.
    """
    if not block_ids:
        return False
    return _post(project, {"block_ids": block_ids})


def notify_reload(project: Path) -> bool:
    """Tell the application that too much changed to name it.

    A bulk action answers with a count rather than identifiers, and a
    whole project rewritten is a reload rather than a row update. Sending
    every touched line instead would be a list of thousands describing a
    page of fifty.

    Args:
        project: The Ren'Py project root.

    Returns:
        True when the application acknowledged, False in every other
        case.
    """
    return _post(project, {"reload": True})


def _post(project: Path, payload: dict[str, object]) -> bool:
    """Send one notification, treating every failure as an absent listener.

    Args:
        project: The Ren'Py project root.
        payload: The body to send.

    Returns:
        True when the application acknowledged, False in every other
        case.
    """
    endpoint = read(project)
    if endpoint is None:
        return False
    try:
        response = httpx.post(
            f"http://127.0.0.1:{endpoint.port}/changed",
            json=payload,
            headers={AUTH_HEADER: endpoint.token},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        _logger.debug("No application listening for %s", project, exc_info=True)
        return False
    return response.status_code == 204
