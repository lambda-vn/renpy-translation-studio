[← Documentation](README.md)

# Troubleshooting

*[Version française](../fr/troubleshooting.md)*

## Extraction

**Ren'Py refuses some source files.** The lines of every refused file are
absent from the extraction, and the application names them. This is almost
always a version mismatch: Ren'Py 8 requires a value for screen properties
that Ren'Py 7 accepted without one. Use the engine the game ships with
rather than your SDK — that is already the default when this system can
run it. See [Installation](installation.md).

**No engine could be found.** Either the game ships none this system can
run — a `-win` build opened from Linux only contains Windows runtimes — or
no SDK is configured. The message says which. Set an SDK path in the
settings dialog.

**The unit count changed after switching extractors.** Expected, and
small. The SDK's own `common.rpy` carries launcher strings the game does
not have.

## Quality checks

Two kinds, and the difference matters.

**Warnings** are advisory and shown under the field — *Translation 32%
longer than source text*, for instance. Nothing is blocked; long
translations overflow Ren'Py text boxes often enough to be worth a glance.

**Refusals** reject the translation outright. The important one:

> A translation may not introduce an `[interpolation]` the source text did
> not have.

Ren'Py evaluates the contents of square brackets as a **Python
expression**. A translation that invents `[something]` therefore ships
executable code to every player of the game. The untrusted inputs here are
real ones — a bilingual file returned by a proofreader, an answer from a
provider — and the `tl/` folder you produce goes out to players. This
check is not relaxable.

Filter on *In error* to find refused lines.

## Providers

**A connection test fails.** Turn on **Verbose logging** at the bottom of
the provider screen; every request and response is then logged at DEBUG
level. That is the first thing to check on any provider problem.

**Ollama returns nonsense on short strings.** Small quantized models mix
up short similar labels — menu entries, button captions — within one
batch. Lower **Units per request**, or use a larger model. The warning in
the Ollama panel says as much.

**A model stops early or duplicates lines.** Same family of problem, same
answer: smaller batches.

**Ollama on a cloud model is slow in small batches.** The 8192-token
context ceiling that protects local models does not apply to cloud models,
which are recognised by their `-cloud` suffix; nothing is loaded on your
machine so it protects nothing there.

## Translations

**A wrong AI suggestion keeps coming back.** It does not come back — it
never left. A translation job only sends `not_translated` lines, so an
existing suggestion is neither retried nor overwritten. Fix it, or clear
it so the next job picks it up.

**A job seems to skip lines.** Same reason: anything already carrying text
is skipped by design.

**A validated line was replaced.** That should be impossible from a job,
an import, the memory, or the MCP server. It happens when someone types in
the field, which turns the line into a draft. The MCP server can do it
only if it was started with `--allow-overwrite-validated`, and then it
lands as a draft too.

## Files and storage

**Where are my translations?** In `<game>/.rts/translations.db`. Moving
the game folder carries them along. Two sidecar files,
`translations.db-wal` and `-shm`, belong to it — copy them too if you copy
a project by hand.

**The application warns it could not switch to WAL.** The database sits on
a filesystem without shared memory, typically a network share. Everything
still works; two processes reaching the project at once may block each
other.

**Nothing changed in the game.** Saving to `.rpy` is a separate step from
editing. Watch the orange counter next to **Save to .rpy**.

## Interface

**The file panel is too narrow for long names.** It is fixed. Flet exposes
no resizable panel control, and a hand-made drag handle costs a
Python/Flutter round trip per frame — it was tried and it felt bad. Long
names are covered by the tooltip.

**The window icon is Flet's logo in development.** `flet run` launches
Flet's own prebuilt client, and Windows draws the task bar icon from the
executable it launched. Only a packaged build carries the real icon.
