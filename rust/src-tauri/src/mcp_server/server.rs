//! The tools a client gets, one per action the application offers. Port
//! of `mcp_server/server.py`.
//!
//! Everything a translation goes through in the review screen it goes
//! through here: a submission is quality-checked and refused on the same
//! grounds, and it lands in `ai_suggested` because a machine wrote it.
//! The screen stays where a human validates.
//!
//! Every write below tells a running application which lines it touched
//! (`core::live`), a bonus the server never waits on and never needs.

use std::path::Path;

use crate::core::live;
use std::sync::Arc;

use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::handler::server::wrapper::{Json, Parameters};
use rmcp::model::{Implementation, ServerCapabilities, ServerInfo};
use rmcp::{tool, tool_handler, tool_router, ServerHandler};
use tokio::sync::Mutex;

use crate::core::storage::{repositories, Database};
use crate::core::translation::quality;

use super::dto::*;
use super::session::{ProjectSession, ServerState};

const CONTEXT_RADIUS: i64 = 2;
const UNIVERSE_SUMMARY_KEY: &str = "universe_summary";

const INSTRUCTIONS: &str = "\
Translate a Ren'Py visual novel through the studio holding the project.

Start with list_projects and use_project, unless one is already open.
Then read a file's untranslated lines with list_units, ask
get_unit_context for what surrounds a line you are unsure of, and send
batches back with submit_translations.

Copy every {tag} and every [interpolation] of the source verbatim: a
submission that drops one, or that invents one the source did not have,
is refused. Never write an interpolation of your own, the engine runs
what is between square brackets as Python.

Translations land as suggestions. A human reviews them in the
application, and lines they already validated are left alone.";

const KNOWN_STATUSES: [&str; 5] = [
    "not_translated",
    "draft",
    "imported",
    "ai_suggested",
    "human_validated",
];

#[derive(Clone)]
pub struct RtsServer {
    state: Arc<Mutex<ServerState>>,
    tool_router: ToolRouter<Self>,
}

