[← Documentation](README.md)

# MCP server

*[Version française](../fr/mcp-server.md)*

A second entry point onto the same core, so an assistant you already pay
for can do the translating — no API key, no GPU.

## Setting it up

The server is launched by the client, over stdio:

```bash
claude mcp add renpy-studio -- uv run --directory /path/to/renpy-translation-studio python -m mcp_server
```

There is deliberately **no installed console script**. On Windows an
`rts-mcp.exe` would be locked as long as a client held the server open,
which would stop `uv run` from reinstalling the project and therefore stop
the application from starting.

## What it can reach

`list_projects` reads the same recent-project registry the application
writes when a human sets a game up, and `use_project` opens one of them.
Anything absent from that list is refused.

That is the whole permission model for paths: the reachable set is the one
**you** built by configuring games, not the one a model can name.
`--project <path>` pins a server to a single game.

## What it can do

Seventeen tools, matching the actions of the review screen: list files,
list units with the same filters and search, ask for the context around a
line, submit translations, read and write the character glossary and the
universe summary, fill from the translation memory, set notes and review
flags, report progress.

A submission goes through the **same quality checks** as any provider's
answer and arrives as **AI suggested**, for you to review like any other
suggestion. Lines you already validated are left alone.

Paths come out relative to the project root, and both forms are accepted
going in. The database stores absolute paths from extraction time, and
sending those would repeat your disk layout on every line of every page.

## The two things it cannot do

`--allow-overwrite-validated` lets a submission replace a line you
validated, landing it as a draft. `--allow-clear` allows deleting
translations in bulk.

Both are **command-line flags and nothing else** — never tool arguments.
The reason is specific: the assistant reads the game's own text, written
by a third party, so a line of dialogue asking for either must not be a
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
instead of showing them fill. The row your cursor is in is always skipped.

The notification is a **bonus, never a dependency**. Nobody listening, no
file, connection refused — all ordinary. Close the application and the
assistant keeps translating.

The token stops exactly one thing: a web page, which can post to a local
port but cannot read your disk. It stops nothing running under your own
account.
