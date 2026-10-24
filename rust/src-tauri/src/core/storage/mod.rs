//! SQLite storage for a single project, plus the machine-wide registry of
//! which projects exist. Port of `core/storage/`.

pub mod database;
pub mod recent_projects;
pub mod repositories;
pub mod translation_memory;

pub use database::Database;
