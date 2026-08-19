"""Tests for core/storage/translation_memory.py."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.storage.translation_memory import TranslationMemory, normalized_key


@pytest.fixture()
def memory(tmp_path: Path) -> Iterator[TranslationMemory]:
    """Provide a translation memory backed by a throwaway file."""
    store = TranslationMemory(tmp_path / "memory.db")
    yield store
    store.close()


def test_lookup_returns_a_remembered_translation(memory: TranslationMemory) -> None:
    memory.remember([("Hello", "Bonjour")], "english", "french")
    assert memory.lookup(["Hello"], "english", "french") == {"Hello": "Bonjour"}


def test_lookup_omits_unknown_texts(memory: TranslationMemory) -> None:
    memory.remember([("Hello", "Bonjour")], "english", "french")
    assert memory.lookup(["Goodbye"], "english", "french") == {}


def test_lookup_is_scoped_to_the_language_pair(memory: TranslationMemory) -> None:
    memory.remember([("Hello", "Bonjour")], "english", "french")
    assert memory.lookup(["Hello"], "english", "spanish") == {}
    assert memory.lookup(["Hello"], "japanese", "french") == {}


def test_remember_replaces_an_earlier_translation(memory: TranslationMemory) -> None:
    memory.remember([("Hello", "Bonjour")], "english", "french")
    memory.remember([("Hello", "Salut")], "english", "french")
    assert memory.lookup(["Hello"], "english", "french") == {"Hello": "Salut"}


def test_remember_skips_empty_entries(memory: TranslationMemory) -> None:
    memory.remember([("", "Bonjour"), ("Hello", "")], "english", "french")
    assert memory.lookup(["", "Hello"], "english", "french") == {}


def test_lookup_without_texts_queries_nothing(memory: TranslationMemory) -> None:
    assert memory.lookup([], "english", "french") == {}


def test_lookup_handles_more_texts_than_sqlite_takes_at_once(
    memory: TranslationMemory,
) -> None:
    entries = [(f"Line {i}", f"Ligne {i}") for i in range(1200)]
    memory.remember(entries, "english", "french")
    found = memory.lookup([source for source, _ in entries], "english", "french")
    assert len(found) == 1200
    assert found["Line 999"] == "Ligne 999"


def test_stats_counts_each_language_pair(memory: TranslationMemory) -> None:
    memory.remember([("Hello", "Bonjour"), ("Bye", "Salut")], "english", "french")
    memory.remember([("Hello", "Hola")], "english", "spanish")
    assert memory.stats() == [("english", "french", 2), ("english", "spanish", 1)]


def test_stats_of_an_empty_memory(memory: TranslationMemory) -> None:
    assert memory.stats() == []


def test_forget_drops_one_pair_and_keeps_the_others(
    memory: TranslationMemory,
) -> None:
    memory.remember([("Hello", "Bonjour")], "english", "french")
    memory.remember([("Hello", "Hola")], "english", "spanish")

    assert memory.forget("english", "french") == 1
    assert memory.lookup(["Hello"], "english", "french") == {}
    assert memory.lookup(["Hello"], "english", "spanish") == {"Hello": "Hola"}


def test_a_new_memory_reads_what_an_earlier_one_wrote(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    first = TranslationMemory(path)
    first.remember([("Hello", "Bonjour")], "english", "french")
    first.close()

    second = TranslationMemory(path)
    found = second.lookup(["Hello"], "english", "french")
    second.close()
    assert found == {"Hello": "Bonjour"}


def test_normalized_key_ignores_case_spacing_and_trailing_punctuation() -> None:
    assert normalized_key("Riley...") == normalized_key("RILEY!")
    assert normalized_key("Yes   sir") == normalized_key("yes sir")
    assert normalized_key("Well, then-") == normalized_key("well, then")


def test_normalized_key_keeps_texts_with_different_code_apart() -> None:
    assert normalized_key("Hello [MC]") != normalized_key("Hello [mc]")
    assert normalized_key("Wait{p=1}") != normalized_key("Wait{p=2}")
    assert normalized_key("{i}Yes{/i}") != normalized_key("Yes")


def test_normalized_key_does_not_empty_an_all_punctuation_text() -> None:
    assert normalized_key("...") != normalized_key("!!")
    assert normalized_key("...") == "..."


def test_lookup_answers_a_trailing_punctuation_variant(
    memory: TranslationMemory,
) -> None:
    memory.remember([("Riley...", "Riley...")], "english", "french")
    found = memory.lookup(["RILEY!", "Riley?!"], "english", "french")
    assert found == {"RILEY!": "Riley...", "Riley?!": "Riley..."}


def test_lookup_prefers_the_exact_text_over_a_normalised_neighbour(
    memory: TranslationMemory,
) -> None:
    memory.remember([("Yes", "Oui"), ("Yes!", "Oui !")], "english", "french")
    assert memory.lookup(["Yes!"], "english", "french") == {"Yes!": "Oui !"}


def test_lookup_picks_one_normalised_neighbour_and_always_the_same(
    memory: TranslationMemory,
) -> None:
    memory.remember([("Yes.", "Oui."), ("Yes!", "Ouais !")], "english", "french")
    first = memory.lookup(["YES"], "english", "french")
    assert first["YES"] in {"Oui.", "Ouais !"}
    assert memory.lookup(["YES"], "english", "french") == first
    assert memory.lookup(["Yes"], "english", "french")["Yes"] == first["YES"]


def test_a_later_validation_takes_over_a_normalised_neighbour(
    memory: TranslationMemory,
) -> None:
    memory.remember([("Yes.", "Oui.")], "english", "french")
    memory.remember([("Yes.", "Ouais.")], "english", "french")
    assert memory.lookup(["YES"], "english", "french") == {"YES": "Ouais."}


def test_lookup_does_not_import_a_variable_the_source_lacks(
    memory: TranslationMemory,
) -> None:
    memory.remember([("Hello [MC].", "Bonjour [MC].")], "english", "french")
    assert memory.lookup(["Hello."], "english", "french") == {}


def test_a_memory_written_before_the_normalised_key_gains_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "memory.db"
    legacy = sqlite3.connect(str(path))
    legacy.executescript("""
        CREATE TABLE memory (
            source_language TEXT NOT NULL,
            target_language TEXT NOT NULL,
            source_text     TEXT NOT NULL,
            translated_text TEXT NOT NULL,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (source_language, target_language, source_text)
        );
        INSERT INTO memory (source_language, target_language, source_text,
                            translated_text, updated_at)
        VALUES ('english', 'french', 'Riley...', 'Riley...', datetime('now'));
    """)
    legacy.commit()
    legacy.close()

    store = TranslationMemory(path)
    found = store.lookup(["RILEY!"], "english", "french")
    store.close()
    assert found == {"RILEY!": "Riley..."}
