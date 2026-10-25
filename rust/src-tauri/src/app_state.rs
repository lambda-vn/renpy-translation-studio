//! Shared state behind every Tauri command: the project currently open,
//! persistent settings, and a running translation job's cancel token.
//!
//! `ProjectSession` is reused as-is from `mcp_server::session` — a
//! project connection, and `relative()`/`absolute()` path helpers, have
//! nothing MCP-specific about them. What the desktop app does not reuse
//! is `ServerState::use_project`'s registry gate: an MCP client is
//! reached from outside and can only open a project the application
//! already listed, but the human using this app picks a folder directly
//! through a native dialog, so `commands::project::open_project` calls
//! the free `mcp_server::session::open_project` function instead and
//! registers the result itself.

use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use tokio::sync::Mutex;

use crate::core::live::LiveServer;
use crate::core::settings::Settings;
use crate::core::translation::job::CancelToken;
use crate::mcp_server::session::ProjectSession;

#[derive(Clone)]
pub struct AppState {
    pub current: Arc<Mutex<Option<ProjectSession>>>,
    pub settings: Arc<Mutex<Settings>>,
    pub job: Arc<Mutex<Option<CancelToken>>>,
    /// Set while an extraction runs, so a second one is refused rather
    /// than racing the first over the same `tl/` folder.
    pub extracting: Arc<AtomicBool>,
    /// The endpoint other processes notify, while the review screen is up.
    pub live: Arc<Mutex<Option<LiveServer>>>,
    /// Whether no settings file existed at startup, until the onboarding
    /// is finished. Captured once: any early write to the settings (a
    /// language picked before the screen is done) would otherwise make the
    /// file exist and the screen vanish.
    pub first_launch: Arc<AtomicBool>,
}

impl Default for AppState {
    fn default() -> Self {
        let settings = Settings::load();
        let first_launch = settings.is_first_launch();
        Self {
            current: Arc::new(Mutex::new(None)),
            settings: Arc::new(Mutex::new(settings)),
            first_launch: Arc::new(AtomicBool::new(first_launch)),
            job: Arc::new(Mutex::new(None)),
            extracting: Arc::new(AtomicBool::new(false)),
            live: Arc::new(Mutex::new(None)),
        }
    }
}
