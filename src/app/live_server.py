"""The listener a running application opens for its project.

One route, one job: take the identifiers of the lines somebody else just
wrote and hand them to the view, which refreshes those rows in place.
Nothing is read back over it, the database staying the one source of
truth; the notification only says where to look.

The socket is created here rather than by uvicorn, so the port is known
before the server starts and can be published without waiting for it to
come up. Port 0 asks the system for a free one: a fixed port would
collide with a second window, and choosing one badly would collide with
whatever else runs on this machine.
"""

import asyncio
import logging
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from core.live import AUTH_HEADER, LiveEndpoint, clear, new_token, publish

_logger = logging.getLogger(__name__)

_HOST = "127.0.0.1"


class LiveServer:
    """A local endpoint telling one view which lines changed under it.

    Attributes:
        project: The Ren'Py project this server answers for.
    """

    def __init__(
        self, project: Path, on_changed: Callable[[list[str] | None], None]
    ) -> None:
        """Prepare the server without opening anything yet.

        Args:
            project: The Ren'Py project root being shown.
            on_changed: Called with the identifiers of the changed
                lines, or with None when too much changed to name it and
                the view should reload. Runs on the event loop, so it
                must hand any control tree mutation over the way a
                background job does.
        """
        self.project = project
        self._on_changed = on_changed
        self._token = new_token()
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Open the socket, publish the endpoint, and serve.

        A failure to bind is logged and swallowed: losing live refresh
        costs a page reload, where refusing to open a project over it
        would cost the session.
        """
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind((_HOST, 0))
            self._socket.listen()
            port = int(self._socket.getsockname()[1])
        except OSError:
            _logger.warning("Could not open the live endpoint", exc_info=True)
            self._close_socket()
            return

        config = uvicorn.Config(
            self._build_app(),
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve(sockets=[self._socket]))
        publish(self.project, LiveEndpoint(port=port, token=self._token))

    async def stop(self) -> None:
        """Withdraw the endpoint and shut the server down."""
        clear(self.project)
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self._close_socket()
        self._server = None
        self._task = None

    def _close_socket(self) -> None:
        """Release the listening socket if it was ever opened."""
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def _build_app(self) -> Starlette:
        """Build the one-route application answering notifications."""

        async def changed(request: Request) -> Response:
            if request.headers.get(AUTH_HEADER) != self._token:
                return JSONResponse({"error": "forbidden"}, status_code=403)
            try:
                payload: Any = await request.json()
            except ValueError:
                return JSONResponse({"error": "invalid json"}, status_code=400)
            if not isinstance(payload, dict):
                return JSONResponse({"error": "object expected"}, status_code=400)
            if payload.get("reload") is True:
                self._on_changed(None)
                return Response(status_code=204)
            block_ids = payload.get("block_ids")
            if not isinstance(block_ids, list):
                return JSONResponse({"error": "block_ids expected"}, status_code=400)
            self._on_changed([str(block_id) for block_id in block_ids])
            return Response(status_code=204)

        return Starlette(routes=[Route("/changed", changed, methods=["POST"])])
