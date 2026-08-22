"""Start the MCP server from inside a packaged build.

`flet build` produces one application and no way to run anything else in
it, so a release used to carry the MCP server as dead code: the modules
shipped, the `mcp` package shipped, and nothing could reach them. The
Flutter host runs `main.py` through its own loader, passes no command
line to it, and redirects its output to a log file, which rules out both
a flag on the application and the stdio transport the protocol needs.

What the bundle does hold is a complete CPython. The build copies that
interpreter in beside it, and this file is what the interpreter runs.

The two directories are added differently on purpose. `app` is a plain
import root and goes on the path. `site-packages` is registered as a
site directory instead, because a `.pth` there is only executed on that
path: pywin32 ships one, and without it `import mcp` fails on Windows
looking for `pywintypes`, which lives in a subdirectory that only the
`.pth` adds.
"""

import runpy
import site
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def main() -> None:
    """Put the bundle on the import path and hand over to the server."""
    site.addsitedir(str(_ROOT / "site-packages"))
    sys.path.insert(0, str(_ROOT / "app"))
    runpy.run_module("mcp_server", run_name="__main__")


if __name__ == "__main__":
    main()
