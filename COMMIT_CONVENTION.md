# Commit Convention

This project enforces **Conventional Commits**. Every commit message is validated
by a local pre-commit hook at commit time. A non-conforming commit will be
**rejected** before it is written to the repository.

---

## Format

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

All three parts of the first line are mandatory except the scope, which is optional
but strongly recommended. The first line must not exceed **100 characters**.

---

## Types

| Type       | When to use                                                               |
|------------|---------------------------------------------------------------------------|
| `feat`     | A new feature visible to the user or to the application's public API     |
| `fix`      | A bug fix                                                                 |
| `docs`     | Documentation only (markdown files, docstrings)                          |
| `refactor` | Code change that neither adds a feature nor fixes a bug                   |
| `test`     | Adding or updating tests, no production code change                       |
| `chore`    | Maintenance tasks: dependency updates, config files, CI tweaks            |
| `perf`     | A change that improves performance without altering behavior              |
| `ci`       | Changes to GitHub Actions workflows or CI configuration                   |

**Rules:**
- Use exactly one type per commit.
- Never mix a feature and a bug fix in the same commit. Split them.
- `refactor` must not change observable behavior. If it does, use `fix` or `feat`.

---

## Scope

The scope identifies the area of the codebase affected. It is written in lowercase,
using hyphens as separators.

| Scope               | Area                                                          |
|---------------------|---------------------------------------------------------------|
| `archive`           | `.rpa` archive reading and extraction (`core/renpy/archive.py`)|
| `parser`            | `TranslateBlockParser` (`core/renpy/parser.py`)               |
| `writer`            | Translation rewriting into `.rpy` files (`core/renpy/writer.py`)|
| `renpy-cli`         | `RenpyCli` subprocess wrapper around the Ren'Py SDK           |
| `exporter`          | Zip export and `GameNameResolver` (`core/exporter.py`)        |
| `validators`        | Language codes, safe paths, project folder checks             |
| `storage`           | SQLite database, repositories, schema migrations, recent projects|
| `providers`         | Any `TranslationProvider` implementation or the registry      |
| `deepl`             | `DeepLProvider` specifically                                  |
| `ollama`            | `OllamaProvider` specifically                                 |
| `libretranslate`    | `LibreTranslateProvider` specifically                         |
| `claude`            | Claude (Anthropic) provider specifically                      |
| `mistral`           | Mistral provider specifically                                 |
| `onboarding`        | Onboarding view (`app/views/onboarding.py`)                   |
| `project-setup`     | Project setup view (`app/views/project_setup.py`)             |
| `translation-review`| Review view (`app/views/review_view.py`)                      |
| `export-view`       | Export view (`app/views/export_view.py`)                      |
| `settings`          | Persistent settings and the settings dialog                   |
| `i18n`              | UI translations (`core/i18n.py`, `src/locales/`)              |
| `mcp`               | MCP server exposing projects to a client (`src/mcp_server/`)  |
| `ui`                | Cross-cutting UI: theme, shared components, navigation        |
| `ci`                | GitHub Actions workflows                                      |
| `deps`              | `uv` dependency changes                                       |

The scope is **optional** but should be included whenever the change is confined
to a clearly identifiable area. Omit it only for cross-cutting changes that affect
multiple areas simultaneously.

---

## Description

- Written in **English**, imperative mood, present tense.
- **Do not** capitalize the first letter.
- **Do not** end with a period.
- Describe *what* the commit does, not *why* (the why goes in the body).

```
# Correct
feat(parser): add support for multiline dialogue blocks
fix(exporter): exclude .rpyc files from generated zip
docs(onboarding): document SDK path validation behavior

# Wrong
feat(parser): Added support for multiline dialogue blocks.   <- past tense + period
fix: fixed a bug                                             <- vague, no scope
feat(parser): Multiline support                              <- not imperative mood
```

---

## Body

The body is optional but expected for any non-trivial commit. It explains **why**
the change was made, and any context that is not obvious from the diff.

- Separated from the description by a blank line.
- Wrap lines at **72 characters**.
- May include multiple paragraphs.

