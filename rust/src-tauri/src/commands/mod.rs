//! Tauri commands bridging the Svelte frontend to `core::`. Each module
//! groups the backend calls of one screen; the views themselves —
//! layout, dialogs, keyboard handling — live entirely in `../../../src`
//! (the SvelteKit frontend), nothing UI-specific belongs on this side.

pub mod characters;
pub mod dto;
pub mod export;
pub mod extract;
pub mod interchange;
pub mod live;
pub mod project;
pub mod review;
pub mod settings;
pub mod translate;
pub mod universe;

use serde::Serialize;

use crate::core::project_session::ProjectSession;
use crate::core::storage::repositories;
use crate::core::translation::providers::base::ProviderError;

/// The failure of a command: plain text (technical details, left in
/// English), or a message the interface translates (`{ key, params }`),
/// from a provider or from the command itself.
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum CommandError {
    /// A technical message shown as is.
    Text(String),
    /// A failure reported by a translation provider.
    Provider(ProviderError),
    /// A catalog message the interface translates, with its placeholders.
    Message {
        /// Key in the interface's message catalog.
        key: &'static str,
        /// Values substituted into the message's placeholders.
        params: serde_json::Value,
    },
}

impl CommandError {
    /// A catalog message without placeholders.
    pub fn message(key: &'static str) -> Self {
        Self::Message {
            key,
            params: serde_json::json!({}),
        }
    }
}

impl From<String> for CommandError {
    fn from(text: String) -> Self {
        Self::Text(text)
    }
}

impl From<ProviderError> for CommandError {
    fn from(error: ProviderError) -> Self {
        Self::Provider(error)
    }
}

/// The open session.
///
/// # Errors
///
/// Fails with `errors.no_project_open` when no project is open.
pub(crate) fn require_session(
    guard: &Option<ProjectSession>,
) -> Result<&ProjectSession, CommandError> {
    guard
        .as_ref()
        .ok_or_else(|| CommandError::message("errors.no_project_open"))
}

/// The unit stored under `block_id`.
///
/// # Errors
///
/// Fails when the database cannot be read or when no unit has this
/// `block_id`.
pub(crate) fn require_unit(
    session: &ProjectSession,
    block_id: &str,
) -> Result<repositories::TranslationUnit, String> {
    repositories::get_many(session.conn(), &[block_id.to_string()])
        .map_err(|e| e.to_string())?
        .into_iter()
        .next()
        .ok_or_else(|| format!("Unknown block_id: {block_id}"))
}

/// The open session, provided it is still the project at `project`: for a
/// command that let go of the lock during slow file work and must not write
/// what it found into a project opened in the meantime.
///
/// # Errors
///
/// Fails with `errors.no_project_open` when no project is open, and with
/// `errors.project_changed` when the open project is not the one at `project`.
pub(crate) fn require_session_at<'a>(
    guard: &'a Option<ProjectSession>,
    project: &std::path::Path,
) -> Result<&'a ProjectSession, CommandError> {
    let session = require_session(guard)?;
    if session.path != project {
        return Err(CommandError::message("errors.project_changed"));
    }
    Ok(session)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_message_serializes_as_key_and_params() {
        let value = serde_json::to_value(CommandError::message("errors.no_project_open")).unwrap();
        assert_eq!(
            value,
            serde_json::json!({ "key": "errors.no_project_open", "params": {} })
        );
        let text = serde_json::to_value(CommandError::from("disk full".to_string())).unwrap();
        assert_eq!(text, serde_json::json!("disk full"));
    }

    #[test]
    fn a_session_is_only_returned_for_the_project_it_holds() {
        use crate::core::storage::Database;

        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let project = std::env::temp_dir().join(format!("rts-session-at-{nanos}"));
        let db_path = Database::path_for(&project);
        std::fs::create_dir_all(db_path.parent().unwrap()).unwrap();
        Database::open(&db_path).unwrap();
        let guard = Some(crate::core::project_session::open_project(&project).unwrap());

        assert!(require_session_at(&guard, &guard.as_ref().unwrap().path).is_ok());
        let other = serde_json::to_value(
            require_session_at(&guard, &project.join("elsewhere"))
                .err()
                .unwrap(),
        )
        .unwrap();
        assert_eq!(other["key"], "errors.project_changed");
        let none =
            serde_json::to_value(require_session_at(&None, &project).err().unwrap()).unwrap();
        assert_eq!(none["key"], "errors.no_project_open");
    }
}
