//! Shared fixtures for the repository tests.

use rusqlite::Connection;

use crate::core::storage::database::Database;

use super::units::{bulk_insert, NewUnit};

pub(super) fn open_temp() -> Database {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "rts-repo-test-{nanos}-{:?}.db",
        std::thread::current().id()
    ));
    Database::open(&path).unwrap()
}

pub(super) fn seed(conn: &Connection) {
    bulk_insert(
        conn,
        &[
            NewUnit {
                block_id: "a",
                source_file: "script.rpy",
                source_line: 10,
                character_variable: Some("e"),
                source_text: "Hello.",
            },
            NewUnit {
                block_id: "b",
                source_file: "script.rpy",
                source_line: 20,
                character_variable: None,
                source_text: "Goodbye [name].",
            },
        ],
    )
    .unwrap();
}

pub(super) fn unit<'a>(block_id: &'a str, source_text: &'a str) -> NewUnit<'a> {
    NewUnit {
        block_id,
        source_file: "script.rpy",
        source_line: 1,
        character_variable: None,
        source_text,
    }
}
