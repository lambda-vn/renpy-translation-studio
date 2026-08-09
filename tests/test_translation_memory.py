"""Tests for core/storage/translation_memory.py."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.storage.translation_memory import TranslationMemory


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
