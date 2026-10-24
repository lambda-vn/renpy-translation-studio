//! The extraction pipeline: run Ren'Py, read back what it generated, and
//! bring the project database in line with it. Port of the logic that
//! lived in `app/views/project_setup.py` (`_run_extraction`, `_init_db`
//! and their helpers), moved out of the view so that nothing but a click
//! is left in the interface.
//!
//! Ren'Py only ever appends to an existing `tl/<language>/` folder, never
//! prunes it, so rebuilding is the only way to learn what the game dropped
//! between two versions. `update` and `reset` therefore both archive the
//! folder already on disk and let Ren'Py rebuild it; `update` reads the
//! old folder first so the translations it held can still be adopted,
//! `reset` throws them away on purpose. `keep` reuses the files on disk
//! untouched. Nothing is lost either way: the database keeps every
//! translation and saving mirrors all of them back into the files.

use std::collections::HashSet;
use std::path::{Path, PathBuf};

use rusqlite::Connection;
use serde::{Deserialize, Serialize};

use super::renpy::archive::ArchiveError;
use super::renpy::cli::{self, CliError};
use super::renpy::engine::{self, EngineError};
use super::renpy::parser::{self, is_translated, ParseError, TranslationBlock};
use super::renpy::unpacker;
use super::storage::repositories::{self as repo, NewUnit};
use super::storage::Database;
use super::translation::job::needs_translation;
use super::validators::{validate_language_code, validate_project_dir};

/// How the `tl/` folder already on disk is treated.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExtractMode {
    /// Reuse the files on disk untouched, without running Ren'Py.
    Keep,
    /// Rebuild them while adopting their translations.
    Update,
    /// Rebuild them and drop those translations.
    Reset,
}

/// Where the pipeline is, for a progress display.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ExtractionStage {
    Archiving,
    Unpacking,
    Running,
    Parsing,
    Syncing,
}

#[derive(Debug, thiserror::Error)]
pub enum ExtractionError {
    #[error("This folder is not a Ren'Py project: it holds no game/ folder")]
    InvalidProject,
    #[error("'{0}' is not a valid language code")]
    InvalidLanguage(String),
    #[error(transparent)]
    Engine(#[from] EngineError),
    #[error("The existing translation folder could not be archived: {0}")]
    Archive(std::io::Error),
    #[error(transparent)]
    Cli(#[from] CliError),
    #[error("Cannot read the game's archives: {0}")]
    Unpack(#[from] ArchiveError),
    #[error(
        "The game's archives hold only compiled scripts (.rpyc), with no .rpy source to extract"
    )]
    CompiledScriptsOnly,
    #[error(transparent)]
    Parse(#[from] ParseError),
    #[error("Database error: {0}")]
    Database(#[from] rusqlite::Error),
    #[error("Cannot prepare the project's .rts folder: {0}")]
    Io(#[from] std::io::Error),
    #[error("Ren'Py generated no translatable text")]
    NoBlocks,
    #[error(
        "Only the engine's own interface strings (common.rpy) were extracted: the game's \
         scripts were not read, usually because they are packed in an archive"
    )]
    OnlyCommonRpy,
}

impl ExtractionError {
    /// A stable identifier the interface maps to a localized message.
    pub fn code(&self) -> &'static str {
        match self {
            Self::InvalidProject => "invalid_project",
            Self::InvalidLanguage(_) => "invalid_language",
            Self::Engine(EngineError::NotFound) => "no_engine",
            Self::Engine(EngineError::WrongPlatform { .. }) => "engine_wrong_platform",
            Self::Archive(_) => "archive_failed",
            Self::Cli(CliError::Failed { .. }) => "engine_failed",
            Self::Cli(CliError::TimedOut { .. }) => "engine_timed_out",
            Self::Cli(CliError::Spawn(_)) => "engine_not_started",
            Self::Unpack(_) => "unpack_failed",
            Self::CompiledScriptsOnly => "compiled_scripts_only",
            Self::Parse(_) => "parse_failed",
            Self::Database(_) => "database",
            Self::Io(_) => "io",
            Self::NoBlocks => "no_blocks",
            Self::OnlyCommonRpy => "only_common_rpy",
        }
    }
}

pub struct ExtractionRequest<'a> {
    pub project: &'a Path,
    pub source_language: &'a str,
    pub target_language: &'a str,
    pub mode: ExtractMode,
    pub sdk_path: Option<&'a Path>,
}

