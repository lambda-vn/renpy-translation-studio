//! Wire shapes for the Tauri commands the Svelte frontend calls.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::core::storage::repositories;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UnitPayload {
    pub block_id: String,
    pub source_file: String,
    pub source_line: i64,
    pub speaker: Option<String>,
    pub source_text: String,
    pub translated_text: String,
    pub status: String,
    pub needs_review: bool,
    pub note: Option<String>,
}

impl UnitPayload {
    pub fn from_unit(
        session: &crate::mcp_server::session::ProjectSession,
        unit: &repositories::TranslationUnit,
    ) -> Self {
        Self {
            block_id: unit.block_id.clone(),
            source_file: session.relative(&unit.source_file),
            source_line: unit.source_line,
            speaker: unit.character_variable.clone(),
            source_text: unit.source_text.clone(),
            translated_text: unit.translated_text.clone(),
            status: unit.status.clone(),
            needs_review: unit.needs_review,
            note: unit.note.clone(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectEntry {
    pub name: String,
    pub path: String,
    pub ready: bool,
    /// What the recent-projects card shows; `None` when the project cannot
    /// be resumed (no units yet, no recorded target language, `tl/` gone).
    pub resume: Option<ProjectResume>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectResume {
    pub source_language: String,
    pub target_language: String,
    pub total: i64,
    pub validated: i64,
    pub ai_suggested: i64,
    pub imported: i64,
}

impl From<crate::core::project_actions::ResumeInfo> for ProjectResume {
    fn from(info: crate::core::project_actions::ResumeInfo) -> Self {
        Self {
            source_language: info.source_language,
            target_language: info.target_language,
            total: info.total,
            validated: info.validated,
            ai_suggested: info.ai_suggested,
            imported: info.imported,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectInfo {
    pub path: String,
    pub game_name: String,
    pub source_language: String,
    pub target_language: String,
    pub by_status: HashMap<String, i64>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FileEntry {
    pub source_file: String,
    /// Absolute path on disk, for "copy path" and for the file manager.
    pub path: String,
    pub total: i64,
    pub validated: i64,
    pub ai_suggested: i64,
    pub draft: i64,
    pub imported: i64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ListUnitsResult {
    pub units: Vec<UnitPayload>,
    /// For the lines of this page whose source text occurs elsewhere too,
    /// keyed by `blockId`.
    pub duplicates: HashMap<String, DuplicatePayload>,
    pub total: i64,
    pub page: i64,
    pub page_size: i64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DuplicatePayload {
    /// Every occurrence of the text, the displayed line included.
    pub total: i64,
    /// Those outside the file being displayed.
    pub other_files: i64,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ListUnitsArgs {
    pub source_file: String,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub search: String,
    #[serde(default)]
    pub speaker: Option<String>,
    #[serde(default)]
    pub needs_review: bool,
    /// The "In error" filter: translated lines a blocking quality check
    /// refuses, whatever their status.
    #[serde(default)]
    pub errors_only: bool,
    #[serde(default)]
    pub page: i64,
    #[serde(default = "default_page_size")]
    pub page_size: i64,
}

fn default_page_size() -> i64 {
    50
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct QualityIssuePayload {
    pub kind: &'static str,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ValidateResult {
    pub unit: Option<UnitPayload>,
    pub blocking_issues: Vec<QualityIssuePayload>,
    pub warnings: Vec<QualityIssuePayload>,
    /// Other lines sharing the source text and not yet validated, which
    /// `spread_to_duplicates` would reach. Zero when refused.
    pub duplicates: usize,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PropagateResult {
    pub unit: Option<UnitPayload>,
    pub blocking_issues: Vec<QualityIssuePayload>,
    pub warnings: Vec<QualityIssuePayload>,
    /// The other lines that received the translation; empty when the
    /// validation was refused or no open duplicate existed.
    pub propagated: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ClearArgs {
    /// Relative path of one file; `None` clears the whole project.
    #[serde(default)]
    pub source_file: Option<String>,
    /// `unvalidated` (suggestions, drafts, imports), `ai_suggested`, or
    /// `all` / absent for every translated line, validated ones included.
    #[serde(default)]
    pub scope: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SpeakerEntry {
    pub variable: String,
    /// The glossary's display name, the variable when there is none.
    pub label: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProgressPayload {
    pub lines: i64,
    pub validated_lines: i64,
    pub words: i64,
    pub validated_words: i64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FailingFile {
    pub source_file: String,
    pub count: i64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SyncPayload {
    pub never_saved: bool,
    pub unsaved_units: i64,
    pub externally_modified: bool,
    pub in_sync: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportInfo {
    /// The name the zip's top folder carries, proposed and editable.
    pub game_name: String,
    pub zip_file_name: String,
    /// Units extracted; zero means nothing to export yet.
    pub total: i64,
    /// Lines the archive would ship in the source language.
    pub untranslated: i64,
    /// Lines a blocking quality check refuses, per file, worst first.
    pub failing: Vec<FailingFile>,
    /// `None` when the `tl/` folder cannot be compared.
    pub sync: Option<SyncPayload>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryPair {
    pub source_language: String,
    pub target_language: String,
    pub entries: i64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CharacterEntry {
    pub variable: String,
    pub display_name: String,
    pub notes: Option<String>,
}

impl From<repositories::Character> for CharacterEntry {
    fn from(c: repositories::Character) -> Self {
        Self {
            variable: c.variable,
            display_name: c.display_name,
            notes: c.notes,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SettingsPayload {
    pub locale: Option<String>,
    pub theme: Option<String>,
    pub default_provider: Option<String>,
    pub deepl_api_key_set: bool,
    pub ollama_endpoint: Option<String>,
    pub ollama_model: Option<String>,
    pub ollama_batch_size: Option<String>,
    pub libretranslate_url: Option<String>,
    pub libretranslate_api_key_set: bool,
    pub verbose_logging: bool,
    pub sdk_path: Option<String>,
    pub available_providers: Vec<&'static str>,
    pub available_llm_providers: Vec<&'static str>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TestConnectionResult {
    pub ok: bool,
    /// DeepL only: characters left this month, when the account has a limit.
    pub characters_left: Option<i64>,
    pub models: Vec<String>,
}
