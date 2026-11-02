//! What the server holds: the permissions, and the project in hand.
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

use crate::core::project_session::{open_project, OpenError, ProjectSession};
use crate::core::storage::recent_projects;

/// Why the server refused to hand out a project.
#[derive(Debug, thiserror::Error)]
pub enum SessionError {
    /// No project has been opened with `use_project` yet.
    #[error(
        "No project open. Call list_projects to see the games set up in the application, \
         then use_project to pick one."
    )]
    NoProjectOpen,
    /// The path is not in the registry of projects the application set up.
    #[error(
        "{0} is not a project this server can open. Set it up in the application first; \
         list_projects shows the ones it already knows."
    )]
    UnknownProject(String),
    /// The server was started with `--project` and the path names another one.
    #[error(
        "This server was started pinned to {0}. Restart it without --project to reach \
         other projects."
    )]
    PinnedElsewhere(String),
    /// The project is known but its database could not be opened.
    #[error(transparent)]
    Open(#[from] OpenError),
}

/// The permissions of the process and the project currently open.
pub struct ServerState {
    /// Lets `submit_translations` draft over a `human_validated` line (`--allow-overwrite-validated`).
    pub allow_overwrite_validated: bool,
    /// Lets `clear_translations` run (`--allow-clear`).
    pub allow_clear: bool,
    /// Lets the glossary and universe summary tools write (`--allow-edit-glossary`).
    pub allow_edit_glossary: bool,
    /// The only project this server may open (`--project`), if any.
    pub pinned: Option<PathBuf>,
    /// The project opened by `use_project`, if any.
    pub current: Option<ProjectSession>,
    /// The registry file listing the projects the server may open.
    pub registry: PathBuf,
    /// The machine-wide translation memory database.
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
            allow_edit_glossary: false,
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
    /// `recent_projects::resolve` of the same path in [`Self::use_project`],
    /// whatever a platform's canonical form happens to look like (the
    /// `\\?\` prefix Windows adds, a symlink elsewhere).
    pub fn known_projects(&self) -> Vec<PathBuf> {
        recent_projects::all(&self.registry)
            .into_iter()
            .map(|path| recent_projects::resolve(&path))
            .collect()
    }

    /// Return the open project.
    ///
    /// # Errors
    ///
    /// [`SessionError::NoProjectOpen`] when no project has been opened yet.
    pub fn require(&self) -> Result<&ProjectSession, SessionError> {
        self.current.as_ref().ok_or(SessionError::NoProjectOpen)
    }

    /// Open a project, closing the one held before it.
    ///
    /// # Errors
    ///
    /// [`SessionError::PinnedElsewhere`] when the server is pinned to another project,
    /// [`SessionError::UnknownProject`] when the registry does not list the path,
    /// [`SessionError::Open`] when the project has no database or it cannot be opened.
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
    ///
    /// # Errors
    ///
    /// [`SessionError::Open`] when the project has no database or it cannot be opened;
    /// the pin stays set in that case.
    pub fn pin(&mut self, project: &Path) -> Result<(), SessionError> {
        let resolved = recent_projects::resolve(project);
        self.pinned = Some(resolved.clone());
        self.use_project(&resolved).map(|_| ())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::core::storage::Database;

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
        assert!(matches!(
            result,
            Err(SessionError::Open(OpenError::NoDatabase(_)))
        ));
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
}