/// What an extraction did, for the message shown once it is over.
#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExtractionReport {
    /// Translatable units now in the database.
    pub units: usize,
    /// Units that inherited a translation from a vanished block id.
    pub moved: usize,
    /// Obsolete units dropped because the game no longer has them.
    pub obsolete: usize,
    /// Sources unpacked from an archive that Ren'Py could not parse and
    /// that were dropped; their lines stay untranslated.
    pub discarded_sources: Vec<String>,
    /// Units whose stored source text was corrected by this parse.
    pub repaired: usize,
}

pub fn tl_dir(project: &Path, language: &str) -> PathBuf {
    project.join("game").join("tl").join(language)
}

/// Whether the target language folder already holds `.rpy` files.
pub fn has_existing_tl(project: &Path, language: &str) -> bool {
    let dir = tl_dir(project, language);
    dir.is_dir()
        && walkdir::WalkDir::new(&dir)
            .into_iter()
            .filter_map(Result::ok)
            .any(|entry| {
                entry.file_type().is_file()
                    && entry.path().extension().is_some_and(|ext| ext == "rpy")
            })
}

/// Whether every block comes from a bare `common.rpy` file.
///
/// The translate command skips any script packed inside an `.rpa`
/// archive, but still generates `common.rpy` from the engine's own bundled
/// strings. A result made up of nothing else looks like a successful
/// extraction while carrying no dialogue from the game.
pub fn only_common_rpy(blocks: &[TranslationBlock]) -> bool {
    !blocks.is_empty()
        && blocks.iter().all(|block| {
            Path::new(&block.source_file)
                .file_name()
                .is_some_and(|name| name == "common.rpy")
        })
}

/// `YYYYMMDD-HHMMSS`, UTC, from the system clock.
fn utc_stamp() -> String {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs() as i64);
    stamp_from_epoch(seconds)
}

fn stamp_from_epoch(seconds: i64) -> String {
    let days = seconds.div_euclid(86_400);
    let rest = seconds.rem_euclid(86_400);
    // Howard Hinnant's civil-from-days.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}{month:02}{day:02}-{:02}{:02}{:02}",
        rest / 3_600,
        rest % 3_600 / 60,
        rest % 60
    )
}

/// Copy an existing translation folder into the backups, then empty it.
///
/// The folder is copied and emptied rather than moved. Renaming a
/// directory fails on Windows as soon as any process sits inside it, and
/// a translation folder is exactly the kind of place a file manager, an
/// editor or the game itself is left open on. Copying needs no exclusive
/// access, and deleting the files it holds leaves the directory in place
/// for Ren'Py to fill again.
///
/// The archive lives under `.rts/`, outside `game/`, so Ren'Py never picks
/// it up as a second translation of the same language.
pub fn archive_tl_dir(project: &Path, tl_dir: &Path) -> std::io::Result<Option<PathBuf>> {
    if !tl_dir.is_dir() {
        return Ok(None);
    }
    let backups = project.join(".rts").join("backups");
    std::fs::create_dir_all(&backups)?;
    let name = tl_dir
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default();
    let stamp = utc_stamp();
    let mut archive = backups.join(format!("{name}-{stamp}"));
    let mut attempt = 1;
    while archive.exists() {
        archive = backups.join(format!("{name}-{stamp}-{attempt}"));
        attempt += 1;
    }
    for entry in walkdir::WalkDir::new(tl_dir) {
        let entry = entry.map_err(std::io::Error::other)?;
        let relative = entry
            .path()
            .strip_prefix(tl_dir)
            .map_err(std::io::Error::other)?;
        let target = archive.join(relative);
        if entry.file_type().is_dir() {
            std::fs::create_dir_all(&target)?;
        } else {
            if let Some(parent) = target.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::copy(entry.path(), &target)?;
        }
    }
    for entry in walkdir::WalkDir::new(tl_dir) {
        let entry = entry.map_err(std::io::Error::other)?;
        if entry.file_type().is_file() {
            std::fs::remove_file(entry.path())?;
        }
    }
    Ok(Some(archive))
}

