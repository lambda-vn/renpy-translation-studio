//! Tauri commands bridging the Svelte frontend to `core::`. Each module
//! here mirrors one Python view's backend calls; the views themselves —
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

use crate::core::storage::repositories;
use crate::core::translation::providers::base::ProviderError;
use crate::mcp_server::session::ProjectSession;

/// The failure of a command: plain text (technical details, left in
/// English), or a message the interface translates (`{ key, params }`),
/// from a provider or from the command itself.
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum CommandError {
    Text(String),
    Provider(ProviderError),
    Message {
        key: &'static str,
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

pub(crate) fn require_session(
    guard: &Option<ProjectSession>,
) -> Result<&ProjectSession, CommandError> {
    guard
        .as_ref()
        .ok_or_else(|| CommandError::message("errors.no_project_open"))
}

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
}
