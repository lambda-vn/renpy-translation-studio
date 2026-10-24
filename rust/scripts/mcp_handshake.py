"""Speak MCP to a built `rts-mcp` and report what it answered.

The build gate for the packaged MCP server, the Rust counterpart of the
1.x `scripts/mcp_handshake.py`. Starting the process proves nothing: it can
launch, link every library and still answer nothing a client understands,
stdio being the whole contract. So this holds a real conversation instead:
initialize, list the tools, call one, and fail when any reply is not one.

Run it with the executable to test as the argument:

    python rust/scripts/mcp_handshake.py rust/src-tauri/binaries/rts-mcp-<triple>

Unlike the 1.x gate, which only insists on three tools so that adding one
is not a build failure, this one asserts the exact set. The Rust server
registers its tools statically, so a tool that vanishes from the list is a
regression worth stopping a release for, and `EXPECTED_TOOLS` is the place
a human acknowledges that one was added.

The call is `list_projects`, the one tool that needs no open project: it
reads the registry of recent projects, which is empty on a CI runner and
whatever the user has on a developer machine, and writes nothing.
"""

import json
import subprocess
import sys
from pathlib import Path

EXPECTED_TOOLS = frozenset(
    {
        "clear_translations",
        "delete_character",
        "fill_from_memory",
        "get_unit_context",
        "get_universe_summary",
        "list_characters",
        "list_files",
        "list_projects",
        "list_units",
        "project_progress",
        "set_needs_review",
        "set_note",
        "set_universe_summary",
        "submit_translations",
        "upsert_character",
        "use_project",
    }
)
_TIMEOUT = 90


class HandshakeError(RuntimeError):
    """The server did not answer like an MCP server."""


def _send(proc: subprocess.Popen[str], payload: dict[str, object]) -> None:
    """Write one JSON-RPC message on the server's standard input.

    Args:
        proc: The running server.
        payload: The message to send.

    Raises:
        HandshakeError: If the server has no standard input.
    """
    if proc.stdin is None:
        raise HandshakeError("the server has no standard input")
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _read(proc: subprocess.Popen[str]) -> dict[str, object]:
    """Read one JSON-RPC message from the server's standard output.

    Args:
        proc: The running server.

    Returns:
        The decoded message.

    Raises:
        HandshakeError: If the server answered nothing, or something that
            is not JSON.
    """
    if proc.stdout is None:
        raise HandshakeError("the server has no standard output")
    line = proc.stdout.readline()
    if not line.strip():
        raise HandshakeError("the server closed without answering")
    try:
        return dict(json.loads(line))
    except json.JSONDecodeError as exc:
        raise HandshakeError(f"not JSON: {line.strip()[:200]}") from exc


def _result(answer: dict[str, object], what: str) -> dict[str, object]:
    """Return the `result` member of a reply, or fail naming the request.

    Args:
        answer: The decoded reply.
        what: The request it answers, for the error message.

    Returns:
        The result object.

    Raises:
        HandshakeError: If the reply carries no result object.
    """
    result = answer.get("result")
    if not isinstance(result, dict):
        raise HandshakeError(f"{what} refused: {answer}")
    return result


def handshake(command: list[str]) -> list[str]:
    """Initialize a server, list its tools and call one of them.

    Args:
        command: The command starting the server, as an argument list.

    Returns:
        The sorted names of the tools it listed.

    Raises:
        HandshakeError: If the exchange failed at any point.
    """
    program = Path(command[0])
    resolved = str(program.resolve()) if program.exists() else command[0]
    proc = subprocess.Popen(
        [resolved, *command[1:]],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    try:
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "build-gate", "version": "0"},
                },
            },
        )
        _result(_read(proc), "initialize")

        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = _result(_read(proc), "tools/list").get("tools")
        if not isinstance(tools, list):
            raise HandshakeError("no tool list in the tools/list reply")
        names = sorted(str(tool["name"]) for tool in tools)

        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_projects", "arguments": {}},
            },
        )
        called = _result(_read(proc), "tools/call list_projects")
        if called.get("isError"):
            raise HandshakeError(f"list_projects reported an error: {called}")
        return names
    finally:
        proc.kill()
        try:
            _, err = proc.communicate(timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            err = ""
        if err:
            print(f"server stderr:\n{err[-2000:]}", file=sys.stderr)


def main(argv: list[str]) -> int:
    """Run the handshake and report.

    Args:
        argv: The command starting the server.

    Returns:
        0 when the server answered like one and offers exactly the expected
        tools, 1 otherwise.
    """
    if not argv:
        print("usage: mcp_handshake.py <command> [args...]", file=sys.stderr)
        return 1
    try:
        names = handshake(argv)
    except (HandshakeError, OSError) as exc:
        print(f"handshake failed: {exc}", file=sys.stderr)
        return 1

    print(f"tools listed ({len(names)}): {', '.join(names)}")
    listed = set(names)
    missing = sorted(EXPECTED_TOOLS - listed)
    unexpected = sorted(listed - EXPECTED_TOOLS)
    if missing or unexpected:
        print(f"missing tools: {', '.join(missing) or 'none'}", file=sys.stderr)
        print(f"unexpected tools: {', '.join(unexpected) or 'none'}", file=sys.stderr)
        return 1
    print("the MCP server answered over stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