/// What the Ren'Py run produced, before it reaches the database.
pub struct Extracted {
    pub blocks: Vec<TranslationBlock>,
    /// The blocks of the folder as it was before being rebuilt, in
    /// `update` mode; they carry the translations to adopt.
    pub disk_blocks: Vec<TranslationBlock>,
    /// See [`ExtractionReport::discarded_sources`].
    pub discarded_sources: Vec<String>,
}

/// How many times Ren'Py may blame an unpacked source before giving up.
/// Generous on purpose: a mixed archive can make every one of its
/// extracted sources conflict, one revealed per round.
const MAX_DISCARD_ROUNDS: usize = 200;

/// Run Ren'Py, dropping the unpacked sources it cannot parse.
///
/// Ren'Py loads every script before generating anything, so a single
/// unparseable one fails the whole run. An archive can hold such a source
/// and still ship a game that runs, because the engine reads the `.rpyc`
/// next to it and never looks at the `.rpy`; unpacking that `.rpy` is what
/// puts it in front of the parser for the first time. Dropping it hands
/// that file back to its `.rpyc`, at the price of its lines staying
/// untranslated.
///
/// Ren'Py stops at the first file it cannot parse and only reveals the
/// next one on the following run, so this retries as long as it keeps
/// blaming a file the manifest recorded. A round that drops nothing of
/// ours returns the error.
///
/// The same loop absorbs a source Ren'Py reports as defined twice, because
/// [`unpacker::disable_extracted_archives`] could not take its archive out
/// of the way (a mixed archive): Ren'Py names it with the same
/// `File "...", line N` shape a parse error uses.
fn translate_discarding_broken_sources(
    engine: &Path,
    request: &ExtractionRequest,
) -> Result<Vec<String>, ExtractionError> {
    let mut discarded = Vec::new();
    for _ in 0..MAX_DISCARD_ROUNDS {
        match cli::translate(
            engine,
            request.project,
            request.target_language,
            cli::TRANSLATE_TIMEOUT,
        ) {
            Ok(()) => return Ok(discarded),
            Err(error) => {
                let blamed = cli::parse_failed_files(error.output());
                let dropped = unpacker::discard_unpacked_files(request.project, &blamed)?;
                if dropped.is_empty() {
                    return Err(error.into());
                }
                discarded.extend(dropped);
            }
        }
    }
    cli::translate(
        engine,
        request.project,
        request.target_language,
        cli::TRANSLATE_TIMEOUT,
    )?;
    Ok(discarded)
}

/// Prepare the `tl/` folder, run Ren'Py when needed and parse the result.
pub fn run_extraction(
    request: &ExtractionRequest,
    progress: &mut dyn FnMut(ExtractionStage),
) -> Result<Extracted, ExtractionError> {
    let dir = tl_dir(request.project, request.target_language);

    let disk_blocks = if request.mode == ExtractMode::Update && dir.is_dir() {
        parser::parse_directory(&dir)?
    } else {
        Vec::new()
    };

    let mut discarded_sources = Vec::new();
    if request.mode != ExtractMode::Keep {
        let engine = engine::resolve_engine(request.project, request.sdk_path)?;
        progress(ExtractionStage::Archiving);
        archive_tl_dir(request.project, &dir).map_err(ExtractionError::Archive)?;
        progress(ExtractionStage::Unpacking);
        let unpacked = unpacker::unpack_archived_sources(request.project)?;
        if unpacked.is_empty() && unpacker::archives_contain_compiled_scripts(request.project)? {
            return Err(ExtractionError::CompiledScriptsOnly);
        }
        unpacker::disable_extracted_archives(request.project)?;
        progress(ExtractionStage::Running);
        let outcome = translate_discarding_broken_sources(&engine, request);
        let restored = unpacker::restore_disabled_archives(request.project);
        discarded_sources = outcome?;
        restored?;
    }

    progress(ExtractionStage::Parsing);
    let blocks = if dir.is_dir() {
        parser::parse_directory(&dir)?
    } else {
        Vec::new()
    };
    let disk_blocks = if request.mode == ExtractMode::Keep {
        blocks.clone()
    } else {
        disk_blocks
    };
    Ok(Extracted {
        blocks,
        disk_blocks,
        discarded_sources,
    })
}

