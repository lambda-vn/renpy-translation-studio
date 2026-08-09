# Security Policy

## Supported versions

The project is in beta. Only the latest commit on `main` receives fixes;
there is no maintained release branch yet.

## Reporting a vulnerability

Please report privately through GitHub, using **Security > Report a
vulnerability** on this repository. Do not open a public issue for a
vulnerability.

Include what you did, what happened, and what you expected. A `.rpy`
excerpt or a bilingual file reproducing the problem helps a lot. Never
include an API key: the report is private, but nothing needs it.

Expect a first answer within a week. The project is maintained by one
person on their own time, so a fix may take longer than the
acknowledgement.

## What is in scope

This application reads a game's files, stores text in a local SQLite
database, sends text to translation providers, and writes `.rpy` files
that the Ren'Py engine executes. The interesting boundaries are:

- **Anything that ends up in a `.rpy` file.** The `tl/` folder produced
  here ships to the players of the translated game. A translation is
  inserted between double quotes and escaped, and one that adds a
  `[interpolation]` absent from the source text is refused, since Ren'Py
  evaluates the contents of square brackets as a Python expression.
- **Bilingual files taken as input** (CSV, XLIFF 1.2, JSON). These come
  from third parties, such as a reviewer or an agency, and are the main
  untrusted input.
- **Provider responses.** A hostile or compromised endpoint, a
  self-hosted LibreTranslate instance in particular, is untrusted input
  on the same path.
- **The MCP server.** It hands the same actions to an assistant, and
  what that assistant reads is the game's own text, written by somebody
  else. A line of dialogue asking for translations to be dropped must
  therefore not be a request it can grant itself: the two destructive
  permissions, `--allow-overwrite-validated` and `--allow-clear`, are
  command-line flags and nothing said over the protocol turns them on.
  It opens only projects already set up in the application, never an
  arbitrary folder, and everything it submits goes through the checks
  above.
- **The live notification endpoint.** While the review screen is open,
  the application listens on the loopback interface so another process
  can say which lines it just wrote. The port and a token are published
  in `<game>/.rts/live.json`, and a request without that token is
  refused. This is aimed at one thing: a web page can post to a local
  port, it cannot read your disk. It is not a defence against a program
  running as you, which could read the file, or simply write the
  database.
- **Paths and archives.** Game folders are resolved and bound-checked;
  zip entries reject `../` traversal.
- **API keys.** They live in the local settings file and are never
  logged, even partially, nor included in an error message.

## What is not in scope

The SQLite database in `<game>/.rts/` is local user data, not a trust
boundary. A process able to write it runs under your account and could
edit the game's `.rpy` files directly, so encrypting the database would
protect nothing. The same holds for `live.json` beside it.

Binaries produced by the build workflow are **not signed**. Windows
SmartScreen and macOS Gatekeeper will warn about them, and that warning
means unsigned, not tampered with. Verifying that a download matches
what the workflow built is on you until signing exists.
