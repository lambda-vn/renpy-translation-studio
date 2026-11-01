//! Data access layer for translation units, characters and project
//! metadata. Port of `core/storage/repositories.py`.
//!
//! Deliberately partial for `2.0.0-alpha.2`, extended in `2.0.0-beta.1`
//! with the pagination, neighbour-window, batch-update and bulk-clear
//! queries the MCP server needs, and with the three extraction-pipeline
//! methods (`resync_sources`, `transfer_orphan_translations`,
//! `delete_stale`) in `2.0.0-rc.2`. Still not ported: the
//! duplicate/search-count helpers used only by the review UI's side
//! panel, which belong with the review screen's remaining work.
//!
//! Python's repositories take an explicit `threading.Lock` shared across
//! callers on the same connection, working around `sqlite3.Connection`
//! not being safe to share across threads on its own. `rusqlite::
//! Connection` has the same restriction, but Rust already forces that
//! synchronization to be visible at the type level — a caller sharing a
//! connection across threads holds it behind a `Mutex`, so nothing extra
//! is threaded through every function here.

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
pub(crate) fn begin(conn: &Connection) -> rusqlite::Result<Option<Transaction<'_>>> {
    conn.is_autocommit()
        .then(|| conn.unchecked_transaction())
        .transpose()
}

/// Commit what [`begin`] opened; a no-op when the caller owns the transaction.
pub(crate) fn commit(tx: Option<Transaction<'_>>) -> rusqlite::Result<()> {
    tx.map_or(Ok(()), Transaction::commit)
}

/// `n` comma-separated `?` placeholders for an `IN (...)` clause.
pub(crate) fn sql_placeholders(n: usize) -> String {
    vec!["?"; n].join(",")
}