/// Adopt the translations already written in the `tl/` files.
///
/// Only units still `not_translated` are filled, so the database stays
/// authoritative for anything already drafted, suggested or validated.
/// Adopted lines get their own `imported` status rather than borrowing
/// `ai_suggested`: nothing is known about who wrote them, so they must
/// neither be counted as model output nor pass for reviewed work.
///
/// A block whose translation equals its source text is an untouched
/// Ren'Py stub, not a translation, and is skipped (see [`is_translated`]).
fn import_disk_translations(
    conn: &Connection,
    blocks: &[TranslationBlock],
) -> rusqlite::Result<usize> {
    let pending: HashSet<String> = repo::get_all(conn, Some(repo::STATUS_NOT_TRANSLATED), None)?
        .into_iter()
        .map(|unit| unit.block_id)
        .collect();
    let entries: Vec<(String, String, String)> = blocks
        .iter()
        .filter(|block| pending.contains(&block.block_id) && is_translated(block))
        .map(|block| {
            (
                block.block_id.clone(),
                block.translated_text.clone(),
                "imported".to_string(),
            )
        })
        .collect();
    repo::update_translations(conn, &entries)
}

/// Auto-validate units whose source text has nothing to translate.
///
/// Their text is copied verbatim from the source, no model is ever
/// involved, so there is nothing for a human to review: they are marked
/// `human_validated` rather than `ai_suggested`, which keeps the "AI
/// suggested" filter to actual model output. A unit whose text was edited
/// by hand is left alone.
fn validate_symbol_only_units(conn: &Connection) -> rusqlite::Result<usize> {
    let mut entries: Vec<(String, String, String)> = Vec::new();
    for status in [repo::STATUS_NOT_TRANSLATED, "ai_suggested"] {
        for unit in repo::get_all(conn, Some(status), None)? {
            if needs_translation(&unit.source_text) {
                continue;
            }
            if !unit.translated_text.is_empty() && unit.translated_text != unit.source_text {
                continue;
            }
            entries.push((
                unit.block_id,
                unit.source_text,
                repo::STATUS_HUMAN_VALIDATED.to_string(),
            ));
        }
    }
    repo::update_translations(conn, &entries)
}

/// Bring an open project database in line with a parse.
///
/// An empty parse must never reach this: it would make `delete_stale`
/// wipe the whole project, which is why [`extract`] refuses one first.
pub fn sync_database(
    conn: &Connection,
    extracted: &Extracted,
    mode: ExtractMode,
    source_language: &str,
    target_language: &str,
) -> rusqlite::Result<ExtractionReport> {
    if mode == ExtractMode::Reset {
        repo::clear_translations(conn, None, None)?;
    }
    let units: Vec<NewUnit> = extracted
        .blocks
        .iter()
        .map(|block| NewUnit {
            block_id: &block.block_id,
            source_file: &block.source_file,
            source_line: block.source_line,
            character_variable: block.character_variable.as_deref(),
            source_text: &block.source_text,
        })
        .collect();
    repo::bulk_insert(conn, &units)?;
    let resync = repo::resync_sources(conn, &units)?;
    let current: HashSet<String> = extracted
        .blocks
        .iter()
        .map(|block| block.block_id.clone())
        .collect();
    let moved = repo::transfer_orphan_translations(conn, &current)?;
    let obsolete = repo::delete_stale(conn, &current)?;
    import_disk_translations(conn, &extracted.disk_blocks)?;
    validate_symbol_only_units(conn)?;
    repo::set_project_meta(conn, "target_language", target_language)?;
    repo::set_project_meta(conn, "source_language", source_language)?;
    Ok(ExtractionReport {
        units: units.len(),
        moved,
        obsolete,
        repaired: resync.repaired,
        discarded_sources: extracted.discarded_sources.clone(),
    })
}

