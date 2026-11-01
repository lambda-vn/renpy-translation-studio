//! An open project: its folder and the connection reading its database.
//!
//! Shared by the desktop commands and the MCP server. Opening is the same
//! for both; what differs is who may ask for which folder, and that gate
//! stays with each caller (`mcp_server::session` checks the registry, the
//! application lets a human pick any folder through a native dialog).

use std::path::{Path, PathBuf};

use rusqlite::Connection;

use crate::core::storage::{repositories, Database};

/// Why a project could not be opened.
#[derive(Debug, thiserror::Error)]
pub enum OpenError {
    #[error(
        "No project database at {0}. Open this game in the application and extract it once first."
    )]
    NoDatabase(String),
    #[error(transparent)]
    Sqlite(#[from] rusqlite::Error),
}

/// An open project and the connection reading it.
pub struct ProjectSession {
    pub path: PathBuf,
    db: Database,
}

impl ProjectSession {
    pub fn conn(&self) -> &Connection {
        self.db.conn()
    }

    /// Language the game is written in, English when unrecorded.
    pub fn source_language(&self) -> String {
        repositories::get_project_meta(self.conn(), "source_language")
            .ok()
            .flatten()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "english".to_string())
    }

    /// Language being translated into, empty when unrecorded.
    pub fn target_language(&self) -> String {
        repositories::get_project_meta(self.conn(), "target_language")
            .ok()
            .flatten()
            .unwrap_or_default()
    }

    /// Shorten a stored path to what it is under the project root.
    ///
    /// Files are stored with the absolute path they had when the game
    /// was extracted. Sent as they are, they repeat the user's disk
    /// layout on every line of every page, and they are wrong as soon as
    /// the project moves.
    pub fn relative(&self, source_file: &str) -> String {
        match Path::new(source_file).strip_prefix(&self.path) {
            Ok(relative) => relative.to_string_lossy().replace('\\', "/"),
            Err(_) => source_file.to_string(),
        }
    }

    /// Turn a path a client sent back into the one the database holds.
    ///
    /// Accepts both forms, a client having no reason to know which one
    /// it was given. Joined component by component rather than with a
    /// single `PathBuf::join`: `relative()` always hands back
    /// forward-slash paths, and `Path::join` appends its argument's raw
    /// string rather than reparsing it, so on Windows a plain join would
    /// leave a stray `/` inside an otherwise backslash-separated path —
    /// a string the stored, backslash-only `source_file` would never
    /// exact-match in SQL.
    pub fn absolute(&self, source_file: &str) -> String {
        let candidate = Path::new(source_file);
        if candidate.is_absolute() {
            source_file.to_string()
        } else {
            let mut joined = self.path.clone();
            joined.extend(candidate.components());
            joined.to_string_lossy().into_owned()
        }
    }
}

/// Open a project set up by the application.
///
/// The database is never created here. A missing one means the path is
/// not a project the application has extracted yet, and answering an
/// empty project would look like a game with nothing to translate.
///
/// # Errors
///
/// [`OpenError::NoDatabase`] when the project has never been extracted,
/// [`OpenError::Sqlite`] when its database cannot be opened.
pub fn open_project(project: &Path) -> Result<ProjectSession, OpenError> {
    let db_path = Database::path_for(project);
    if !db_path.is_file() {
        return Err(OpenError::NoDatabase(db_path.display().to_string()));
    }
    let db = Database::open(&db_path)?;
    Ok(ProjectSession {
        path: project.to_path_buf(),
        db,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extracted_project() -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let project = std::env::temp_dir().join(format!(
            "rts-project-session-test-{nanos}-{:?}",
            std::thread::current().id()
        ));
        let db_path = Database::path_for(&project);
        std::fs::create_dir_all(db_path.parent().unwrap()).unwrap();
        Database::open(&db_path).unwrap();
        project
    }

    #[test]
    fn open_project_refuses_a_folder_never_extracted() {
        let project = std::env::temp_dir().join("rts-project-session-test-missing");
        assert!(matches!(
            open_project(&project),
            Err(OpenError::NoDatabase(_))
        ));
    }

    #[test]
    fn relative_and_absolute_round_trip() {
        let session = open_project(&extracted_project()).unwrap();

        let stored = session.path.join("game").join("script.rpy");
        let relative = session.relative(&stored.to_string_lossy());
        assert_eq!(relative, "game/script.rpy");
        assert_eq!(Path::new(&session.absolute(&relative)), stored.as_path());

        // The stored form is what a SQL `WHERE source_file = ?` compares
        // against exact-match — Path equality alone (above) would not
        // have caught a stray `/` left over from a naive string join.
        assert_eq!(session.absolute(&relative), stored.to_string_lossy());
    }
}
