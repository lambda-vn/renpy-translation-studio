# Ren'Py Translation Studio

Desktop application for managing translations of Ren'Py games. It covers the
full workflow: extract the game's text, review it line by line in a dedicated
UI, translate automatically through MT/LLM providers, rewrite the `tl/` files,
and export a ready-to-ship zip.

Read this in French: [README_FR.md](README_FR.md).

![The review screen, showing The Question — the sample game shipped with the
Ren'Py SDK — being translated into French](docs/images/03-review-en.png)

Full documentation, screen by screen, is in
[`docs/en/`](docs/en/README.md) ([français](docs/fr/README.md)).

## Features

- Extract translatable text from a Ren'Py game through the engine the game
  ships with (`renpy translate`), falling back on an installed Ren'Py SDK.
- Per-line review UI with statuses: `not_translated`, `draft`, `imported`,
  `ai_suggested`, `human_validated`. A `human_validated` line is never
  overwritten by an AI suggestion. Any line can also be flagged for a
  second look and carry a note explaining why.
- Background translation jobs with per-line quality checks (placeholders,
  `{tags}`, length) and automatic retries on failure. Progress is reported
  in a banner, not a modal: the review stays usable while a job runs.
- Character glossary and AI-generated universe summary to give providers
  consistent context.
- Import and export bilingual files as CSV, XLIFF 1.2 or JSON, for review
  in a spreadsheet or a CAT tool. Matching is by stable block identifier,
  never by position.
- Translation memory shared across projects, fed by human validations only,
  filling exact matches in a new project.
- Keyboard-operable throughout, F1 listing the shortcuts. Statuses carry a
  glyph and a screen-reader label rather than a colour alone.
- Zip export scoped to `<game>/game/tl/<language>/`.

## Translation providers

| Provider | Type | Runs | Needs | Notes |
|---|---|---|---|---|
| [DeepL](https://www.deepl.com) | MT | Cloud | API key | Supports a server-side glossary |
| [LibreTranslate](https://libretranslate.com) | MT | Cloud or self-hosted | URL, key if the instance asks for one | One request per unit |
| [Ollama](https://ollama.com) | LLM | Local, or Ollama's cloud models | A pulled model and a GPU to be comfortable; a `-cloud` model needs `ollama signin` instead | Guardrails for small quantized models |
| [Claude](https://www.anthropic.com) | LLM | Cloud | API key | Beta: never tested against the real API |
| [Mistral](https://mistral.ai) | LLM | Cloud | API key | Beta: never tested against the real API |

Ollama's cloud models go through the same local endpoint, the daemon
signing the request itself, so nothing changes here beyond the model
name you type in the settings.

No account and no GPU at all: the MCP server below hands the translating
to an assistant you already pay for.

## MCP server

The application also exposes its projects over the
[Model Context Protocol](https://modelcontextprotocol.io), so an
assistant such as Claude Code can do the translating through a
subscription you already have, instead of an API key or a local GPU.

```bash
claude mcp add renpy-studio -- uv run --directory /path/to/renpy-translation-studio python -m mcp_server
```

Ask it to list your projects, pick one, and translate a file. It sees
the same actions the review screen offers: search and filters, the
character glossary, the universe summary, the translation memory, notes
and review flags. What it sends back goes through the same quality
checks and arrives as `ai_suggested`, to be reviewed in the application
like any other suggestion.

Leave the review screen open while it works and the lines fill in
under your eyes: the server tells the application which ones it just
wrote, and those rows are updated in place. Close the application and
it keeps translating, the notification being a bonus rather than a
dependency.

Two things it cannot do unless you say so on the command line:
`--allow-overwrite-validated` lets a submission replace a line you
validated, landing it as a draft; `--allow-clear` allows deleting
translations in bulk. Both are flags rather than tool arguments on
purpose: the assistant reads the game's own text, so a line of dialogue
asking for either must not be a request it can grant itself. It also
only opens games already set up in the application, never an arbitrary
folder.

## Stack

Python 3.12+ / Flet (Flutter desktop UI) / uv / SQLite.

## Requirements

- Python 3.12 or newer.
- [uv](https://docs.astral.sh/uv/) for dependency and environment management.
- A Ren'Py engine to run the extraction with. A packaged game carries its
  own, in the version its sources were written for, and that is the one used
  when this system can run it: a `-win` build holds Windows runtimes only,
  so a Windows-only game extracted from Linux needs the fallback below.
  Note that this runs third-party code, the very executable you would start
  to play the game.
- The Ren'Py SDK, optional. It is the fallback for a game shipping no engine
  this system can run, and its version may differ from the game's: Ren'Py 8
  rejects screen syntax Ren'Py 7 accepted, losing the lines of every source
  it refuses.
- A provider account or endpoint (API key or local server) for the provider
  you intend to use.

## Installation

```bash
git clone https://github.com/lambda-vn/renpy-translation-studio.git
cd renpy-translation-studio
uv sync
```

`uv` creates the `.venv` automatically on the first `uv sync` or `uv run`.
Do not activate it manually and do not commit it. Never call `pip` directly.

## Running

```bash
uv run flet run src/main.py
```

On first launch, an onboarding screen asks for the UI language and, optionally,
the Ren'Py SDK path. You then point the app at a game folder, pick source and target
languages, and move on to review, translation and export.

## Development

After every change, all four checks must pass:

```bash
uv run ruff check
uv run ruff format --check
uv run mypy src/
uv run pytest
```

- `ruff` handles linting and formatting (replaces black, flake8, isort).
- `mypy` runs in strict mode; the whole codebase is statically typed.
- `pre-commit install` wires format, lint, and commit-message hooks.

### Tests

Unit tests only, no Flet or end-to-end tests. Providers are tested against
mocked clients, never the real APIs. The `.rpy` fixtures under
`tests/fixtures/` are real Ren'Py excerpts.

```bash
uv run pytest
uv run pytest tests/test_parser.py -v
```

### Building a desktop binary

```bash
uv run python scripts/build.py
```

Builds for the system it runs on: `flet build` drives the local Flutter
toolchain and does not cross-compile. All three targets are built by the
Build workflow, one runner each. macOS is arm64 only, one of its
dependencies being impossible to cross-compile on an Apple Silicon
runner. Binaries are unsigned, so SmartScreen and Gatekeeper will warn.

## Project layout

```
src/
  main.py            Flet entry point and view navigation
  app/               UI: state, theme, components, views
  core/              Domain logic
    renpy/           parser, SDK CLI wrapper, writer, character detector
    storage/         SQLite database, repositories, recent projects
    translation/     job, quality, context builder, providers
  mcp_server/        MCP server exposing a project to an assistant
  locales/           en.json and fr.json (UI i18n)
tests/               Unit tests and .rpy fixtures
```

See [CLAUDE.md](CLAUDE.md) for the full architecture and contributor notes.

## Security

- Subprocess calls always use an argument list, never `shell=True`.
- User paths are resolved and bound-checked; zip entries reject `../`
  traversal.
- API keys live in local settings and are never logged or included in error
  messages.
- Sending game content to a third-party service (AI universe summary) always
  requires explicit user confirmation.
- A translation is refused if it adds a `[interpolation]` the source text did
  not have. Ren'Py evaluates the contents of square brackets as a Python
  expression, so an interpolation introduced by a translation coming from
  outside (a bilingual file returned by a reviewer, a provider response)
  would run on every player of the shipped game.

## Commits

Conventional Commits, validated by pre-commit. See
[COMMIT_CONVENTION.md](COMMIT_CONVENTION.md) for types, scopes, and examples.

## License

Licensed under the CeCILL Free Software License Agreement v2.1, a French
open source license compatible with the GNU GPL. See [LICENSE.md](LICENSE.md).

## Disclaimer

Ren'Py Translation Studio is not affiliated with, endorsed by, or sponsored by
Ren'Py. The name is used only to designate the engine this tool reads and
writes files for.