/// Extract a project: validate the request, run Ren'Py, and write the
/// result into `<project>/.rts/translations.db`.
pub fn extract(
    request: &ExtractionRequest,
    progress: &mut dyn FnMut(ExtractionStage),
) -> Result<ExtractionReport, ExtractionError> {
    if !validate_project_dir(request.project) {
        return Err(ExtractionError::InvalidProject);
    }
    if !validate_language_code(request.target_language) {
        return Err(ExtractionError::InvalidLanguage(
            request.target_language.to_string(),
        ));
    }
    let extracted = run_extraction(request, progress)?;
    if extracted.blocks.is_empty() {
        return Err(ExtractionError::NoBlocks);
    }
    if only_common_rpy(&extracted.blocks) {
        return Err(ExtractionError::OnlyCommonRpy);
    }

    progress(ExtractionStage::Syncing);
    let db_path = Database::path_for(request.project);
    if let Some(parent) = db_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let db = Database::open(&db_path)?;
    Ok(sync_database(
        db.conn(),
        &extracted,
        request.mode,
        request.source_language,
        request.target_language,
    )?)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn block(id: &str, file: &str, source: &str, translated: &str) -> TranslationBlock {
        TranslationBlock {
            block_id: id.to_string(),
            source_file: file.to_string(),
            source_line: 1,
            character_variable: None,
            source_text: source.to_string(),
            translated_text: translated.to_string(),
        }
    }

    fn scratch(name: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("rts-extraction-{name}-{nanos}"));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn open_temp(name: &str) -> Database {
        Database::open(&scratch(name).join("translations.db")).unwrap()
    }

    fn by_id(conn: &Connection, id: &str) -> repo::TranslationUnit {
        repo::get_many(conn, &[id.to_string()]).unwrap().remove(0)
    }

    #[test]
    fn the_timestamp_is_a_civil_utc_date() {
        assert_eq!(stamp_from_epoch(0), "19700101-000000");
        assert_eq!(stamp_from_epoch(1_000_000_000), "20010909-014640");
        assert_eq!(stamp_from_epoch(1_700_000_000), "20231114-221320");
    }

    #[test]
    fn a_result_made_only_of_common_rpy_is_not_an_extraction() {
        let only_common = [block("a", "tl/french/common.rpy", "OK", "")];
        assert!(only_common_rpy(&only_common));
        let mixed = [
            block("a", "tl/french/common.rpy", "OK", ""),
            block("b", "tl/french/script.rpy", "Hi", ""),
        ];
        assert!(!only_common_rpy(&mixed));
        assert!(!only_common_rpy(&[]));
    }

    #[test]
    fn a_first_extraction_inserts_every_block() {
        let db = open_temp("first");
        let extracted = Extracted {
            blocks: vec![
                block("a", "script.rpy", "Hello.", "Hello."),
                block("b", "script.rpy", "Bye.", "Bye."),
            ],
            disk_blocks: Vec::new(),
            discarded_sources: Vec::new(),
        };

        let report = sync_database(
            db.conn(),
            &extracted,
            ExtractMode::Update,
            "english",
            "french",
        )
        .unwrap();

        assert_eq!(report.units, 2);
        let units = repo::get_all(db.conn(), None, None).unwrap();
        assert!(units
            .iter()
            .all(|u| u.status == repo::STATUS_NOT_TRANSLATED));
        assert_eq!(
            repo::get_project_meta(db.conn(), "target_language").unwrap(),
            Some("french".to_string())
        );
    }

    #[test]
    fn translations_on_disk_are_adopted_as_imported_and_stubs_are_not() {
        let db = open_temp("adopt");
        let blocks = vec![
            block("a", "script.rpy", "Hello.", "Bonjour."),
            block("b", "script.rpy", "Bye.", "Bye."),
        ];
        let extracted = Extracted {
            disk_blocks: blocks.clone(),
            blocks,
            discarded_sources: Vec::new(),
        };

        sync_database(
            db.conn(),
            &extracted,
            ExtractMode::Update,
            "english",
            "french",
        )
        .unwrap();

        let a = by_id(db.conn(), "a");
        assert_eq!(
            (a.translated_text.as_str(), a.status.as_str()),
            ("Bonjour.", "imported")
        );
        assert_eq!(by_id(db.conn(), "b").status, repo::STATUS_NOT_TRANSLATED);
    }

    #[test]
    fn re_extracting_never_overwrites_validated_work() {
        let db = open_temp("keep-work");
        let extracted = Extracted {
            blocks: vec![block("a", "script.rpy", "Hello.", "Hello.")],
            disk_blocks: Vec::new(),
            discarded_sources: Vec::new(),
        };
        sync_database(
            db.conn(),
            &extracted,
            ExtractMode::Update,
            "english",
            "french",
        )
        .unwrap();
        repo::update_translation(db.conn(), "a", "Bonjour.", repo::STATUS_HUMAN_VALIDATED).unwrap();
        let again = Extracted {
            blocks: vec![block("a", "script.rpy", "Hello.", "Salut.")],
            disk_blocks: vec![block("a", "script.rpy", "Hello.", "Salut.")],
            discarded_sources: Vec::new(),
        };

        sync_database(db.conn(), &again, ExtractMode::Update, "english", "french").unwrap();

        let a = by_id(db.conn(), "a");
        assert_eq!(a.translated_text, "Bonjour.");
        assert_eq!(a.status, repo::STATUS_HUMAN_VALIDATED);
    }

    #[test]
    fn reset_drops_stored_translations_before_inserting() {
        let db = open_temp("reset");
        let extracted = Extracted {
            blocks: vec![block("a", "script.rpy", "Hello.", "Hello.")],
            disk_blocks: Vec::new(),
            discarded_sources: Vec::new(),
        };
        sync_database(
            db.conn(),
            &extracted,
            ExtractMode::Update,
            "english",
            "french",
        )
        .unwrap();
        repo::update_translation(db.conn(), "a", "Bonjour.", repo::STATUS_HUMAN_VALIDATED).unwrap();

        sync_database(
            db.conn(),
            &extracted,
            ExtractMode::Reset,
            "english",
            "french",
        )
        .unwrap();

        let a = by_id(db.conn(), "a");
        assert_eq!(a.translated_text, "");
        assert_eq!(a.status, repo::STATUS_NOT_TRANSLATED);
    }

    #[test]
    fn a_line_whose_id_was_rebuilt_keeps_its_translation_and_the_orphan_goes() {
        let db = open_temp("rekey");
        let first = Extracted {
            blocks: vec![block("old", "script.rpy", "Hello.", "Hello.")],
            disk_blocks: Vec::new(),
            discarded_sources: Vec::new(),
        };
        sync_database(db.conn(), &first, ExtractMode::Update, "english", "french").unwrap();
        repo::update_translation(db.conn(), "old", "Bonjour.", repo::STATUS_HUMAN_VALIDATED)
            .unwrap();
        let second = Extracted {
            blocks: vec![block("new", "script.rpy", "Hello.", "Hello.")],
            disk_blocks: Vec::new(),
            discarded_sources: Vec::new(),
        };

        let report =
            sync_database(db.conn(), &second, ExtractMode::Update, "english", "french").unwrap();

        assert_eq!((report.moved, report.obsolete), (1, 1));
        let heir = by_id(db.conn(), "new");
        assert_eq!(heir.translated_text, "Bonjour.");
        assert_eq!(heir.status, repo::STATUS_HUMAN_VALIDATED);
        assert!(repo::get_many(db.conn(), &["old".to_string()])
            .unwrap()
            .is_empty());
    }

    #[test]
    fn symbol_only_lines_are_validated_without_a_human() {
        let db = open_temp("symbols");
        let extracted = Extracted {
            blocks: vec![
                block("dots", "script.rpy", "...", "..."),
                block("words", "script.rpy", "Hello.", "Hello."),
            ],
            disk_blocks: Vec::new(),
            discarded_sources: Vec::new(),
        };

        sync_database(
            db.conn(),
            &extracted,
            ExtractMode::Update,
            "english",
            "french",
        )
        .unwrap();

        assert_eq!(
            by_id(db.conn(), "dots").status,
            repo::STATUS_HUMAN_VALIDATED
        );
        assert_eq!(
            by_id(db.conn(), "words").status,
            repo::STATUS_NOT_TRANSLATED
        );
    }

    #[test]
    fn archiving_copies_the_folder_then_empties_it() {
        let project = scratch("archive");
        let dir = tl_dir(&project, "french");
        std::fs::create_dir_all(dir.join("sub")).unwrap();
        std::fs::write(dir.join("script.rpy"), "a").unwrap();
        std::fs::write(dir.join("sub").join("more.rpy"), "b").unwrap();

        let archive = archive_tl_dir(&project, &dir).unwrap().unwrap();

        assert_eq!(
            std::fs::read_to_string(archive.join("script.rpy")).unwrap(),
            "a"
        );
        assert_eq!(
            std::fs::read_to_string(archive.join("sub").join("more.rpy")).unwrap(),
            "b"
        );
        assert!(archive.starts_with(project.join(".rts").join("backups")));
        assert!(dir.is_dir());
        assert!(!dir.join("script.rpy").exists());
        assert!(!dir.join("sub").join("more.rpy").exists());
    }

    #[test]
    fn nothing_is_archived_when_there_is_no_folder() {
        let project = scratch("no-archive");
        assert!(archive_tl_dir(&project, &tl_dir(&project, "french"))
            .unwrap()
            .is_none());
    }

    #[test]
    fn existing_translations_are_detected_by_their_rpy_files() {
        let project = scratch("existing");
        assert!(!has_existing_tl(&project, "french"));
        let dir = tl_dir(&project, "french");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("script.rpyc"), "x").unwrap();
        assert!(!has_existing_tl(&project, "french"));
        std::fs::write(dir.join("script.rpy"), "x").unwrap();
        assert!(has_existing_tl(&project, "french"));
    }

    fn copy_dir(from: &Path, to: &Path) {
        for entry in walkdir::WalkDir::new(from)
            .into_iter()
            .filter_map(Result::ok)
        {
            let target = to.join(entry.path().strip_prefix(from).unwrap());
            if entry.file_type().is_dir() {
                std::fs::create_dir_all(&target).unwrap();
            } else {
                std::fs::copy(entry.path(), &target).unwrap();
            }
        }
    }

    /// Runs the real Ren'Py SDK on a copy of its demo game, The Question,
    /// which ships a `tl/french` of its own: the case `update` exists for.
    /// The SDK is found through `RTS_TEST_RENPY_SDK` (default
    /// `D:\VN\renpy-8.5.3-sdk`); the copy is left in the temp folder.
    #[test]
    #[ignore = "runs the real Ren'Py SDK on this machine"]
    fn extracts_the_question_with_the_real_sdk() {
        let sdk_dir = PathBuf::from(
            std::env::var("RTS_TEST_RENPY_SDK").unwrap_or_else(|_| r"D:\VN\renpy-8.5.3-sdk".into()),
        );
        let exe = sdk_dir.join(if cfg!(windows) {
            "renpy.exe"
        } else {
            "renpy.sh"
        });
        let demo = sdk_dir.join("the_question");
        assert!(
            exe.is_file() && demo.is_dir(),
            "no SDK at {}",
            sdk_dir.display()
        );

        let project = std::env::temp_dir()
            .join("rts-real-extraction")
            .join("the_question");
        let _ = std::fs::remove_dir_all(&project);
        std::fs::create_dir_all(&project).unwrap();
        copy_dir(&demo, &project);

        let run = |mode| {
            let mut stages = Vec::new();
            let report = extract(
                &ExtractionRequest {
                    project: &project,
                    source_language: "english",
                    target_language: "french",
                    mode,
                    sdk_path: Some(&exe),
                },
                &mut |stage| stages.push(stage),
            )
            .unwrap();
            let db = Database::open_readonly(&Database::path_for(&project)).unwrap();
            let counts = repo::count_by_status(db.conn()).unwrap();
            println!("{mode:?}: {report:?} {counts:?} {stages:?}");
            (report, counts)
        };

        let (update, counts) = run(ExtractMode::Update);
        assert!(update.units > 100);
        assert!(
            counts.get("imported").copied().unwrap_or(0) > 0,
            "no adopted translation"
        );
        let backups = project.join(".rts").join("backups");
        assert!(backups.is_dir() && std::fs::read_dir(&backups).unwrap().count() == 1);

        let (keep, _) = run(ExtractMode::Keep);
        assert_eq!(keep.units, update.units);

        let (reset, counts) = run(ExtractMode::Reset);
        assert_eq!(reset.units, update.units);
        assert_eq!(counts.get("imported").copied().unwrap_or(0), 0);
    }

    /// Extracts the game named by `RTS_TEST_PACKED_GAME` (a throwaway copy,
    /// it is modified) with the engine it ships, to exercise the archive
    /// path: unpack, disable, run, restore.
    #[test]
    #[ignore = "needs RTS_TEST_PACKED_GAME, a copy of a game with a scripts .rpa"]
    fn extracts_a_packed_game_with_its_own_engine() {
        let project = PathBuf::from(std::env::var("RTS_TEST_PACKED_GAME").expect("env var"));
        let archives_before: Vec<_> = std::fs::read_dir(project.join("game"))
            .unwrap()
            .filter_map(Result::ok)
            .map(|e| e.file_name())
            .collect();
        let started = std::time::Instant::now();
        let mut stages = Vec::new();
        let report = extract(
            &ExtractionRequest {
                project: &project,
                source_language: "english",
                target_language: "french",
                mode: ExtractMode::Update,
                sdk_path: None,
            },
            &mut |stage| stages.push(stage),
        )
        .unwrap();
        println!("{report:?} {stages:?} in {:?}", started.elapsed());

        let db = Database::open_readonly(&Database::path_for(&project)).unwrap();
        let ids: Vec<String> = repo::get_all(db.conn(), None, None)
            .unwrap()
            .into_iter()
            .map(|u| u.block_id)
            .collect();
        std::fs::write(project.join(".rts").join("rust_ids.txt"), ids.join("\n")).unwrap();
        let archives_after: Vec<_> = std::fs::read_dir(project.join("game"))
            .unwrap()
            .filter_map(Result::ok)
            .map(|e| e.file_name())
            .collect();
        for name in &archives_before {
            assert!(
                archives_after.contains(name),
                "{name:?} vanished from game/"
            );
        }
        assert!(report.units > 0);
    }

    #[test]
    fn a_request_is_validated_before_anything_runs() {
        let not_a_project = scratch("invalid");
        let request = ExtractionRequest {
            project: &not_a_project,
            source_language: "english",
            target_language: "french",
            mode: ExtractMode::Update,
            sdk_path: None,
        };
        assert!(matches!(
            extract(&request, &mut |_| {}),
            Err(ExtractionError::InvalidProject)
        ));

        std::fs::create_dir_all(not_a_project.join("game")).unwrap();
        let bad_language = ExtractionRequest {
            target_language: "../evil",
            ..request
        };
        assert!(matches!(
            extract(&bad_language, &mut |_| {}),
            Err(ExtractionError::InvalidLanguage(_))
        ));
    }
}
