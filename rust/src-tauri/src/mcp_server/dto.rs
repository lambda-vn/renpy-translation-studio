//! Wire shapes for the MCP tools: what a client sends and what it gets
//! back. Kept separate from `server.rs` so the tool bodies read as logic
//! rather than struct definitions.
//!
//! Field names match `mcp_server/server.py`'s dict payloads exactly,
//! since a client written against the Python server should read the
//! Rust one without changes.

use std::collections::HashMap;

use rmcp::schemars;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, schemars::JsonSchema)]
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

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ProjectEntry {
    pub name: String,
    pub path: String,
    pub ready: bool,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ListProjectsResult {
    pub projects: Vec<ProjectEntry>,
    pub open: Option<String>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct UseProjectArgs {
    /// The path as given by list_projects.
    pub project: String,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct UseProjectResult {
    pub open: String,
    pub source_language: String,
    pub target_language: String,
    pub by_status: HashMap<String, i64>,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct FileEntry {
    pub source_file: String,
    pub total: i64,
    pub validated: i64,
    pub ai_suggested: i64,
    pub draft: i64,
    pub imported: i64,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ListFilesResult {
    pub files: Vec<FileEntry>,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ProjectProgressResult {
    pub lines: i64,
    pub validated_lines: i64,
    pub words: i64,
    pub validated_words: i64,
    pub by_status: HashMap<String, i64>,
    pub source_language: String,
    pub target_language: String,
}

fn default_page_size() -> i64 {
    50
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct ListUnitsArgs {
    /// Path as returned by list_files.
    pub source_file: String,
    /// Keep only this status, e.g. 'not_translated'.
    #[serde(default)]
    pub status: Option<String>,
    /// Substring to look for in source or translation.
    #[serde(default)]
    pub search: String,
    /// Ren'Py character variable the lines belong to.
    #[serde(default)]
    pub speaker: Option<String>,
    /// Keep only the lines flagged for a second look.
    #[serde(default)]
    pub needs_review: bool,
    /// Zero-based page index.
    #[serde(default)]
    pub page: i64,
    /// Lines per page.
    #[serde(default = "default_page_size")]
    pub page_size: i64,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ListUnitsResult {
    pub units: Vec<UnitPayload>,
    pub total: i64,
    pub page: i64,
    pub page_size: i64,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct BlockIdArgs {
    /// Identifier of the line.
    pub block_id: String,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct SpeakerInfo {
    pub variable: String,
    pub display_name: String,
    pub notes: Option<String>,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct UnitContextResult {
    pub unit: UnitPayload,
    pub window: Vec<UnitPayload>,
    pub speaker: Option<SpeakerInfo>,
    pub universe_summary: Option<String>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct TranslationSubmission {
    pub block_id: String,
    pub translation: String,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct SubmitTranslationsArgs {
    /// Pairs of block_id and translation.
    pub items: Vec<TranslationSubmission>,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct SubmissionRejection {
    pub block_id: String,
    pub reason: String,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct SubmitTranslationsResult {
    pub applied: usize,
    pub rejected: Vec<SubmissionRejection>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct SetNoteArgs {
    pub block_id: String,
    /// What to say about it; an empty note clears both.
    pub note: String,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct SetNeedsReviewArgs {
    pub block_id: String,
    pub needs_review: bool,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct CharacterEntry {
    pub variable: String,
    pub display_name: String,
    pub notes: Option<String>,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct CharactersResult {
    pub characters: Vec<CharacterEntry>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct UpsertCharacterArgs {
    /// The Ren'Py variable the character is defined as.
    pub variable: String,
    /// The name shown to players.
    pub display_name: String,
    /// Free-form notes, or omitted to leave them as they are.
    #[serde(default)]
    pub notes: Option<String>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct DeleteCharacterArgs {
    pub variable: String,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct SummaryResult {
    pub summary: Option<String>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct SetSummaryArgs {
    /// The new description; an empty string clears it.
    pub summary: String,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct ClearTranslationsArgs {
    /// Limit to one file; the whole project otherwise.
    #[serde(default)]
    pub source_file: Option<String>,
    /// Limit to these statuses, e.g. ['ai_suggested'] to drop a bad run
    /// without touching reviewed work.
    #[serde(default)]
    pub statuses: Option<Vec<String>>,
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ClearTranslationsResult {
    pub cleared: usize,
}
