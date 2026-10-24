//! What the server holds: the permissions, and the project in hand.
//! Port of `mcp_server/session.py`.
//!
//! One process serves whichever project the client asks for, chosen
//! among the ones already set up in the application. The permissions
//! belong to the process and never to a call: a client reads the game's
//! own text, so a line of dialogue asking for every validated
//! translation to be dropped would otherwise be a request the model is
//! free to grant itself.
//!
//! The same rule explains why `use_project` only accepts a project the
//! registry already knows. The application writes that registry when a
//! human sets a game up, so the reachable set is one the user built, not
//! one the model names.

use std::path::{Path, PathBuf};

use rusqlite::Connection;

use crate::core::storage::{recent_projects, repositories, Database};

#[derive(Debug, thiserror::Error)]
pub enum SessionError {
    #[error(
        "No project open. Call list_projects to see the games set up in the application, \
         then use_project to pick one."
    )]
    NoProjectOpen,
    #[error(
        "{0} is not a project this server can open. Set it up in the application first; \
         list_projects shows the ones it already knows."
    )]
    UnknownProject(String),
    #[error(
        "No project database at {0}. Open this game in the application and extract it once first."
    )]
    NoDatabase(String),
    #[error(
        "This server was started pinned to {0}. Restart it without --project to reach \
         other projects."
    )]
    PinnedElsewhere(String),
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

/// The permissions of the process and the project currently open.
pub struct ServerState {
    pub allow_overwrite_validated: bool,
    pub allow_clear: bool,
    pub pinned: Option<PathBuf>,
    pub current: Option<ProjectSession>,
    pub registry: PathBuf,
    pub memory_path: PathBuf,
}

impl Default for ServerState {
    fn default() -> Self {
        Self::new()
    }
}

impl ServerState {
    /// A fresh, unpinned state reading the real machine-wide project
    /// registry.
    pub fn new() -> Self {
        Self {
            allow_overwrite_validated: false,
            allow_clear: false,
            pinned: None,
            current: None,
            registry: recent_projects::default_path(),
            memory_path: crate::core::storage::translation_memory::default_path(),
        }
    }

    /// The games the application has set up on this machine.
    ///
    /// Re-resolved on every call, not just read back verbatim: a registry
    /// entry written before this run must still compare equal to a fresh
    /// [`recent_projects::resolve`] of the same path in [`Self::use_project`],
    /// whatever a platform's canonical form happens to look like (the
    /// `\\?\` prefix Windows adds, a symlink elsewhere).
    pub fn known_projects(&self) -> Vec<PathBuf> {
        recent_projects::all(&self.registry)
            .into_iter()
            .map(|path| recent_projects::resolve(&path))
            .collect()
    }

    /// Return the open project.
    pub fn require(&self) -> Result<&ProjectSession, SessionError> {
        self.current.as_ref().ok_or(SessionError::NoProjectOpen)
    }

    /// Open a project, closing the one held before it.
    pub fn use_project(&mut self, project: &Path) -> Result<&ProjectSession, SessionError> {
        let target = recent_projects::resolve(project);
        if let Some(pinned) = &self.pinned {
            if target != *pinned {
                return Err(SessionError::PinnedElsewhere(pinned.display().to_string()));
            }
        } else if !self.known_projects().contains(&target) {
            return Err(SessionError::UnknownProject(target.display().to_string()));
        }

        let session = open_project(&target)?;
        self.current = Some(session);
        Ok(self.current.as_ref().expect("just assigned"))
    }

    /// Pin the server to a single project, opened immediately.
    ///
    /// Unlike [`Self::use_project`], the target need not already be in
    /// the registry: `--project` is how a client reaches a game the
    /// application has not necessarily listed yet, as long as it has
    /// been extracted at least once.
    pub fn pin(&mut self, project: &Path) -> Result<(), SessionError> {
        let resolved = recent_projects::resolve(project);
        self.pinned = Some(resolved.clone());
        self.use_project(&resolved).map(|_| ())
    }
}

/// Open a project set up by the application.
///
/// The database is never created here. A missing one means the path is
/// not a project the application has extracted yet, and answering an
/// empty project would look like a game with nothing to translate.
pub fn open_project(project: &Path) -> Result<ProjectSession, SessionError> {
    let db_path = Database::path_for(project);
    if !db_path.is_file() {
        return Err(SessionError::NoDatabase(db_path.display().to_string()));
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

    fn temp_project() -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "rts-mcp-session-test-{nanos}-{:?}",
            std::thread::current().id()
        ))
    }

    fn extracted_project() -> PathBuf {
        let project = temp_project();
        let db_path = Database::path_for(&project);
        std::fs::create_dir_all(db_path.parent().unwrap()).unwrap();
        Database::open(&db_path).unwrap();
        project
    }

    #[test]
    fn require_fails_before_a_project_is_opened() {
        let state = ServerState::new();
        assert!(matches!(state.require(), Err(SessionError::NoProjectOpen)));
    }

    #[test]
    fn use_project_refuses_a_path_outside_the_registry() {
        let mut state = ServerState::new();
        state.registry = temp_project();
        let project = extracted_project();

        let result = state.use_project(&project);
        assert!(matches!(result, Err(SessionError::UnknownProject(_))));
    }

    #[test]
    fn use_project_opens_a_registered_extracted_project() {
        let mut state = ServerState::new();
        state.registry = temp_project();
        let project = extracted_project();
        recent_projects::add(&state.registry, &project);

        let session = state.use_project(&project).unwrap();
        assert_eq!(session.path, recent_projects::resolve(&project));
    }

    #[test]
    fn use_project_refuses_a_registered_path_with_no_database() {
        let mut state = ServerState::new();
        state.registry = temp_project();
        let project = temp_project();
        recent_projects::add(&state.registry, &project);

        let result = state.use_project(&project);
        assert!(matches!(result, Err(SessionError::NoDatabase(_))));
    }

    #[test]
    fn pin_refuses_every_other_project_afterwards() {
        let mut state = ServerState::new();
        state.registry = temp_project();
        let pinned = extracted_project();
        let other = extracted_project();

        state.pin(&pinned).unwrap();
        let result = state.use_project(&other);
        assert!(matches!(result, Err(SessionError::PinnedElsewhere(_))));
    }

    #[test]
    fn relative_and_absolute_round_trip() {
        let mut state = ServerState::new();
        state.registry = temp_project();
        let project = extracted_project();
        recent_projects::add(&state.registry, &project);
        let session = state.use_project(&project).unwrap();

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
