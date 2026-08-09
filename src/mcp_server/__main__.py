"""Command line starting the server.

One server serves every game the application has set up: the client asks
for the list and picks one, so a user declares this command once instead
of once per project. --project pins it to a single one, for a client
that should reach nothing else.

The two permissions are flags here and nowhere else. A client reads the
game's own text, which is written by someone other than the person
running this, so anything that destroys work has to be granted from
outside the protocol.
"""

import argparse
import logging
import sys
from pathlib import Path

from mcp_server.server import build_server
from mcp_server.session import ProjectNotFoundError, ServerState


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read the command line.

    Args:
        argv: Arguments to parse, sys.argv[1:] when omitted.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="rts-mcp",
        description="Serve the Ren'Py projects of this machine over MCP.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        help="Serve only this game folder, the one holding game/. Omitted, "
        "the client picks among the projects set up in the application.",
    )
    parser.add_argument(
        "--allow-overwrite-validated",
        action="store_true",
        help="Let a submission replace a line a human already validated. "
        "The replacement lands as a draft, never as validated.",
    )
    parser.add_argument(
        "--allow-clear",
        action="store_true",
        help="Allow deleting translations in bulk.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Serve over stdio until the client disconnects.

    Args:
        argv: Arguments to parse, sys.argv[1:] when omitted.

    Returns:
        0 once the client disconnects, 1 if a pinned project cannot be
        opened.

    httpx is quietened first: the SDK sets up logging for this process,
    and every notification sent to a running application would otherwise
    print the URL it was posted to.
    """
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = _parse_args(argv)
    state = ServerState(
        allow_overwrite_validated=args.allow_overwrite_validated,
        allow_clear=args.allow_clear,
    )

    if args.project is not None:
        state.pinned = args.project.resolve()
        try:
            state.use(state.pinned)
        except ProjectNotFoundError as error:
            print(error, file=sys.stderr)
            return 1

    try:
        build_server(state).run()
    finally:
        state.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
