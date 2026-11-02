//! Data access layer for translation units, characters and project
//! metadata.
//!
//! No lock is threaded through these functions: a `rusqlite::Connection`
//! cannot be shared across threads on its own, and a caller that does
//! share one holds it behind a `Mutex`, which keeps the synchronization
//! visible at the type level.

mod characters;
mod extraction;
mod meta;
mod queries;
#[cfg(test)]
mod test_support;
mod units;

pub use characters::*;
pub use extraction::*;
pub use meta::*;
pub use queries::*;
pub use units::*;

use rusqlite::{Connection, Transaction};

/// Open a transaction unless the caller already holds one, so a write is
/// atomic on its own and still composes inside a larger transaction
/// (SQLite does not nest them).
///
/// # Errors
///
/// Fails when SQLite cannot start the transaction.
pub(crate) fn begin(conn: &Connection) -> rusqlite::Result<Option<Transaction<'_>>> {
    conn.is_autocommit()
        .then(|| conn.unchecked_transaction())
        .transpose()
}

/// Commit what [`begin`] opened; a no-op when the caller owns the transaction.
///
/// # Errors
///
/// Fails when SQLite cannot commit the transaction.
pub(crate) fn commit(tx: Option<Transaction<'_>>) -> rusqlite::Result<()> {
    tx.map_or(Ok(()), Transaction::commit)
}

/// `n` comma-separated `?` placeholders for an `IN (...)` clause.
pub(crate) fn sql_placeholders(n: usize) -> String {
    vec!["?"; n].join(",")
}
