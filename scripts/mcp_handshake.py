"""Speak MCP to a packaged server and report what it answered.

The build gate for the MCP launcher. Starting the process proves nothing:
the launcher can find its interpreter, import every module and still
answer nothing a client understands, because the transport is stdio and
stdio is exactly what a packaged application does not have by default.
So this holds a real conversation instead, and fails the build when the
reply is not one.

Run it with the command to test as arguments:

    python scripts/mcp_handshake.py ./rts-mcp

The three tools it insists on are the ones the workflow is built from,
naming a project, opening it and sending translations back. Asserting the
whole list would break the day a tool is added, which is not a build
failure; asserting these three breaks only when the server is not the
server.
"""

import json
import subprocess
import sys

_REQUIRED = ("list_projects", "use_project", "submit_translations")
_TIMEOUT = 90


class HandshakeError(RuntimeError):
    """The packaged server did not answer like an MCP server."""


def _send(proc: subprocess.Popen[str], payload: dict[str, object]) -> None:
    """Write one JSON-RPC message on the server's standard input.

    Args:
        proc: The running server.
        payload: The message to send.

    Raises:
        HandshakeError: If the server has already closed its input.
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
        HandshakeError: If the server answered nothing, or answered
            something that is not JSON.
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


def handshake(command: list[str]) -> list[str]:
    """Initialize a server and return the tools it offers.

    Args:
        command: The command starting the server, as an argument list.

    Returns:
        The names of the tools it listed.

    Raises:
        HandshakeError: If the exchange failed at any point.
    """
    proc = subprocess.Popen(
        command,
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
        answer = _read(proc)
        if "result" not in answer:
            raise HandshakeError(f"initialize refused: {answer}")

        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = _read(proc)
        result = listed.get("result")
        if not isinstance(result, dict):
            raise HandshakeError(f"tools/list refused: {listed}")
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise HandshakeError(f"no tool list in {listed}")
        return sorted(str(tool["name"]) for tool in tools)
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
        0 when the server answered like one, 1 otherwise.
    """
    if not argv:
        print("usage: mcp_handshake.py <command> [args...]", file=sys.stderr)
        return 1
    try:
        tools = handshake(argv)
    except (HandshakeError, OSError) as exc:
        print(f"handshake failed: {exc}", file=sys.stderr)
        return 1

    print(f"tools listed ({len(tools)}): {', '.join(tools)}")
    missing = [name for name in _REQUIRED if name not in tools]
    if missing:
        print(f"missing tools: {', '.join(missing)}", file=sys.stderr)
        return 1
    print("the packaged MCP server answered over stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
