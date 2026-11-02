[← Documentation](README.md)

# Troubleshooting

*[Version française](../fr/troubleshooting.md)*

## Extraction

**Ren'Py refuses some source files.** The lines of every refused file are
absent from the extraction. A dialog titled *Some files could not be read*
names them; the game itself still works, since it falls back to the
compiled version of each one. This is almost always a version mismatch:
Ren'Py 8 requires a value for screen properties that Ren'Py 7 accepted
without one. Use the engine the game ships with rather than your SDK —
that is already the default when this system can run it. See
[Installation](installation.md).

**"This game ships no engine that can run here, and no Ren'Py SDK is
selected."** The game carries no engine this system can run, and no SDK is
configured. Set an SDK path in the settings dialog.

**"This game only ships a … engine, which cannot run on this system."**
Same situation, with the cause spelled out: a `-win` build opened from
Linux only contains Windows runtimes, for instance. Select a Ren'Py SDK to
extract it.

**"Ren'Py failed (exit …)".** Ren'Py ran and stopped with an error; its
output follows the message.

**"Ren'Py did not finish within the allowed time and was stopped."**
Extract again: the files it had already written are kept.

**"The Ren'Py executable could not be started."** The path of the SDK, or
the game's launcher, is not executable on this system. Check the path in
the settings dialog.

**"An extraction is already running."** Wait for it to finish.

**"Only the engine's built-in strings (common.rpy) were extracted."** No
dialogue came out. Check that the folder you picked is the game's own
project folder — the one holding `game/`, not `game/` itself — and that
`game/` holds `.rpy` files once the archived sources are unpacked.

**"This game's archives contain only compiled scripts (.rpyc)".** There is
no source to translate. A decompiler is required before this project can be
extracted.

**"Could not archive the existing translation folder".** Another program
is using `game/tl/`. Close the game, your editor, and any file manager or
terminal opened inside it, then try again.

**The unit count changed after switching engines.** Expected, and small.
The SDK's own `common.rpy` carries launcher strings the game does not
have.

## Quality checks

Two kinds, and the difference matters.

**Warnings** are advisory and shown under the field — *Translation 32%
longer than source text*, for instance. Nothing is blocked; long
translations overflow Ren'Py text boxes often enough to be worth a glance.

**Refusals** reject the translation outright (*Validation refused.*): a
missing or extra `{tag}`, a missing `[variable]`, an unexpected HTML tag,
and the important one:

> Interpolation absent from the source text, which Ren'Py would run as
> Python code.

Ren'Py evaluates the contents of square brackets as a **Python
expression**. A translation that invents `[something]` therefore ships
executable code to every player of the game. The untrusted inputs here are
real ones — a bilingual file returned by a proofreader, an answer from a
provider or from an MCP client — and the `tl/` folder you produce goes out
to players. This check is not relaxable.

Filter on *In error* to find refused lines. An empty translation is
refused too (*Translation cannot be empty.*).

## Providers

**A connection test fails.** Turn on **Verbose logging** in the settings
dialog, retry, then use **Open the log**: every request and response is
logged at DEBUG level, never with the API key. That is the first thing to
check on any provider problem.

**"Configure a translation provider in settings first" or "Configure … in
settings first".** The provider you picked has no key or URL yet. The
messages *DeepL API key not configured*, *Ollama model not configured* and
*LibreTranslate URL not configured* say which.

**"Could not save the API key: no system keyring is available on this
machine."** Keys are kept in the operating system's keyring and never in a
plain file. Without a keyring service (on Linux, a Secret Service such as
GNOME Keyring or KWallet), the key cannot be saved.

**"Connection failed — check your API key".** The key was refused. Paste it
again; the field shows *Key saved — type to replace it* when one is stored,
and **Remove the key** deletes it.

**A job stops with a provider error.** When the provider answers with a
refusal that retrying cannot fix (401, 403, 429, 456: bad key, quota,
rate limit), the job stops instead of replaying every line, and the
translations already received are kept. Fix the cause, then start the job
again: it only sends the lines still *Not translated*.

**"Cannot reach the Ollama server".** Check that Ollama is running and that
the **Server URL** is the right one.

**"The Ollama model … is not installed".** Run the `ollama pull` command
the message gives, then test the connection again: the **Model** list is
filled from the server.

**Ollama returns nonsense on short strings.** Small quantized models mix
up short similar labels — menu entries, button captions — within one
batch. Lower **Units per request**, or use a larger model. The warning in
the Ollama panel says as much.

**A model stops early or duplicates lines.** Same family of problem, same
answer: smaller batches.

**Ollama is slow and the banner mentions the CPU.** The model does not fit
in video memory and runs partly on the processor. Reduce **Units per
request** or use a smaller model.

**Ollama on a cloud model is slow in small batches.** The 8192-token
context ceiling that protects local models does not apply to cloud models,
which are recognised by their `-cloud` suffix; nothing is loaded on your
machine so it protects nothing there.

**LibreTranslate is slow or refuses requests.** Public instances have
unpredictable rate limits; self-hosting is recommended. The panel also
warns when the URL is `http://` to a non-local host, since the API key
would travel unencrypted.

## Translations

**A wrong AI suggestion keeps coming back.** It does not come back — it
never left. A translation job only sends *Not translated* lines, so an
existing suggestion is neither retried nor overwritten. Fix it, or clear
it so the next job picks it up. Drafts are the one exception: when some
exist, the application asks whether to retranslate them (*With drafts*)
or not (*Without drafts*).

**A job seems to skip lines.** Same reason: anything already carrying text
is skipped by design. The banner also reports the messages with nothing to
translate, copied as they are, and the repeated messages that reuse the
translation of their first occurrence.

**A validated line was replaced.** That should be impossible from a job,
an import, the memory, or the MCP server. It happens when someone types in
the field, which turns the line into a draft. The MCP server can do it
only if it was started with `--allow-overwrite-validated`, and then it
lands as a draft too.

## Files and storage

**Where are my translations?** In `<game>/.rts/translations.db`. Moving
the game folder carries them along. Two sidecar files,
`translations.db-wal` and `-shm`, belong to it — copy them too if you copy
a project by hand. Settings, the recent-project list and the log live in
the configuration folder described in [Installation](installation.md).

**The log says it could not switch to WAL.** The database sits on a
filesystem without shared memory, typically a network share. Everything
still works; two processes reaching the project at once (the application
and the MCP server, for instance) may block each other.

**Nothing changed in the game.** Saving to `.rpy` is a separate step from
editing. Watch the counter next to **Save to .rpy**: *N lines not written
to .rpy*.

**The export says translations are missing.** The export screen warns when
translations have not been written to the files, or when the `tl/` files
were modified outside the application since the last save — those changes
would be lost on the next save. Save to `.rpy` first. *No translation
directory found. Run extraction first.* means the game was never extracted
for this language.
