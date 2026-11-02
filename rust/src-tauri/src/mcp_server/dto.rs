//! Wire shapes for the MCP tools: what a client sends and what it gets
//! back. Kept separate from `server.rs` so the tool bodies read as logic
//! rather than struct definitions.
//!
//! A `usize` count is published as `i64` (`#[schemars(with = "i64")]`):
//! schemars gives `usize` the format `uint`, which clients validating with
//! Ajv do not know and warn about, where `int64` is a standard one.

use std::collections::HashMap;

use rmcp::schemars;
use serde::{Deserialize, Serialize};

/// One translation line as a client sees it.
#[derive(Debug, Clone, Serialize, schemars::JsonSchema)]
pub struct UnitPayload {
    pub block_id: String,
    /// Relative to the project root.
    pub source_file: String,
    pub source_line: i64,
    /// Ren'Py character variable speaking the line.
    pub speaker: Option<String>,
    pub source_text: String,
    pub translated_text: String,
    /// One of the stored status names, e.g. `not_translated`.
    pub status: String,
    pub needs_review: bool,
    pub note: Option<String>,
}

/// A game the application has set up.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ProjectEntry {
    pub name: String,
    pub path: String,
    /// Whether the game has been extracted, i.e. has a database.
    pub ready: bool,
}

/// Result of `list_projects`.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ListProjectsResult {
    pub projects: Vec<ProjectEntry>,
    /// Path of the project currently open, if any.
    pub open: Option<String>,
}

/// Arguments of `use_project`.
#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct UseProjectArgs {
    /// The path as given by list_projects.
    pub project: String,
}

/// Result of `use_project`: the project now open and its line counts.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct UseProjectResult {
    pub open: String,
    pub source_language: String,
    pub target_language: String,
    /// Number of lines per status.
    pub by_status: HashMap<String, i64>,
}

/// A file with its line counts per status.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct FileEntry {
    pub source_file: String,
    pub total: i64,
    /// Lines in `human_validated`.
    pub validated: i64,
    pub ai_suggested: i64,
    pub draft: i64,
    pub imported: i64,
}

/// Result of `list_files`.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ListFilesResult {
    pub files: Vec<FileEntry>,
}

/// Result of `project_progress`: how much of the project is translated.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ProjectProgressResult {
    pub lines: i64,
    pub validated_lines: i64,
    /// Words in the source text, as an estimate.
    pub words: i64,
    pub validated_words: i64,
    /// Number of lines per status.
    pub by_status: HashMap<String, i64>,
    pub source_language: String,
    pub target_language: String,
}

fn default_page_size() -> i64 {
    50
}

/// Arguments of `list_units`.
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

/// Result of `list_units`: one page of lines.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ListUnitsResult {
    pub units: Vec<UnitPayload>,
    /// Lines matching the filters across all pages.
    pub total: i64,
    /// Page index actually served.
    pub page: i64,
    /// Page size actually applied, after clamping.
    pub page_size: i64,
}

/// Arguments of the tools that take a single line.
#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct BlockIdArgs {
    /// Identifier of the line.
    pub block_id: String,
}

/// A glossary entry for the character speaking a line.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct SpeakerInfo {
    pub variable: String,
    pub display_name: String,
    pub notes: Option<String>,
}

/// Result of `get_unit_context`.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct UnitContextResult {
    pub unit: UnitPayload,
    /// The line and its neighbours, in file order.
    pub window: Vec<UnitPayload>,
    pub speaker: Option<SpeakerInfo>,
    pub universe_summary: Option<String>,
}

/// One translation sent by a client.
#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct TranslationSubmission {
    pub block_id: String,
    pub translation: String,
}

/// Arguments of `submit_translations`.
#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct SubmitTranslationsArgs {
    /// Pairs of block_id and translation.
    pub items: Vec<TranslationSubmission>,
}

/// A submitted line that was refused, with the reason.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct SubmissionRejection {
    pub block_id: String,
    pub reason: String,
}

/// Result of `submit_translations`.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct SubmitTranslationsResult {
    #[schemars(with = "i64")]
    /// Lines written to the database.
    pub applied: usize,
    pub rejected: Vec<SubmissionRejection>,
}

/// Arguments of `set_note`.
#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct SetNoteArgs {
    pub block_id: String,
    /// What to say about it; an empty note clears both.
    pub note: String,
}

/// Arguments of `set_needs_review`.
#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct SetNeedsReviewArgs {
    pub block_id: String,
    pub needs_review: bool,
}

/// A glossary entry.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct CharacterEntry {
    pub variable: String,
    pub display_name: String,
    pub notes: Option<String>,
}

/// The glossary as it stands, returned by the character tools.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct CharactersResult {
    pub characters: Vec<CharacterEntry>,
}

/// Result of `detect_characters`.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct DetectCharactersResult {
    /// How many definitions the scan found.
    #[schemars(with = "i64")]
    pub found: usize,
    pub characters: Vec<CharacterEntry>,
}

/// Arguments of `upsert_character`.
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

/// Arguments of `delete_character`.
#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct DeleteCharacterArgs {
    pub variable: String,
}

/// The universe summary, `None` when unset.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct SummaryResult {
    pub summary: Option<String>,
}

/// Arguments of `set_universe_summary`.
#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct SetSummaryArgs {
    /// The new description; an empty string clears it.
    pub summary: String,
}

/// Arguments of `clear_translations`.
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

/// Result of `fill_from_memory`.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct FillFromMemoryResult {
    #[schemars(with = "i64")]
    /// Lines filled from the memory.
    pub filled: usize,
}

/// Result of `clear_translations`.
#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct ClearTranslationsResult {
    #[schemars(with = "i64")]
    /// Lines reset to `not_translated`.
    pub cleared: usize,
}
