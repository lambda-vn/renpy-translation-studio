"""Build the desktop application for the system running this script.

There is no way to make one machine produce the three binaries: flet
build drives the Flutter toolchain installed locally, so a Windows
machine builds Windows and nothing else. The three at once is what
.github/workflows/build.yml is for, one runner per target.

This exists to answer the question the bare command does not: which
target am I even allowed to ask for, and where did the result go.

    uv run python scripts/build.py
"""

import subprocess
import sys
from pathlib import Path

_TARGETS = {
    "win32": "windows",
    "darwin": "macos",
    "linux": "linux",
}

_ROOT = Path(__file__).resolve().parent.parent

_DEV_MODE_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock"
_DEV_MODE_VALUE = "AllowDevelopmentWithoutDevLicense"


def _windows_developer_mode() -> bool:
    """Report whether Windows allows the symlinks a plugin build needs.

    Flutter builds plugins through symlinks, which Windows only grants
    under Developer Mode. Without it the build runs for four minutes,
    resolves every dependency, and only then fails on one line buried
    under a doctor report about Android and Chrome, neither of which has
    anything to do with a desktop build.

    Returns:
        True when the mode is on, or when the answer cannot be read, the
        build being the better judge in that case.
    """
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DEV_MODE_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _DEV_MODE_VALUE)
    except OSError:
        return False
    return value == 1


def main() -> int:
    """Run flet build for this platform.

    Returns:
        The build's exit code, or 1 when the platform has no desktop
        target.
    """
    target = _TARGETS.get(sys.platform)
    if target is None:
        print(
            f"No desktop target for {sys.platform}. Supported: "
            f"{', '.join(sorted(set(_TARGETS.values())))}.",
            file=sys.stderr,
        )
        return 1

    if target == "windows" and not _windows_developer_mode():
        print(
            "Windows Developer Mode is off, and Flutter needs it to build "
            "plugins through symlinks.\n"
            "Turn it on, then run this again:\n\n"
            "    start ms-settings:developers\n",
            file=sys.stderr,
        )
        return 1

    print(f"Building the {target} application. The other two need their own")
    print("system: run the Build workflow on GitHub for all three at once.\n")

    result = subprocess.run(
        ["uv", "run", "flet", "build", target, "--yes"],
        cwd=_ROOT,
        check=False,
    )
    if result.returncode == 0:
        print(f"\nDone: {_ROOT / 'build' / target}")
        print(
            "The binary is unsigned, so Windows SmartScreen and macOS "
            "Gatekeeper will warn about it."
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
