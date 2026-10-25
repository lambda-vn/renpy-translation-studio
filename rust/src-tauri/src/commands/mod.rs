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

/// The failure of a command that can reach a provider: plain text, or a
/// [`ProviderError`] the interface translates (`{ key, params }`).
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum CommandError {
    Text(String),
    Provider(ProviderError),
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

pub(crate) fn require_session(guard: &Option<ProjectSession>) -> Result<&ProjectSession, String> {
    guard.as_ref().ok_or_else(|| "No project open.".to_string())
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
