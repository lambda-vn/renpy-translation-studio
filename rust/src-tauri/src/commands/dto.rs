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
    pub total: i64,
    pub page: i64,
    pub page_size: i64,
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
    pub detail: Option<String>,
    pub models: Vec<String>,
}
