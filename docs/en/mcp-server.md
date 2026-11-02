[← Documentation](README.md)

# MCP server

*[Version française](../fr/mcp-server.md)*

A second entry point onto the same core, so an assistant you already pay
for can do the translating — no API key, no GPU. It is a separate program,
`rts-mcp`, that speaks the Model Context Protocol over stdio.

## Setting it up

The server is launched by the client, which needs the path of the
executable.

### From the installed application

The installer puts `rts-mcp` (`rts-mcp.exe` on Windows) in the same folder
as the application's own executable, `renpy-translation-studio`. Point the
client at it:

```bash
claude mcp add renpy-studio -- "/path/to/rts-mcp"
```

Any other client takes the same two things in its configuration: the
command (that path) and its arguments (the flags below, if any).

### From the source

Build it once, then point the client at the result:

```bash
cargo build --release --bin rts-mcp --manifest-path rust/src-tauri/Cargo.toml
claude mcp add renpy-studio -- "/path/to/renpy-translation-studio/rust/src-tauri/target/release/rts-mcp"
```

`rts-mcp --help` lists the options. An unknown argument stops the server
with a message on its standard error.

## The command-line flags

| Flag | Effect |
|------|--------|
| `--project <path>` | Serve only this game folder — the one that holds `game/`. Without it, the client picks among the projects set up in the application. |
| `--allow-overwrite-validated` | Let a submission replace a line you validated. The replacement lands as a draft, never as validated. |
| `--allow-clear` | Allow deleting translations in bulk (`clear_translations`). |
| `--allow-edit-glossary` | Allow changing the character glossary and the universe summary. |

Nothing is allowed by default: without a flag, the matching tool refuses
with a message naming it.

## What it can reach

`list_projects` reads the same recent-project registry the application
writes when a human sets a game up (`projects.json`, in the configuration
folder: see [Installation](installation.md)), and `use_project` opens one
of them. Anything absent from that list is refused: **a game has to be set
up in the application first.**

That is the whole permission model for paths: the reachable set is the one
**you** built by configuring games, not the one a model can name.

`--project <path>` pins a server to a single game, and the server then
refuses every other one. The game must have been extracted at least once,
so that its `.rts` folder exists.

## What it can do

Seventeen tools, matching the actions of the review screen.

**Projects**

- `list_projects` — the games set up in the application.
- `use_project` — open one of them, by path.

**Reading**

- `list_files` — the translatable files with their progress.
- `project_progress` — how much of the whole project is translated.
- `list_units` — one page of a file's lines, with the same filters and
  search as the review screen.
- `get_unit_context` — the lines around one line, in file order.
- `list_characters` — the character glossary.
- `get_universe_summary` — the universe summary.

**Translating**

- `submit_translations` — send translations back, one batch at a time.
- `set_note` — leave a note on a line and flag it for a second look.
- `set_needs_review` — set or clear that flag.
- `fill_from_memory` — fill untranslated lines from the translation memory.

**Glossary** (needs `--allow-edit-glossary`)

- `upsert_character` and `delete_character`.
- `detect_characters` — detect the characters in the game's script.
- `set_universe_summary`.

**Clearing** (needs `--allow-clear`)

- `clear_translations` — back to *Not translated*, in bulk.

A submission goes through the **same quality checks** as any provider's
answer and arrives as **AI suggested**, for you to review like any other
suggestion. A line that drops a `{tag}` or an `[interpolation]`, or adds
an interpolation the source did not have, is refused. Lines you already
validated are left alone.

Paths come out relative to the project root, and both forms are accepted
going in. The database stores absolute paths from extraction time, and
sending those would repeat your disk layout on every line of every page.

## The things it cannot do on its own

`--allow-overwrite-validated`, `--allow-clear` and `--allow-edit-glossary`
are **command-line flags and nothing else** — never tool arguments. The
reason is specific: the assistant reads the game's own text, written by a
third party, so a line of dialogue asking for any of them must not be a
request the model can grant itself.

## Live refresh

Leave the review screen open while the assistant works and the lines fill
in under your eyes.

SQLite offers no cross-process notification, so the application listens on
the loopback interface while the review screen is open and publishes its
port and a token in `<game>/.rts/live.json`. The server posts the block
identifiers it just wrote.

Rows are updated **in place**, never by reloading the page: under a
*Not translated* filter, reloading would make them vanish as they fill
instead of showing them fill. The row your cursor is in, or one with a
pending edit, is never overwritten. Bulk actions (`fill_from_memory`,
`clear_translations`) reload the page instead, since they answer with a
count and have no identifiers to give.

The notification is a **bonus, never a dependency**. Nobody listening, no
file, connection refused — all ordinary. Close the application and the
assistant keeps translating.

The token stops exactly one thing: a web page, which can post to a local
port but cannot read your disk. It stops nothing running under your own
account.
