//! The listener an open review screen has for its project. Port of
//! `_start_live` / `_stop_live` in `app/views/review_view.py`; the channel
//! itself is `core::live`.
//!
//! Only while the review screen is up: it is the one that shows lines, and
//! an endpoint outliving it would announce a project nobody is looking at.
//! Losing the channel costs a page reload and nothing else, so a failure to
//! open it is reported to nobody.

use std::sync::Arc;

use serde::Serialize;
use tauri::{AppHandle, Emitter, State};

use crate::app_state::AppState;
use crate::core::live::LiveServer;

const LIVE_EVENT: &str = "live-changed";

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct LiveChanged {
    /// The lines that changed, or `None` when too much did to name them
    /// and the screen should reload.
    block_ids: Option<Vec<String>>,
}

/// Publish this project's endpoint and start relaying what other
/// processes write to it as `live-changed` events.
#[tauri::command]
pub async fn start_live(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), super::CommandError> {
    let project = {
        let guard = state.current.lock().await;
        super::require_session(&guard)?.path.clone()
    };
    if let Some(previous) = state.live.lock().await.take() {
        previous.stop();
    }
    let started = LiveServer::start(
        &project,
        Arc::new(move |block_ids| {
            let _ = app.emit(LIVE_EVENT, LiveChanged { block_ids });
        }),
    )
    .await;
    *state.live.lock().await = started.ok();
    Ok(())
}

/// Withdraw the endpoint on the way out of the review screen.
#[tauri::command]
pub async fn stop_live(state: State<'_, AppState>) -> Result<(), String> {
    if let Some(server) = state.live.lock().await.take() {
        server.stop();
    }
    Ok(())
}
