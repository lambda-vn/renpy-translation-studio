//! Tauri commands bridging the Svelte frontend to `core::`. Each module
//! here mirrors one Python view's backend calls; the views themselves —
//! layout, dialogs, keyboard handling — live entirely in `../../../src`
//! (the SvelteKit frontend), nothing UI-specific belongs on this side.

pub mod characters;
pub mod dto;
pub mod export;
pub mod extract;
pub mod interchange;
pub mod project;
pub mod review;
pub mod settings;
pub mod translate;
pub mod universe;

use crate::core::storage::repositories;
use crate::mcp_server::session::ProjectSession;

pub(crate) fn require_session(guard: &Option<ProjectSession>) -> Result<&ProjectSession, String> {
    guard.as_ref().ok_or_else(|| "No project open.".to_string())
}

pub(crate) fn require_unit(
    session: &ProjectSession,
    block_id: &str,
) -> Result<repositories::TranslationUnit, String> {
    repositories::get_all(session.conn(), None, None)
        .map_err(|e| e.to_string())?
        .into_iter()
        .find(|u| u.block_id == block_id)
        .ok_or_else(|| format!("Unknown block_id: {block_id}"))
}
