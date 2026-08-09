"""Import guard over the UI package, which no other test ever loads.

The views hold the bulk of the application and are checked by hand, so
nothing else catches a module left unimportable: a name that survived a
rename only where it is spelled out, a circular import between a view
and a component, a constant read at module level that moved. mypy sees
most of those, this catches what is decided at run time.

main is imported too, which only holds as long as its ft.run() call
stays behind the __main__ guard: importing it otherwise starts the
application rather than loading it.
"""

import importlib
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parent.parent / "src" / "app"


def _app_modules() -> list[str]:
    """Return the dotted name of every module of the UI layer.

    Returns:
        Import paths such as "app.views.review_view", in a stable order,
        the entry point last.
    """
    return [
        ".".join(path.relative_to(_APP_DIR.parent).with_suffix("").parts)
        for path in sorted(_APP_DIR.rglob("*.py"))
    ] + ["main"]


@pytest.mark.parametrize("module", _app_modules())
def test_module_imports(module: str) -> None:
    """Every module of the UI package imports on its own."""
    importlib.import_module(module)


def test_the_app_package_was_found() -> None:
    """Guard the walk itself, which passes silently over an empty tree."""
    assert "app.views.review_view" in _app_modules()
