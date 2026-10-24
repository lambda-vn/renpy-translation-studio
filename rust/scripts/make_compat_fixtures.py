"""Regenerate the 1.0.0 compatibility fixtures under src-tauri/tests/fixtures.

The Rust application promises to read what the 1.0.0 Python application
wrote. A fixture written by hand would only prove the Rust code agrees with
itself, so these are produced by the Python code of the v1.0.0 tag itself:

    git archive v1.0.0 src | tar -x -C <scratch>/v1
    uv run python rust/scripts/make_compat_fixtures.py \
        --src <scratch>/v1/src --out rust/src-tauri/tests/fixtures/compat

Nothing here touches the real machine-wide config: app_dirs.config_dir() is
pointed at a throwaway folder before settings or the memory are imported,
and no API key (OS keyring) is ever written.
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT_AS_STORED = "D:\\VN\\Games\\Demo"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--src", required=True, type=Path, help="src/ of the v1.0.0 tag"
    )
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    sys.path.insert(0, str(args.src.resolve()))
    scratch = Path(tempfile.mkdtemp(prefix="rts-compat-"))

    import core.app_dirs as app_dirs

    app_dirs.config_dir = lambda: scratch  # type: ignore[assignment]

    from core.settings import Settings
    from core.storage.database import Database
    from core.storage.recent_projects import RecentProjects
    from core.storage.repositories import (
        CharacterRepository,
        ProjectMetaRepository,
        TranslationUnitRepository,
    )
    from core.storage.translation_memory import TranslationMemory

    out = args.out
    if out.exists():
        shutil.rmtree(out)
    project = out / "project"
    (project / ".rts").mkdir(parents=True)

    db = Database(Database.path_for(project))
    db.connect()
    units = TranslationUnitRepository(db.conn, db.lock)
    stored = f"{PROJECT_ROOT_AS_STORED}\\game\\tl\\french"
    units.bulk_insert(
        [
            {
                "block_id": "start_a1",
                "source_file": f"{stored}\\script.rpy",
                "source_line": 10,
                "character_variable": "e",
                "source_text": "Hello [name].",
            },
            {
                "block_id": "start_a2",
                "source_file": f"{stored}\\script.rpy",
                "source_line": 20,
                "character_variable": "e",
                "source_text": "Goodbye.",
            },
            {
                "block_id": "start_a3",
                "source_file": f"{stored}\\script.rpy",
                "source_line": 30,
                "character_variable": None,
                "source_text": "...",
            },
            {
                "block_id": "start_a4",
                "source_file": f"{stored}\\script.rpy",
                "source_line": 40,
                "character_variable": "m",
                "source_text": "Caf\u00e9 \u00e0 la cr\u00e8me \u2014 \u00fcber",
            },
            {
                "block_id": "start_a5",
                "source_file": f"{stored}\\script.rpy",
                "source_line": 50,
                "character_variable": "e",
                "source_text": "Still to do.",
            },
            {
                "block_id": "strings_deadbeef",
                "source_file": f"{stored}\\common.rpy",
                "source_line": 3,
                "character_variable": None,
                "source_text": "Yes",
            },
        ]
    )
    units.update_translation("start_a1", "Bonjour [name].", "human_validated")
    units.update_translation("start_a2", "Au revoir.", "ai_suggested")
    units.mark_as_draft("start_a3", "\u2026")
    units.update_translation("start_a4", "Caf\u00e9 \u00e0 la cr\u00e8me", "imported")
    units.set_note("start_a5", "check the tone")
    units.update_translation("strings_deadbeef", "Oui", "human_validated")

    characters = CharacterRepository(db.conn, db.lock)
    characters.upsert("e", "Eileen")
    characters.update_notes("e", "female, formal\nEileen -> Aline")
    characters.upsert("m", "Mark")

    meta = ProjectMetaRepository(db.conn, db.lock)
    meta.set("source_language", "english")
    meta.set("target_language", "french")
    meta.set("universe_summary", "A quiet seaside town.")
    db.close()
    for leftover in (project / ".rts").glob("translations.db-*"):
        leftover.unlink()

    settings_dir = out / "config"
    settings_dir.mkdir()
    settings = Settings()
    for key, value in {
        "locale": "fr",
        "theme": "dark",
        "default_provider": "ollama",
        "ollama_endpoint": "http://localhost:11434",
        "ollama_model": "llama3.1",
        "ollama_batch_size": "8",
        "libretranslate_url": "http://localhost:5000",
        "verbose_logging": "true",
    }.items():
        settings.set(key, value)
    shutil.copy(scratch / "settings.json", settings_dir / "settings.json")

    memory = TranslationMemory(settings_dir / "memory.db")
    memory.remember(
        [
            ("Hello.", "Bonjour."),
            ("Yes", "Oui"),
            ("Caf\u00e9 \u00e0 la cr\u00e8me", "Caf\u00e9 cr\u00e8me"),
            ("Press [key]!", "Appuyez sur [key] !"),
        ],
        "english",
        "french",
    )
    memory.remember([("Hello.", "Hallo.")], "english", "german")
    memory.close()
    for leftover in settings_dir.glob("memory.db-*"):
        leftover.unlink()

    registry = RecentProjects(settings_dir / "projects.json")
    registry.add(Path(PROJECT_ROOT_AS_STORED + "\\Other"))
    registry.add(Path(PROJECT_ROOT_AS_STORED))

    shutil.rmtree(scratch, ignore_errors=True)
    print(f"wrote fixtures to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
