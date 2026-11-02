//! Setting a game up: inspecting a folder and extracting its texts. The work
//! itself lives in `core::extraction`, nothing here decides anything about
//! Ren'Py.
//!
//! Errors leave as a stable `code` plus the English message, so the
//! interface can show its own localized wording and fall back on the
//! message for a code it does not know.

use std::collections::HashMap;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};

use serde::Serialize;
use tauri::{AppHandle, Emitter, State};

use crate::app_state::AppState;
use crate::core::extraction::{
    self, ExtractMode, ExtractionError, ExtractionReport, ExtractionRequest, ExtractionStage,
};
use crate::core::languages::LANGUAGES;
use crate::core::project_session;
use crate::core::renpy::cli::CliError;
use crate::core::renpy::engine::{self, EngineError};
use crate::core::storage::{recent_projects, Database};
use crate::core::validators::validate_project_dir;

use super::dto::ProjectInfo;
use super::project::project_info;

/// Name of the event reporting the extraction's progress to the frontend.
const STAGE_EVENT: &str = "extraction-stage";

/// A language the setup form offers, from the central language list.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LanguageEntry {
    pub code: &'static str,
    pub label: &'static str,
}

/// What the setup form learns about a game folder.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GameInspection {
    /// The folder holds a `game/` directory.
    pub valid: bool,
    pub game_name: String,
    /// The game's own engine cannot run here, so a Ren'Py SDK is needed.
    pub needs_sdk: bool,
    /// The target language folder already holds `.rpy` files.
    pub has_existing_tl: bool,
    /// The folder already has a project database.
    pub has_database: bool,
    /// Language folders under `game/tl/` that hold `.rpy` files.
    pub existing_languages: Vec<String>,
}

/// A finished extraction: the project now open and what was extracted.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExtractionOutcome {
    pub project: ProjectInfo,
    pub report: ExtractionReport,
}

/// Why an extraction failed, for the interface to word in its own language.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExtractionFailure {
    /// Stable identifier of the failure.
    pub code: &'static str,
    /// The English message, fallback for a `code` the interface does not know.
    pub message: String,
    /// What the engine printed, when it failed.
    pub detail: Option<String>,
    /// Values the localized message interpolates.
    pub params: HashMap<&'static str, String>,
}

impl From<&ExtractionError> for ExtractionFailure {
    fn from(error: &ExtractionError) -> Self {
        let detail = match error {
            ExtractionError::Cli(cli) if !cli.output().is_empty() => Some(cli.output().to_string()),
            _ => None,
        };
        let mut params = HashMap::new();
        let mut inner = |text: String| {
            params.insert("error", text.clone());
            params.insert("message", text);
        };
        match error {
            ExtractionError::Engine(EngineError::WrongPlatform { platforms }) => {
                params.insert("platforms", platforms.clone());
            }
            ExtractionError::Cli(CliError::Failed { code, .. }) => {
                params.insert(
                    "code",
                    code.map_or_else(|| "?".to_string(), |c| c.to_string()),
                );
            }
            ExtractionError::Cli(CliError::Spawn(e)) => inner(e.to_string()),
            ExtractionError::Archive(e) | ExtractionError::Io(e) => inner(e.to_string()),
            ExtractionError::Unpack(e) => inner(e.to_string()),
            ExtractionError::Parse(e) => inner(e.to_string()),
            ExtractionError::Database(e) => inner(e.to_string()),
            _ => {}
        }
        Self {
            code: error.code(),
            message: error.to_string(),
            detail,
            params,
        }
    }
}

/// Clears the "an extraction is running" flag however the command ends.
struct Running<'a>(&'a AtomicBool);

impl Drop for Running<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

/// The languages the setup form can offer.
#[tauri::command]
pub fn list_languages() -> Vec<LanguageEntry> {
    LANGUAGES
        .iter()
        .map(|language| LanguageEntry {
            code: language.code,
            label: language.label,
        })
        .collect()
}

/// What the form needs to know about a folder before extracting it.
#[tauri::command]
pub async fn inspect_game(path: String, target_language: String) -> GameInspection {
    let project = recent_projects::resolve(Path::new(&path));
    let valid = validate_project_dir(&project);
    let tl_root = project.join("game").join("tl");
    let mut existing_languages: Vec<String> = std::fs::read_dir(&tl_root)
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .filter(|entry| entry.path().is_dir())
        .map(|entry| entry.file_name().to_string_lossy().into_owned())
        .filter(|language| extraction::has_existing_tl(&project, language))
        .collect();
    existing_languages.sort();
    GameInspection {
        valid,
        game_name: crate::core::exporter::resolve_game_name(&project),
        needs_sdk: valid && !engine::can_use_game_engine(&project),
        has_existing_tl: valid && extraction::has_existing_tl(&project, &target_language),
        has_database: Database::path_for(&project).is_file(),
        existing_languages,
    }
}

/// Extract a game's texts into its project database, then open it.
///
/// Any project currently open is closed first: it may be this very game,
/// and the extraction rewrites the database under it.
///
/// # Errors
///
/// Fails with an [`ExtractionFailure`]: code `busy` when another extraction
/// is running, `internal` when the worker task fails, `database` when the
/// extracted project cannot be opened, otherwise the code of the
/// [`ExtractionError`] (engine missing or unable to run, parse failure,
/// and so on).
#[tauri::command]
pub async fn extract_project(
    app: AppHandle,
    state: State<'_, AppState>,
    path: String,
    source_language: String,
    target_language: String,
    mode: ExtractMode,
) -> Result<ExtractionOutcome, ExtractionFailure> {
    if state
        .extracting
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return Err(ExtractionFailure {
            code: "busy",
            message: "An extraction is already running.".to_string(),
            detail: None,
            params: HashMap::new(),
        });
    }
    let _running = Running(&state.extracting);

    *state.current.lock().await = None;
    let project = recent_projects::resolve(Path::new(&path));
    let sdk = state
        .settings
        .lock()
        .await
        .get("sdk_path")
        .filter(|value| !value.is_empty())
        .map(std::path::PathBuf::from);

    let worker_project = project.clone();
    let result = tokio::task::spawn_blocking(move || {
        extraction::extract(
            &ExtractionRequest {
                project: &worker_project,
                source_language: &source_language,
                target_language: &target_language,
                mode,
                sdk_path: sdk.as_deref(),
            },
            &mut |stage: ExtractionStage| {
                let _ = app.emit(STAGE_EVENT, stage);
            },
        )
    })
    .await
    .map_err(|e| ExtractionFailure {
        code: "internal",
        message: e.to_string(),
        detail: None,
        params: HashMap::new(),
    })?;

    let report = result.map_err(|e| ExtractionFailure::from(&e))?;
    let opened = project_session::open_project(&project).map_err(|e| ExtractionFailure {
        code: "database",
        message: e.to_string(),
        detail: None,
        params: HashMap::new(),
    })?;
    recent_projects::add(&recent_projects::default_path(), &project);
    let info = project_info(&opened).map_err(|message| ExtractionFailure {
        code: "database",
        message,
        detail: None,
        params: HashMap::new(),
    })?;
    *state.current.lock().await = Some(opened);
    Ok(ExtractionOutcome {
        project: info,
        report,
    })
}