fn unit_payload(session: &ProjectSession, unit: &repositories::TranslationUnit) -> UnitPayload {
    UnitPayload {
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

fn characters_payload(session: &ProjectSession) -> Result<Vec<CharacterEntry>, String> {
    let characters = repositories::get_all_characters(session.conn()).map_err(|e| e.to_string())?;
    Ok(characters
        .into_iter()
        .map(|c| CharacterEntry {
            variable: c.variable,
            display_name: c.display_name,
            notes: c.notes,
        })
        .collect())
}

fn require_unit(
    session: &ProjectSession,
    block_id: &str,
) -> Result<repositories::TranslationUnit, String> {
    let units = repositories::get_all(session.conn(), None, None).map_err(|e| e.to_string())?;
    units
        .into_iter()
        .find(|u| u.block_id == block_id)
        .ok_or_else(|| format!("Unknown block_id: {block_id}"))
}

fn refetch_unit(session: &ProjectSession, block_id: &str) -> Result<UnitPayload, String> {
    let unit = require_unit(session, block_id)?;
    Ok(unit_payload(session, &unit))
}

fn validate_statuses(statuses: &Option<Vec<String>>) -> Result<(), String> {
    let Some(statuses) = statuses else {
        return Ok(());
    };
    let mut unknown: Vec<&str> = statuses
        .iter()
        .map(String::as_str)
        .filter(|s| !KNOWN_STATUSES.contains(s))
        .collect();
    unknown.sort_unstable();
    unknown.dedup();
    if unknown.is_empty() {
        Ok(())
    } else {
        Err(format!("Unknown status: {}", unknown.join(", ")))
    }
}

#[tool_router]
impl RtsServer {
    pub fn new(state: ServerState) -> Self {
        Self {
            state: Arc::new(Mutex::new(state)),
            tool_router: Self::tool_router(),
        }
    }

    #[tool(description = "List the games set up in the application on this machine.")]
    async fn list_projects(&self) -> Result<Json<ListProjectsResult>, String> {
        let state = self.state.lock().await;
        let projects = state
            .known_projects()
            .into_iter()
            .map(|path| {
                let ready = Database::path_for(&path).is_file();
                let name = path
                    .file_name()
                    .map(|n| n.to_string_lossy().into_owned())
                    .unwrap_or_default();
                ProjectEntry {
                    name,
                    path: path.display().to_string(),
                    ready,
                }
            })
            .collect();
        let open = state.current.as_ref().map(|s| s.path.display().to_string());
        Ok(Json(ListProjectsResult { projects, open }))
    }

    #[tool(description = "Open one of the games the application knows, by path.")]
    async fn use_project(
        &self,
        Parameters(args): Parameters<UseProjectArgs>,
    ) -> Result<Json<UseProjectResult>, String> {
        let mut state = self.state.lock().await;
        let session = state
            .use_project(Path::new(&args.project))
            .map_err(|e| e.to_string())?;
        let by_status = repositories::count_by_status(session.conn()).map_err(|e| e.to_string())?;
        Ok(Json(UseProjectResult {
            open: session.path.display().to_string(),
            source_language: session.source_language(),
            target_language: session.target_language(),
            by_status,
        }))
    }

    #[tool(description = "List the game's translatable files with their progress.")]
    async fn list_files(&self) -> Result<Json<ListFilesResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        let files = repositories::get_files(session.conn())
            .map_err(|e| e.to_string())?
            .into_iter()
            .map(|f| FileEntry {
                source_file: session.relative(&f.source_file),
                total: f.total,
                validated: f.validated,
                ai_suggested: f.ai_suggested,
                draft: f.draft,
                imported: f.imported,
            })
            .collect();
        Ok(Json(ListFilesResult { files }))
    }

    #[tool(description = "Report how much of the whole project is translated.")]
    async fn project_progress(&self) -> Result<Json<ProjectProgressResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        let progress = repositories::project_progress(session.conn()).map_err(|e| e.to_string())?;
        let by_status = repositories::count_by_status(session.conn()).map_err(|e| e.to_string())?;
        Ok(Json(ProjectProgressResult {
            lines: progress.lines,
            validated_lines: progress.validated_lines,
            words: progress.words,
            validated_words: progress.validated_words,
            by_status,
            source_language: session.source_language(),
            target_language: session.target_language(),
        }))
    }

    #[tool(description = "List one page of a file's lines, filtered like the review screen.")]
    async fn list_units(
        &self,
        Parameters(args): Parameters<ListUnitsArgs>,
    ) -> Result<Json<ListUnitsResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        let source_file = session.absolute(&args.source_file);
        let (units, total) = repositories::get_page(
            session.conn(),
            &source_file,
            args.page,
            args.page_size,
            args.status.as_deref(),
            &args.search,
            args.speaker.as_deref(),
            args.needs_review,
        )
        .map_err(|e| e.to_string())?;
        Ok(Json(ListUnitsResult {
            units: units.iter().map(|u| unit_payload(session, u)).collect(),
            total,
            page: args.page,
            page_size: args.page_size,
        }))
    }

    #[tool(description = "Show the lines surrounding one line, in file order.")]
    async fn get_unit_context(
        &self,
        Parameters(args): Parameters<BlockIdArgs>,
    ) -> Result<Json<UnitContextResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        let unit = require_unit(session, &args.block_id)?;
        let window = repositories::get_neighbours(
            session.conn(),
            &unit.source_file,
            unit.source_line,
            CONTEXT_RADIUS,
        )
        .map_err(|e| e.to_string())?;
        let speaker = match &unit.character_variable {
            Some(variable) => repositories::get_all_characters(session.conn())
                .map_err(|e| e.to_string())?
                .into_iter()
                .find(|c| &c.variable == variable)
                .map(|c| SpeakerInfo {
                    variable: c.variable,
                    display_name: c.display_name,
                    notes: c.notes,
                }),
            None => None,
        };
        let universe_summary = repositories::get_project_meta(session.conn(), UNIVERSE_SUMMARY_KEY)
            .map_err(|e| e.to_string())?;
        Ok(Json(UnitContextResult {
            unit: unit_payload(session, &unit),
            window: window.iter().map(|u| unit_payload(session, u)).collect(),
            speaker,
            universe_summary,
        }))
    }

    #[tool(description = "Send translations back, one batch at a time.")]
    async fn submit_translations(
        &self,
        Parameters(args): Parameters<SubmitTranslationsArgs>,
    ) -> Result<Json<SubmitTranslationsResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        let known = repositories::get_all(session.conn(), None, None).map_err(|e| e.to_string())?;

        let mut accepted: Vec<(String, String, String)> = Vec::new();
        let mut drafted: Vec<String> = Vec::new();
        let mut rejected = Vec::new();
        for item in args.items {
            let Some(unit) = known.iter().find(|u| u.block_id == item.block_id) else {
                rejected.push(SubmissionRejection {
                    block_id: item.block_id,
                    reason: "Unknown block_id.".to_string(),
                });
                continue;
            };
            if item.translation.trim().is_empty() {
                rejected.push(SubmissionRejection {
                    block_id: item.block_id,
                    reason: "Empty translation.".to_string(),
                });
                continue;
            }
            let issues: Vec<String> = quality::check(&unit.source_text, &item.translation)
                .into_iter()
                .filter(|issue| issue.kind != quality::LENGTH_WARNING_KIND)
                .map(|issue| issue.detail)
                .collect();
            if !issues.is_empty() {
                rejected.push(SubmissionRejection {
                    block_id: item.block_id,
                    reason: issues.join(" "),
                });
                continue;
            }
            if unit.status == repositories::STATUS_HUMAN_VALIDATED {
                if !state.allow_overwrite_validated {
                    rejected.push(SubmissionRejection {
                        block_id: item.block_id,
                        reason: "Validated by a human. The server was not started with \
                                 --allow-overwrite-validated."
                            .to_string(),
                    });
                    continue;
                }
                repositories::mark_as_draft(session.conn(), &item.block_id, &item.translation)
                    .map_err(|e| e.to_string())?;
                drafted.push(item.block_id);
                continue;
            }
            accepted.push((item.block_id, item.translation, "ai_suggested".to_string()));
        }

        let applied = repositories::update_translations(session.conn(), &accepted)
            .map_err(|e| e.to_string())?;
        // A line drafted over a validated one changed as much as the others;
        // the Python server forgot to say so.
        let changed: Vec<String> = accepted
            .into_iter()
            .map(|(block_id, _, _)| block_id)
            .chain(drafted)
            .collect();
        let project = session.path.clone();
        live::notify(&project, &changed).await;
        Ok(Json(SubmitTranslationsResult { applied, rejected }))
    }

    #[tool(description = "Leave a note on a line and flag it for a second look.")]
    async fn set_note(
        &self,
        Parameters(args): Parameters<SetNoteArgs>,
    ) -> Result<Json<UnitPayload>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        require_unit(session, &args.block_id)?;
        repositories::set_note(session.conn(), &args.block_id, &args.note)
            .map_err(|e| e.to_string())?;
        repositories::set_needs_review(
            session.conn(),
            &args.block_id,
            !args.note.trim().is_empty(),
        )
        .map_err(|e| e.to_string())?;
        let unit = refetch_unit(session, &args.block_id)?;
        let project = session.path.clone();
        live::notify(&project, std::slice::from_ref(&args.block_id)).await;
        Ok(Json(unit))
    }

    #[tool(description = "Flag a line for a second look, or clear the flag.")]
    async fn set_needs_review(
        &self,
        Parameters(args): Parameters<SetNeedsReviewArgs>,
    ) -> Result<Json<UnitPayload>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        require_unit(session, &args.block_id)?;
        repositories::set_needs_review(session.conn(), &args.block_id, args.needs_review)
            .map_err(|e| e.to_string())?;
        let unit = refetch_unit(session, &args.block_id)?;
        let project = session.path.clone();
        live::notify(&project, std::slice::from_ref(&args.block_id)).await;
        Ok(Json(unit))
    }

    #[tool(
        description = "Fill untranslated lines the shared memory already answers for. Taken \
                        from the translations validated by hand in other projects, matched on \
                        the source text or on one differing only in case, spacing or trailing \
                        punctuation. Nothing already translated is touched."
    )]
    async fn fill_from_memory(&self) -> Result<Json<FillFromMemoryResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        let filled = crate::core::project_actions::fill_from_memory(
            session.conn(),
            &state.memory_path,
            &session.source_language(),
            &session.target_language(),
        )
        .map_err(|e| e.to_string())?;
        if filled > 0 {
            let project = session.path.clone();
            live::notify_reload(&project).await;
        }
        Ok(Json(FillFromMemoryResult { filled }))
    }

    #[tool(
        description = "Scan the game's sources for Character() definitions and store them.                         Returns how many the scan found, and the glossary as it now stands."
    )]
    async fn detect_characters(&self) -> Result<Json<DetectCharactersResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        let found = crate::core::project_actions::detect_and_store_characters(
            session.conn(),
            &session.path,
        )
        .map_err(|e| e.to_string())?;
        Ok(Json(DetectCharactersResult {
            found,
            characters: characters_payload(session)?,
        }))
    }

    #[tool(description = "List the character glossary.")]
    async fn list_characters(&self) -> Result<Json<CharactersResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        Ok(Json(CharactersResult {
            characters: characters_payload(session)?,
        }))
    }

    #[tool(description = "Add a character or rename one, and optionally set its notes.")]
    async fn upsert_character(
        &self,
        Parameters(args): Parameters<UpsertCharacterArgs>,
    ) -> Result<Json<CharactersResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        repositories::upsert_character(session.conn(), &args.variable, &args.display_name)
            .map_err(|e| e.to_string())?;
        if let Some(notes) = &args.notes {
            repositories::update_character_notes(session.conn(), &args.variable, notes)
                .map_err(|e| e.to_string())?;
        }
        Ok(Json(CharactersResult {
            characters: characters_payload(session)?,
        }))
    }

    #[tool(description = "Remove a character from the glossary.")]
    async fn delete_character(
        &self,
        Parameters(args): Parameters<DeleteCharacterArgs>,
    ) -> Result<Json<CharactersResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        repositories::delete_character(session.conn(), &args.variable)
            .map_err(|e| e.to_string())?;
        Ok(Json(CharactersResult {
            characters: characters_payload(session)?,
        }))
    }

    #[tool(description = "Read the free-form description of the game's setting.")]
    async fn get_universe_summary(&self) -> Result<Json<SummaryResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        let summary = repositories::get_project_meta(session.conn(), UNIVERSE_SUMMARY_KEY)
            .map_err(|e| e.to_string())?;
        Ok(Json(SummaryResult { summary }))
    }

    #[tool(description = "Replace the description of the game's setting.")]
    async fn set_universe_summary(
        &self,
        Parameters(args): Parameters<SetSummaryArgs>,
    ) -> Result<Json<SummaryResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        repositories::set_project_meta(session.conn(), UNIVERSE_SUMMARY_KEY, &args.summary)
            .map_err(|e| e.to_string())?;
        let summary = repositories::get_project_meta(session.conn(), UNIVERSE_SUMMARY_KEY)
            .map_err(|e| e.to_string())?;
        Ok(Json(SummaryResult { summary }))
    }

    #[tool(
        description = "Delete translations in bulk, back to not_translated. Refused unless \
                        the server was started with --allow-clear."
    )]
    async fn clear_translations(
        &self,
        Parameters(args): Parameters<ClearTranslationsArgs>,
    ) -> Result<Json<ClearTranslationsResult>, String> {
        let state = self.state.lock().await;
        let session = state.require().map_err(|e| e.to_string())?;
        if !state.allow_clear {
            return Err("Refused: the server was not started with --allow-clear.".to_string());
        }
        validate_statuses(&args.statuses)?;
        let source_file = args.source_file.as_deref().map(|f| session.absolute(f));
        let cleared = repositories::clear_translations(
            session.conn(),
            source_file.as_deref(),
            args.statuses.as_deref(),
        )
        .map_err(|e| e.to_string())?;
        if cleared > 0 {
            let project = session.path.clone();
            live::notify_reload(&project).await;
        }
        Ok(Json(ClearTranslationsResult { cleared }))
    }
}

#[tool_handler]
impl ServerHandler for RtsServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo::new(ServerCapabilities::builder().enable_tools().build())
            .with_server_info(Implementation::new(
                "renpy-translation-studio",
                env!("CARGO_PKG_VERSION"),
            ))
            .with_instructions(INSTRUCTIONS)
    }
}
