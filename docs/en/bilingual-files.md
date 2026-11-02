[← Documentation](README.md)

# Bilingual files

*[Version française](../fr/bilingual-files.md)*

Two ways to move translations in and out without touching the game files:
a file you send to someone, and a memory shared between your own projects.

## Import and export

![The bilingual file dialog](../images/07-interchange-en.png)

Reached from **Import / export…** in the **More actions** menu of the
review toolbar, or from **Import / export…** in a single file's
right-click menu.

| Format | For |
|---|---|
| **CSV (spreadsheet)** | A spreadsheet. The format a proofreader without special tools will accept. |
| **XLIFF 1.2 (OmegaT, memoQ)** | A CAT tool — OmegaT, memoQ, Trados. |
| **JSON** | A script of your own. |

**Export scope** is either **This file** (the file you are looking at) or
**All files**. **Export…** asks where to save the file; the whole scope
goes out, untranslated lines included, since sending it to a translator is
the point. Source files are written relative to the game folder.

**Import…** accepts `.csv`, `.xlf`, `.xliff` and `.json` files, in UTF-8.
Before anything is written, a confirmation dialog says how many
translations will be written and counts what will be left out.

### Coming back

Lines are paired by **block identifier**, never by position. That has one
consequence worth relying on: the file may come back **partial or
reordered** and it will still import correctly. A proofreader may delete
the rows they had nothing to say about, sort the sheet by speaker, or
send back only the first chapter.

Each line also carries the source text it was exported with. If the game
text changed since the export, the line is skipped rather than paired with
a text it was not written for.

What status a line gets depends on what comes back:

- A line the file marks as validated comes back **validated**: the
  *status* column in CSV and JSON, the `final` or `signed-off` state in
  XLIFF. This is how a file that left the application and returned
  untouched is restored as it was.
- Any other text a proofreader rewrote, or a status the application does
  not know, comes back **imported**, because it has not been read *here*.
  An *AI suggestion* that was rewritten in the file is no longer one.
- A line you already validated is left alone, unless the file marks that
  same line as validated.
- A rewritten line marked validated that fails a quality check (a lost
  `{tag}` or `[variable]`) is written as a **draft** instead.

> An imported file is untrusted input. Every line goes through the same
> quality checks as a provider's answer, and one that adds a Ren'Py
> `[interpolation]` the source did not have is refused outright, whatever
> its status: Ren'Py would run it as code. See
> [Troubleshooting](troubleshooting.md).

The confirmation dialog and the summary that follows name each case:

| The summary says | Meaning |
|---|---|
| *unknown in this project* | The block identifier is not in this project (typically a file from another game). Ignored. |
| *whose source text has changed since the export* | Skipped. |
| *without a translation* | The row came back empty. Ignored: what the project holds is not cleared. |
| *already validated, left untouched* | A validated line the file does not validate. |
| *written as drafts, refused by a quality check* | Written, but as drafts. |
| *refused, adding an interpolation absent from the source* | Not written. |

### Spreadsheet precautions

The game's text is untrusted, and a line such as `=HYPERLINK(...)` or
`-- Hello` is a formula to a spreadsheet. In a CSV export, any cell that
starts with `=`, `+`, `-` or `@` (or a tab or a carriage return) gets a
leading apostrophe, which the import removes again. The file is UTF-8 with
a byte order mark, so accented translations open correctly in Excel.

XLIFF is read without ever expanding entities: a document that declares
one is refused.

## Translation memory

**Memory**, in the **More actions** menu of the review toolbar, fills
untranslated lines from a store shared by every project on this machine.

- It is fed by **human validations only**. Nothing a provider suggested
  goes in until you have said yes to it.
- It answers for a **language pair**, on the source text as written, then
  on near-identical text: letter case, repeated spaces and trailing
  punctuation are ignored. `[variables]` and `{tags}` must match exactly.
- It fills **the whole project**, never a single file: the memory answers
  for a language pair, and a per-file scope would just make you walk every
  file to reach the same result.
- It only ever touches *Not translated* lines, so it needs no
  confirmation, and what it writes lands as **imported**.

It pays off from the second game in a series onward, and on the interface
strings of `screens.rpy` and `common.rpy`, which are nearly identical
across games.

The settings dialog lists, for each language pair, how many entries the
memory holds, and lets you forget a pair. Projects keep their own
translations when you do.