```
fix(parser): handle narratorlines without character variable

Ren'Py allows dialogue without an explicit character variable:

    "This is narrator text."

The previous regex required a variable prefix and silently skipped
these lines. They are now parsed correctly and stored with a null
character_variable value, consistent with the TranslationUnit schema.
```

---

## Footer

Used for three purposes only:

**Breaking changes:**
```
feat(providers): rename translateBatch return type

BREAKING CHANGE: TranslateBatchResult.items is now TranslateBatchResult.entries.
Update all callers accordingly.
```

**Issue references:**
```
fix(exporter): prevent path traversal in zip entry names

Closes #42
```

**AI attribution (mandatory when an LLM contributed):**

When a commit contains code or a message produced with the help of an LLM,
its use must be disclosed, in one of two equivalent ways:

- The LLM adds a `Co-Authored-By` trailer identifying itself, one per line,
  as the last lines of the message:
  ```
  feat(parser): add support for multiline dialogue blocks

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  ```
- Or the human author states the LLM use explicitly in the body:
  ```
  feat(parser): add support for multiline dialogue blocks

  Drafted with the help of an LLM, reviewed and validated by the author.
  ```

A commit that involved no LLM carries no such trailer or note.

---

## Full examples

**Simple feature, no body needed:**
```
feat(onboarding): add SDK path validation feedback on step 2
```

**Bug fix with context:**
```
fix(renpy-cli): pass arguments as list to avoid shell injection

The previous implementation interpolated user-provided paths directly
into a shell string. subprocess.run must always receive a list of
arguments with shell=False, never a concatenated string, to prevent
shell injection regardless of the input content.
```

**Dependency update:**
```
chore(deps): update deepl to 1.30.0
```

**Schema migration:**
```
feat(storage): add draft status to the translation_units schema

Introduces the draft status in the CHECK constraint and an automatic
migration for existing databases, so edited-but-unvalidated text is
counted and clearable.
```

**Test addition:**
```
test(parser): add fixture for multiline dialogue blocks
```

**Documentation:**
```
docs: add COMMIT_CONVENTION.md
```

---

## What the commit-msg hook rejects

Commit messages are validated by a local pre-commit hook running
`scripts/check_commit_msg.py` at the `commit-msg` stage. It matches the first
line against this pattern:

```
^(feat|fix|docs|style|refactor|test|chore|ci|perf|build|revert)(\([a-zA-Z0-9_\-\.]+\))?(!)?: .+
```

Any commit whose first line does not match is rejected immediately. Common
mistakes that trigger a rejection:

- Using a type outside the pattern (e.g. `update`, `wip`)
- Forgetting the colon and space after the type or scope
- Using uppercase for the type (e.g. `Feat` instead of `feat`)
- An empty description after the colon

The hook only checks the first line's shape. The 100-character limit, the
lowercase-hyphenated scope, and the curated type set documented above are
project conventions, not enforced by the hook: `style`, `build`, and `revert`
match the pattern but are not used in this project. The optional `!` marks a
breaking change (`feat!:`).

---

## Guidance for AI agents

When generating a commit message:

1. Read the diff carefully before writing the message.
2. Identify a single coherent intent. If the diff contains multiple unrelated
   changes, request that they be split into separate commits rather than combining
   them under a vague description.
3. Choose the most specific scope available in the table above. If the change
   spans two scopes equally, omit the scope rather than picking an imprecise one.
4. The description must describe the observable effect of the change, not the
   implementation detail. Prefer `add support for X` over `update regex in Y`.
5. Always write the body when the change involves a security decision, a
   non-obvious workaround, or a constraint imposed by an external system
   (Ren'Py behavior, Flet limitation, Ollama API quirk, etc.).
6. Never invent a type that is not in the allowed list.
7. Never use `WIP` or similar markers. A commit must represent a complete,
   reviewable unit of work.
8. Always add a `Co-Authored-By` trailer identifying yourself as the last
   line of any commit you generate (see the AI attribution footer). Never
   remove an existing one.
