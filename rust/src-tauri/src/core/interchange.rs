//! Bilingual interchange files: CSV, XLIFF 1.2 and JSON round-trips. Port
//! of `core/interchange.py`.
//!
//! Translations leave the studio for a proofreader or a CAT tool (OmegaT,
//! memoQ) and come back in the same file. Units travel keyed by their
//! Ren'Py block id, never by position, and carry their source text along:
//! a file written against an older extraction is then detected instead of
//! silently pairing a translation with a line that changed underneath it.
//!
//! CSV and JSON also carry the studio's own status, so a file that never
//! left the tool comes back exactly as it went out. XLIFF only knows its
//! own `state` vocabulary, so the round-trip through it is lossy by
//! construction: everything a CAT tool did not mark final returns as
//! `imported`, the status for text nobody has read in this project yet.
//!
//! Reading XLIFF never expands an entity: `quick-xml` leaves a custom one
//! unresolved, and a document declaring any is refused outright, which is
//! what makes an entity bomb impossible.

use std::collections::HashMap;
use std::path::Path;

use quick_xml::escape::resolve_xml_entity;
use quick_xml::events::{BytesDecl, BytesEnd, BytesStart, BytesText, Event};
use quick_xml::{Reader, Writer};
use rusqlite::Connection;
use serde::Serialize;

use super::languages::get_language;
use super::storage::repositories::{self, TranslationUnit};
use super::translation::quality::{self, LENGTH_WARNING_KIND};

pub const XLIFF_NAMESPACE: &str = "urn:oasis:names:tc:xliff:document:1.2";
pub const JSON_FORMAT: &str = "renpy-translation-studio";
pub const JSON_VERSION: u32 = 1;

/// The extensions a file can be picked with when reading one back.
pub const READABLE_EXTENSIONS: [&str; 4] = ["csv", "xlf", "xliff", "json"];

const CSV_FIELDS: [&str; 7] = [
    "block_id",
    "source_file",
    "source_line",
    "character",
    "source_text",
    "translated_text",
    "status",
];

const STATUSES: [&str; 5] = [
    "not_translated",
    "draft",
    "imported",
    "ai_suggested",
    "human_validated",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Format {
    Csv,
    Xliff,
    Json,
}

impl Format {
    /// The extension a file written in this format carries.
    pub fn extension(self) -> &'static str {
        match self {
            Self::Csv => "csv",
            Self::Xliff => "xlf",
            Self::Json => "json",
        }
    }

    /// The format a file's own extension names, whatever its case.
    pub fn of(path: &Path) -> Result<Self, InterchangeError> {
        let extension = path
            .extension()
            .map(|e| e.to_string_lossy().to_lowercase())
            .unwrap_or_default();
        match extension.as_str() {
            "csv" => Ok(Self::Csv),
            "xlf" | "xliff" => Ok(Self::Xliff),
            "json" => Ok(Self::Json),
            other => Err(InterchangeError::UnsupportedFormat(format!(".{other}"))),
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum InterchangeError {
    #[error("Unsupported interchange format: {0}")]
    UnsupportedFormat(String),
    #[error("File is not encoded in UTF-8")]
    NotUtf8,
    #[error("Invalid CSV file: {0}")]
    Csv(String),
    #[error("CSV file has no block_id column")]
    NoBlockIdColumn,
    #[error("Invalid JSON file: {0}")]
    Json(String),
    #[error("JSON file holds no unit list")]
    NoUnitList,
    #[error("Invalid XLIFF file: {0}")]
    Xliff(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

/// One translation read back from an interchange file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InterchangeUnit {
    pub block_id: String,
    /// The source the file was written against, empty when the file
    /// carries no source column.
    pub source_text: String,
    pub translated_text: String,
    /// Already normalised by [`read_status`].
    pub status: String,
}

/// What an interchange file would do to the project, before it does it.
///
/// Nothing here has been written yet, so a plan can be shown, counted and
/// thrown away. [`apply_plan`] is what commits it.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct ImportPlan {
    /// The `(block_id, translated_text, status)` triples that would be
    /// written.
    #[serde(skip)]
    pub entries: Vec<(String, String, String)>,
    /// Block ids the project does not hold, typically a file exported from
    /// another game.
    pub unknown: usize,
    /// Units whose source text no longer matches the project, so the
    /// translation would land on a line that has since changed.
    pub stale: usize,
    /// Units the file brought back without a translation, left alone
    /// rather than clearing what the project already holds.
    pub empty: usize,
    /// Units already validated by a human, which only an incoming
    /// validated status may replace.
    pub protected: usize,
    /// Units written as drafts instead of validated, a quality check
    /// having refused the text. They are part of `entries`.
    pub flagged: usize,
}

impl ImportPlan {
    /// How many translations applying this plan would write.
    pub fn applicable(&self) -> usize {
        self.entries.len()
    }
}

/// The columns CSV and JSON share.
#[derive(Serialize)]
struct Row<'a> {
    block_id: &'a str,
    source_file: &'a str,
    source_line: i64,
    character: &'a str,
    source_text: &'a str,
    translated_text: &'a str,
    status: &'a str,
}

impl<'a> From<&'a TranslationUnit> for Row<'a> {
    fn from(unit: &'a TranslationUnit) -> Self {
        Self {
            block_id: &unit.block_id,
            source_file: &unit.source_file,
            source_line: unit.source_line,
            character: unit.character_variable.as_deref().unwrap_or(""),
            source_text: &unit.source_text,
            translated_text: &unit.translated_text,
            status: &unit.status,
        }
    }
}

/// Write translation units to a file, in the format its extension names.
pub fn write_interchange(
    path: &Path,
    units: &[TranslationUnit],
    source_language: &str,
    target_language: &str,
) -> Result<(), InterchangeError> {
    match Format::of(path)? {
        Format::Csv => write_csv(path, units),
        Format::Xliff => write_xliff(path, units, source_language, target_language),
        Format::Json => write_json(path, units, source_language, target_language),
    }
}

/// Read back the translations held in an interchange file: one unit per
/// row carrying a block id, in file order.
pub fn read_interchange(path: &Path) -> Result<Vec<InterchangeUnit>, InterchangeError> {
    let format = Format::of(path)?;
    let bytes = std::fs::read(path)?;
    let text = String::from_utf8(bytes).map_err(|_| InterchangeError::NotUtf8)?;
    let text = text.strip_prefix('\u{feff}').unwrap_or(&text);
    match format {
        Format::Csv => read_csv(text),
        Format::Xliff => read_xliff(text),
        Format::Json => read_json(text),
    }
}

/// Work out what an interchange file would change, without changing it.
///
/// Every unit is paired by block id, so a file may hold a subset of the
/// project, come back reordered, or carry rows the project never had. Four
/// cases are counted instead of applied, and reported rather than silently
/// dropped: unknown ids, a source text that has changed since the export,
/// an empty translation, and a line a human already validated.
///
/// A fifth is counted and applied: a rewritten translation a quality check
/// refuses comes in as a draft rather than validated. The same text typed
/// into the review screen behaves exactly that way, so an import is no
/// longer a way to reach `human_validated` with a dropped `[player_name]`.
/// Dropping the text outright would be worse than keeping it: the project
/// would hold on to whatever broken translation it already had, and saving
/// writes that one to the `.rpy` just the same.
pub fn plan_import(units: &[InterchangeUnit], conn: &Connection) -> rusqlite::Result<ImportPlan> {
    let stored: HashMap<String, TranslationUnit> = repositories::get_all(conn, None, None)?
        .into_iter()
        .map(|unit| (unit.block_id.clone(), unit))
        .collect();
    let mut plan = ImportPlan::default();

    for unit in units {
        let Some(current) = stored.get(&unit.block_id) else {
            plan.unknown += 1;
            continue;
        };
        if unit.translated_text.trim().is_empty() {
            plan.empty += 1;
        } else if !unit.source_text.is_empty() && unit.source_text != current.source_text {
            plan.stale += 1;
        } else if current.status == "human_validated" && unit.status != "human_validated" {
            plan.protected += 1;
        } else {
            let mut status = incoming_status(unit, current);
            if must_be_drafted(unit, current, &status) {
                status = "draft".to_string();
                plan.flagged += 1;
            }
            plan.entries
                .push((unit.block_id.clone(), unit.translated_text.clone(), status));
        }
    }
    Ok(plan)
}

/// Write the translations a plan holds; returns how many units were
/// actually updated.
pub fn apply_plan(plan: &ImportPlan, conn: &Connection) -> rusqlite::Result<usize> {
    repositories::update_translations(conn, &plan.entries)
}

/// Whether a translation may not come in as validated.
///
/// Only a rewritten text is weighed. One that matches what the project
/// already holds changes nothing, and re-judging it would have a file
/// exported and imported back unchanged report refusals it did not cause.
///
/// The rule itself is the review screen's: everything the quality check
/// reports bars validation, except the length warning, which flags an
/// unusual ratio rather than something broken.
fn must_be_drafted(unit: &InterchangeUnit, current: &TranslationUnit, status: &str) -> bool {
    if status != "human_validated" || unit.translated_text == current.translated_text {
        return false;
    }
    quality::check(&current.source_text, &unit.translated_text)
        .iter()
        .any(|issue| issue.kind != LENGTH_WARNING_KIND)
}

/// What status a translation coming back deserves.
///
/// A file edited outside the studio keeps the status column it left with,
/// so text a proofreader rewrote in a spreadsheet still reads
/// `ai_suggested` on the way back. Storing it as such would hand human work
/// to "clear the AI suggestions", which erases it without a word. Text that
/// differs from what the project holds is therefore taken as `imported`.
///
/// A file that went out and came back untouched keeps its status, so the
/// round-trip through the studio's own formats stays lossless.
fn incoming_status(unit: &InterchangeUnit, current: &TranslationUnit) -> String {
    let rewritten = unit.translated_text != current.translated_text;
    if unit.status == "ai_suggested" && rewritten {
        "imported".to_string()
    } else {
        unit.status.clone()
    }
}

/// Turn the status column of a file into one the project can store.
///
/// A file edited outside the studio has no reason to keep the column
/// honest: a spreadsheet row can carry a translation and still read
/// `not_translated`, and a foreign tool writes whatever it likes. Anything
/// the project does not recognise, and anything claiming no translation,
/// becomes `imported`, which is what text of unknown provenance means here.
fn read_status(status: &str) -> String {
    if STATUSES.contains(&status) && status != "not_translated" {
        status.to_string()
    } else {
        "imported".to_string()
    }
}

/// UTF-8 CSV with a BOM, which is what makes spreadsheets open the file
/// as UTF-8 instead of the system codepage, where accented translations
/// go to die.
fn write_csv(path: &Path, units: &[TranslationUnit]) -> Result<(), InterchangeError> {
    let mut writer = csv::WriterBuilder::new()
        .terminator(csv::Terminator::CRLF)
        .from_writer(Vec::new());
    writer
        .write_record(CSV_FIELDS)
        .map_err(|e| InterchangeError::Csv(e.to_string()))?;
    for unit in units {
        let row = Row::from(unit);
        writer
            .write_record([
                row.block_id,
                row.source_file,
                &row.source_line.to_string(),
                row.character,
                row.source_text,
                row.translated_text,
                row.status,
            ])
            .map_err(|e| InterchangeError::Csv(e.to_string()))?;
    }
    let body = writer
        .into_inner()
        .map_err(|e| InterchangeError::Csv(e.to_string()))?;
    let mut file = vec![0xEF, 0xBB, 0xBF];
    file.extend_from_slice(&body);
    std::fs::write(path, file)?;
    Ok(())
}

fn read_csv(text: &str) -> Result<Vec<InterchangeUnit>, InterchangeError> {
    let mut reader = csv::ReaderBuilder::new()
        .flexible(true)
        .from_reader(text.as_bytes());
    let headers = reader
        .headers()
        .map_err(|e| InterchangeError::Csv(e.to_string()))?
        .clone();
    let column = |name: &str| headers.iter().position(|header| header == name);
    let block_id = column("block_id").ok_or(InterchangeError::NoBlockIdColumn)?;
    let (source, translated, status) = (
        column("source_text"),
        column("translated_text"),
        column("status"),
    );

    let mut units = Vec::new();
    for record in reader.records() {
        let record = record.map_err(|e| InterchangeError::Csv(e.to_string()))?;
        let cell = |index: Option<usize>| index.and_then(|i| record.get(i)).unwrap_or("");
        let id = cell(Some(block_id));
        if id.is_empty() {
            continue;
        }
        units.push(InterchangeUnit {
            block_id: id.to_string(),
            source_text: cell(source).to_string(),
            translated_text: cell(translated).to_string(),
            status: read_status(cell(status)),
        });
    }
    Ok(units)
}

fn write_json(
    path: &Path,
    units: &[TranslationUnit],
    source_language: &str,
    target_language: &str,
) -> Result<(), InterchangeError> {
    #[derive(Serialize)]
    struct Document<'a> {
        format: &'static str,
        version: u32,
        source_language: &'a str,
        target_language: &'a str,
        units: Vec<Row<'a>>,
    }
    let document = Document {
        format: JSON_FORMAT,
        version: JSON_VERSION,
        source_language,
        target_language,
        units: units.iter().map(Row::from).collect(),
    };
    let mut text = serde_json::to_string_pretty(&document)
        .map_err(|e| InterchangeError::Json(e.to_string()))?;
    text.push('\n');
    std::fs::write(path, text)?;
    Ok(())
}

/// A JSON document written by [`write_json`], or a bare list of units.
fn read_json(text: &str) -> Result<Vec<InterchangeUnit>, InterchangeError> {
    let payload: serde_json::Value =
        serde_json::from_str(text).map_err(|e| InterchangeError::Json(e.to_string()))?;
    let rows = match &payload {
        serde_json::Value::Object(map) => map.get("units"),
        other => Some(other),
    };
    let Some(serde_json::Value::Array(rows)) = rows else {
        return Err(InterchangeError::NoUnitList);
    };
    let text_of = |row: &serde_json::Value, key: &str| match row.get(key) {
        Some(serde_json::Value::String(value)) => value.clone(),
        Some(serde_json::Value::Null) | None => String::new(),
        Some(other) => other.to_string(),
    };
    Ok(rows
        .iter()
        .filter(|row| row.is_object())
        .filter_map(|row| {
            let block_id = text_of(row, "block_id");
            (!block_id.is_empty()).then(|| InterchangeUnit {
                block_id,
                source_text: text_of(row, "source_text"),
                translated_text: text_of(row, "translated_text"),
                status: read_status(&text_of(row, "status")),
            })
        })
        .collect())
}

fn xliff_state(status: &str) -> &'static str {
    match status {
        "not_translated" => "new",
        "draft" => "needs-translation",
        "final" => "final",
        "human_validated" => "final",
        _ => "needs-review-translation",
    }
}

/// The language tag a CAT tool expects for a Ren'Py folder name (`pt-BR`
/// for `brazilian`), or the code itself for a folder no language declares.
fn xliff_language(code: &str) -> String {
    get_language(code).map_or_else(|| code.to_string(), |l| l.long_code().to_string())
}

/// Drop the characters an XML 1.0 document has no way to hold.
///
/// XML 1.0 offers no escape for them, so a file carrying one would fail to
/// parse on the way back in: an export that succeeded would have produced
/// something no CAT tool can open. Ren'Py dialogue has no reason to carry
/// one; a game generating text at runtime might.
fn xml_safe(text: &str) -> String {
    text.chars()
        .filter(|c| {
            !matches!(
                *c,
                '\u{0}'..='\u{8}' | '\u{b}' | '\u{c}' | '\u{e}'..='\u{1f}' | '\u{fffe}' | '\u{ffff}'
            )
        })
        .collect()
}

fn write_xliff(
    path: &Path,
    units: &[TranslationUnit],
    source_language: &str,
    target_language: &str,
) -> Result<(), InterchangeError> {
    let xml = |e: std::io::Error| InterchangeError::Xliff(e.to_string());
    let mut writer = Writer::new_with_indent(Vec::new(), b' ', 2);
    writer
        .write_event(Event::Decl(BytesDecl::new("1.0", Some("UTF-8"), None)))
        .map_err(xml)?;
    let mut root = BytesStart::new("xliff");
    root.push_attribute(("xmlns", XLIFF_NAMESPACE));
    root.push_attribute(("version", "1.2"));
    writer.write_event(Event::Start(root)).map_err(xml)?;

    let mut order: Vec<&str> = Vec::new();
    let mut by_file: HashMap<&str, Vec<&TranslationUnit>> = HashMap::new();
    for unit in units {
        let entry = by_file.entry(unit.source_file.as_str()).or_default();
        if entry.is_empty() {
            order.push(unit.source_file.as_str());
        }
        entry.push(unit);
    }

    let source_tag = xliff_language(source_language);
    let target_tag = xliff_language(target_language);
    for source_file in order {
        let mut file = BytesStart::new("file");
        file.push_attribute(("original", source_file));
        file.push_attribute(("source-language", source_tag.as_str()));
        file.push_attribute(("target-language", target_tag.as_str()));
        file.push_attribute(("datatype", "plaintext"));
        writer.write_event(Event::Start(file)).map_err(xml)?;
        writer
            .write_event(Event::Start(BytesStart::new("body")))
            .map_err(xml)?;
        for unit in &by_file[source_file] {
            let mut trans = BytesStart::new("trans-unit");
            trans.push_attribute(("id", unit.block_id.as_str()));
            writer.write_event(Event::Start(trans)).map_err(xml)?;

            let mut text_element = |name: &str, attribute: Option<(&str, &str)>, text: &str| {
                let mut start = BytesStart::new(name);
                if let Some(pair) = attribute {
                    start.push_attribute(pair);
                }
                writer.write_event(Event::Start(start))?;
                writer.write_event(Event::Text(BytesText::new(&xml_safe(text))))?;
                writer.write_event(Event::End(BytesEnd::new(name)))
            };
            text_element("source", None, &unit.source_text).map_err(xml)?;
            text_element(
                "target",
                Some(("state", xliff_state(&unit.status))),
                &unit.translated_text,
            )
            .map_err(xml)?;
            if let Some(character) = unit.character_variable.as_deref().filter(|c| !c.is_empty()) {
                text_element("note", None, character).map_err(xml)?;
            }
            writer
                .write_event(Event::End(BytesEnd::new("trans-unit")))
                .map_err(xml)?;
        }
        writer
            .write_event(Event::End(BytesEnd::new("body")))
            .map_err(xml)?;
        writer
            .write_event(Event::End(BytesEnd::new("file")))
            .map_err(xml)?;
    }
    writer
        .write_event(Event::End(BytesEnd::new("xliff")))
        .map_err(xml)?;
    std::fs::write(path, writer.into_inner())?;
    Ok(())
}

/// Which direct child of a `trans-unit` text is being gathered for.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Part {
    Source,
    Target,
}

/// A `trans-unit` being read.
#[derive(Default)]
struct Pending {
    id: String,
    source: String,
    target: String,
    state: String,
}

impl Pending {
    fn push(&mut self, part: Part, text: &str) {
        match part {
            Part::Source => self.source.push_str(text),
            Part::Target => self.target.push_str(text),
        }
    }

    fn finish(self) -> Option<InterchangeUnit> {
        (!self.id.is_empty()).then(|| InterchangeUnit {
            block_id: self.id,
            source_text: self.source,
            translated_text: self.target,
            status: if matches!(self.state.as_str(), "final" | "signed-off") {
                "human_validated".to_string()
            } else {
                "imported".to_string()
            },
        })
    }
}

fn attribute(start: &BytesStart, name: &str) -> Option<String> {
    start
        .attributes()
        .filter_map(Result::ok)
        .find(|attribute| attribute.key.local_name().as_ref() == name)
        .and_then(|attribute| {
            attribute
                .normalized_value(quick_xml::XmlVersion::Implicit1_0)
                .ok()
                .map(|value| value.into_owned())
        })
}

/// The trans-units of an XLIFF document, whatever tool wrote it.
///
/// Text is gathered from everything under `source` and `target`, so a CAT
/// tool that wrapped segments in inline markup still yields the sentence
/// instead of the text before its first tag. Only the direct children of a
/// `trans-unit` count, as in the Python reader: an `alt-trans` carries its
/// own source and target that are not this unit's.
fn read_xliff(text: &str) -> Result<Vec<InterchangeUnit>, InterchangeError> {
    let fail = |message: String| InterchangeError::Xliff(message);
    let mut reader = Reader::from_str(text);
    reader.config_mut().trim_text(false);

    let mut units = Vec::new();
    let mut pending: Option<Pending> = None;
    let mut unit_depth = 0usize;
    let mut depth = 0usize;
    let mut part: Option<(Part, usize)> = None;

    loop {
        match reader.read_event().map_err(|e| fail(e.to_string()))? {
            Event::Eof => break,
            Event::DocType(doctype) => {
                if doctype.contains("<!ENTITY") {
                    return Err(fail("entity declarations are not allowed".to_string()));
                }
            }
            Event::Start(start) => {
                depth += 1;
                let name = start.local_name();
                match (&mut pending, part) {
                    (None, _) if name.as_ref() == "trans-unit" => {
                        pending = Some(Pending {
                            id: attribute(&start, "id").unwrap_or_default(),
                            ..Pending::default()
                        });
                        unit_depth = depth;
                    }
                    (Some(unit), None) if depth == unit_depth + 1 => match name.as_ref() {
                        "source" => part = Some((Part::Source, depth)),
                        "target" => {
                            unit.state = attribute(&start, "state").unwrap_or_default();
                            part = Some((Part::Target, depth));
                        }
                        _ => {}
                    },
                    _ => {}
                }
            }
            Event::End(_) => {
                if part.is_some_and(|(_, part_depth)| part_depth == depth) {
                    part = None;
                }
                if depth == unit_depth {
                    if let Some(unit) = pending.take().and_then(Pending::finish) {
                        units.push(unit);
                    }
                }
                depth = depth.saturating_sub(1);
            }
            Event::Text(chunk) => append(&mut pending, part, &chunk.xml10_content()),
            Event::CData(chunk) => append(&mut pending, part, &chunk.xml10_content()),
            Event::GeneralRef(reference) => {
                let resolved = match reference
                    .resolve_char_ref()
                    .map_err(|e| fail(e.to_string()))?
                {
                    Some(character) => character.to_string(),
                    None => resolve_xml_entity(&reference)
                        .ok_or_else(|| fail(format!("undefined entity &{};", &*reference)))?
                        .to_string(),
                };
                append(&mut pending, part, &resolved);
            }
            _ => {}
        }
    }
    if depth != 0 {
        return Err(fail("unexpected end of document".to_string()));
    }
    Ok(units)
}

fn append(pending: &mut Option<Pending>, part: Option<(Part, usize)>, text: &str) {
    if let (Some(unit), Some((which, _))) = (pending.as_mut(), part) {
        unit.push(which, text);
    }
}

#[cfg(test)]
mod tests {
    use super::super::storage::repositories::{bulk_insert, update_translation, NewUnit};
    use super::super::storage::Database;
    use super::*;

    fn scratch(name: &str) -> std::path::PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("rts-interchange-{name}-{nanos}"));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    /// A project of three units, as the Python suite's fixture holds.
    fn project(name: &str) -> (Database, std::path::PathBuf) {
        let dir = scratch(name);
        let db = Database::open(&dir.join("test.db")).unwrap();
        let unit = |block_id, file, line, character, source| NewUnit {
            block_id,
            source_file: file,
            source_line: line,
            character_variable: character,
            source_text: source,
        };
        bulk_insert(
            db.conn(),
            &[
                unit("start_aaa", "game/script.rpy", 10, Some("m"), "Hello."),
                unit("start_bbb", "game/script.rpy", 12, None, "It rains."),
                unit("strings_ccc", "game/options.rpy", 3, None, "Start"),
            ],
        )
        .unwrap();
        (db, dir)
    }

    fn export(db: &Database, dir: &Path, file: &str) -> std::path::PathBuf {
        let path = dir.join(file);
        let units = repositories::get_all(db.conn(), None, None).unwrap();
        write_interchange(&path, &units, "english", "brazilian").unwrap();
        path
    }

    fn incoming(id: &str, source: &str, translation: &str, status: &str) -> InterchangeUnit {
        InterchangeUnit {
            block_id: id.into(),
            source_text: source.into(),
            translated_text: translation.into(),
            status: status.into(),
        }
    }

    fn run_import(units: &[InterchangeUnit], db: &Database) -> (ImportPlan, usize) {
        let plan = plan_import(units, db.conn()).unwrap();
        let applied = apply_plan(&plan, db.conn()).unwrap();
        (plan, applied)
    }

    fn stored(db: &Database, id: &str) -> TranslationUnit {
        repositories::get_many(db.conn(), &[id.to_string()])
            .unwrap()
            .remove(0)
    }

    #[test]
    fn round_trip_keeps_block_ids_and_text_in_every_format() {
        for file in ["export.csv", "export.json", "export.xlf"] {
            let (db, dir) = project("round-trip");
            update_translation(db.conn(), "start_aaa", "Bonjour à toi.", "human_validated")
                .unwrap();
            let read: HashMap<String, InterchangeUnit> = read_interchange(&export(&db, &dir, file))
                .unwrap()
                .into_iter()
                .map(|u| (u.block_id.clone(), u))
                .collect();

            assert_eq!(read.len(), 3, "{file}");
            assert_eq!(
                read["start_aaa"].translated_text, "Bonjour à toi.",
                "{file}"
            );
            assert_eq!(read["start_aaa"].source_text, "Hello.", "{file}");
            assert_eq!(read["start_aaa"].status, "human_validated", "{file}");
        }
    }

    #[test]
    fn csv_and_json_keep_the_ai_status() {
        for file in ["export.csv", "export.json"] {
            let (db, dir) = project("ai-status");
            update_translation(db.conn(), "start_bbb", "Il pleut.", "ai_suggested").unwrap();
            let read = read_interchange(&export(&db, &dir, file)).unwrap();
            let unit = read.iter().find(|u| u.block_id == "start_bbb").unwrap();
            assert_eq!(unit.status, "ai_suggested", "{file}");
        }
    }

    #[test]
    fn xliff_downgrades_unreviewed_status_to_imported() {
        let (db, dir) = project("xliff-status");
        update_translation(db.conn(), "start_bbb", "Il pleut.", "ai_suggested").unwrap();
        let read = read_interchange(&export(&db, &dir, "export.xlf")).unwrap();
        let unit = read.iter().find(|u| u.block_id == "start_bbb").unwrap();
        assert_eq!(unit.status, "imported");
    }

    #[test]
    fn xliff_uses_regional_language_tags() {
        let (db, dir) = project("xliff-tags");
        let content = std::fs::read_to_string(export(&db, &dir, "export.xlf")).unwrap();
        assert!(content.contains(r#"source-language="en""#), "{content}");
        assert!(content.contains(r#"target-language="pt-BR""#), "{content}");
        assert!(content.contains(XLIFF_NAMESPACE));
    }

    #[test]
    fn csv_is_written_with_a_bom_and_crlf() {
        let (db, dir) = project("bom");
        let bytes = std::fs::read(export(&db, &dir, "export.csv")).unwrap();
        assert!(bytes.starts_with(&[0xEF, 0xBB, 0xBF]));
        assert!(String::from_utf8(bytes).unwrap().contains("\r\n"));
    }

    #[test]
    fn an_unknown_extension_is_rejected_both_ways() {
        let (db, dir) = project("suffix");
        let units = repositories::get_all(db.conn(), None, None).unwrap();
        assert!(matches!(
            write_interchange(&dir.join("export.txt"), &units, "english", "french"),
            Err(InterchangeError::UnsupportedFormat(_))
        ));
        std::fs::write(dir.join("in.txt"), "x").unwrap();
        assert!(read_interchange(&dir.join("in.txt")).is_err());
    }

    #[test]
    fn foreign_and_broken_files_are_rejected_not_panicked() {
        let dir = scratch("broken");
        std::fs::write(dir.join("foreign.csv"), "source,target\nHello,Bonjour\n").unwrap();
        assert!(matches!(
            read_interchange(&dir.join("foreign.csv")),
            Err(InterchangeError::NoBlockIdColumn)
        ));
        std::fs::write(dir.join("broken.json"), "{not json").unwrap();
        assert!(matches!(
            read_interchange(&dir.join("broken.json")),
            Err(InterchangeError::Json(_))
        ));
        std::fs::write(dir.join("list.json"), r#"{"units": 3}"#).unwrap();
        assert!(matches!(
            read_interchange(&dir.join("list.json")),
            Err(InterchangeError::NoUnitList)
        ));
        std::fs::write(dir.join("latin1.csv"), [b'b', b'l', 0xE9]).unwrap();
        assert!(matches!(
            read_interchange(&dir.join("latin1.csv")),
            Err(InterchangeError::NotUtf8)
        ));
        std::fs::write(
            dir.join("cut.xlf"),
            r#"<xliff><file><body><trans-unit id="a">"#,
        )
        .unwrap();
        assert!(read_interchange(&dir.join("cut.xlf")).is_err());
    }

    #[test]
    fn a_bare_json_list_is_accepted() {
        let dir = scratch("bare");
        std::fs::write(
            dir.join("bare.json"),
            r#"[{"block_id": "start_aaa", "translated_text": "Bonjour.", "status": "draft"}]"#,
        )
        .unwrap();
        let read = read_interchange(&dir.join("bare.json")).unwrap();
        assert_eq!(read, [incoming("start_aaa", "", "Bonjour.", "draft")]);
    }

    #[test]
    fn an_xliff_entity_bomb_is_rejected() {
        let dir = scratch("bomb");
        std::fs::write(
            dir.join("bomb.xlf"),
            r#"<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;">
]>
<xliff><file><body><trans-unit id="a"><source>&lol1;</source></trans-unit></body></file></xliff>"#,
        )
        .unwrap();
        assert!(matches!(
            read_interchange(&dir.join("bomb.xlf")),
            Err(InterchangeError::Xliff(_))
        ));
    }

    #[test]
    fn xliff_reads_namespaceless_files_inline_markup_and_entities() {
        let dir = scratch("cat-tool");
        std::fs::write(
            dir.join("cat_tool.xlf"),
            r#"<?xml version="1.0"?><xliff version="1.2"><file original="game/script.rpy"><body>
<trans-unit id="start_aaa"><source>Hello &amp; &#65;.</source>
<target state="final">Bon<g id="1">jour</g> &lt;toi&gt;.</target>
<alt-trans><source>no</source><target>no</target></alt-trans>
</trans-unit></body></file></xliff>"#,
        )
        .unwrap();

        let units = read_interchange(&dir.join("cat_tool.xlf")).unwrap();

        assert_eq!(units.len(), 1);
        assert_eq!(units[0].source_text, "Hello & A.");
        assert_eq!(units[0].translated_text, "Bonjour <toi>.");
        assert_eq!(units[0].status, "human_validated");
    }

    #[test]
    fn xliff_export_stays_readable_with_control_characters() {
        let (db, dir) = project("control");
        update_translation(
            db.conn(),
            "start_aaa",
            "Bon\u{c}jour & <fin>.",
            "human_validated",
        )
        .unwrap();
        let read = read_interchange(&export(&db, &dir, "export.xlf")).unwrap();
        let unit = read.iter().find(|u| u.block_id == "start_aaa").unwrap();
        assert_eq!(unit.translated_text, "Bonjour & <fin>.");
    }

    #[test]
    fn csv_keeps_commas_quotes_and_line_breaks() {
        let (db, dir) = project("csv-quoting");
        let text = "Il dit : \"oui, non\"\net voilà.";
        update_translation(db.conn(), "start_aaa", text, "draft").unwrap();
        let read = read_interchange(&export(&db, &dir, "export.csv")).unwrap();
        let unit = read.iter().find(|u| u.block_id == "start_aaa").unwrap();
        assert_eq!(unit.translated_text, text);
    }

    #[test]
    fn an_import_applies_translations_by_block_id() {
        let (db, _) = project("apply");
        let (_, applied) = run_import(
            &[
                incoming("strings_ccc", "Start", "Commencer", "imported"),
                incoming("start_aaa", "Hello.", "Bonjour.", "human_validated"),
            ],
            &db,
        );
        assert_eq!(applied, 2);
        assert_eq!(stored(&db, "start_aaa").status, "human_validated");
        assert_eq!(stored(&db, "strings_ccc").status, "imported");
    }

    #[test]
    fn planning_an_import_writes_nothing() {
        let (db, _) = project("plan-only");
        let plan = plan_import(
            &[incoming("start_aaa", "Hello.", "Bonjour.", "imported")],
            db.conn(),
        )
        .unwrap();
        assert_eq!(plan.applicable(), 1);
        assert_eq!(stored(&db, "start_aaa").translated_text, "");
        assert_eq!(stored(&db, "start_aaa").status, "not_translated");
    }

    #[test]
    fn unknown_stale_empty_and_protected_lines_are_counted_not_applied() {
        let (db, _) = project("skips");
        update_translation(db.conn(), "start_bbb", "Il pleut.", "human_validated").unwrap();
        let (plan, applied) = run_import(
            &[
                incoming("other_game_xyz", "Hi", "Salut", "imported"),
                incoming("start_aaa", "Hello there.", "Bonjour.", "imported"),
                incoming("strings_ccc", "Start", "   ", "imported"),
                incoming("start_bbb", "It rains.", "Il pleuvine.", "imported"),
            ],
            &db,
        );
        assert_eq!(
            (
                plan.unknown,
                plan.stale,
                plan.empty,
                plan.protected,
                applied
            ),
            (1, 1, 1, 1, 0)
        );
        assert_eq!(stored(&db, "start_bbb").translated_text, "Il pleut.");
        assert_eq!(stored(&db, "start_aaa").translated_text, "");
    }

    #[test]
    fn an_import_applies_when_the_file_carries_no_source() {
        let (db, _) = project("no-source");
        let (_, applied) = run_import(&[incoming("start_aaa", "", "Bonjour.", "imported")], &db);
        assert_eq!(applied, 1);
    }

    #[test]
    fn dishonest_status_columns_become_imported() {
        for raw in ["", "not_translated", "reviewed-by-someone-else"] {
            let (db, dir) = project("dishonest");
            std::fs::write(
                dir.join("edited.csv"),
                format!(
                    "block_id,source_text,translated_text,status\nstart_aaa,Hello.,Bonjour.,{raw}\n"
                ),
            )
            .unwrap();
            let units = read_interchange(&dir.join("edited.csv")).unwrap();
            run_import(&units, &db);
            assert_eq!(units[0].status, "imported", "{raw:?}");
            assert_eq!(stored(&db, "start_aaa").status, "imported", "{raw:?}");
        }
    }

    #[test]
    fn proofread_suggestions_come_back_as_imported() {
        let (db, dir) = project("proofread");
        update_translation(db.conn(), "start_bbb", "Il pleut.", "ai_suggested").unwrap();
        let path = export(&db, &dir, "export.csv");
        let edited = std::fs::read_to_string(&path)
            .unwrap()
            .replace("Il pleut.", "Il pleut des cordes.");
        std::fs::write(&path, edited).unwrap();

        run_import(&read_interchange(&path).unwrap(), &db);

        assert_eq!(
            stored(&db, "start_bbb").translated_text,
            "Il pleut des cordes."
        );
        assert_eq!(stored(&db, "start_bbb").status, "imported");
    }

    #[test]
    fn a_translation_that_lost_a_variable_lands_as_a_draft() {
        let (db, _) = project("lost-variable");
        bulk_insert(
            db.conn(),
            &[NewUnit {
                block_id: "start_ddd",
                source_file: "game/script.rpy",
                source_line: 20,
                character_variable: None,
                source_text: "Hi [player_name].",
            }],
        )
        .unwrap();

        let (plan, applied) = run_import(
            &[incoming(
                "start_ddd",
                "Hi [player_name].",
                "Salut toi.",
                "human_validated",
            )],
            &db,
        );

        assert_eq!((plan.flagged, applied), (1, 1));
        assert_eq!(stored(&db, "start_ddd").translated_text, "Salut toi.");
        assert_eq!(stored(&db, "start_ddd").status, "draft");
    }

    #[test]
    fn an_unchanged_translation_is_never_flagged() {
        let (db, dir) = project("unchanged");
        bulk_insert(
            db.conn(),
            &[NewUnit {
                block_id: "start_ddd",
                source_file: "game/script.rpy",
                source_line: 20,
                character_variable: None,
                source_text: "Hi [player_name].",
            }],
        )
        .unwrap();
        update_translation(db.conn(), "start_ddd", "Salut toi.", "human_validated").unwrap();
        let path = export(&db, &dir, "export.csv");

        let (plan, _) = run_import(&read_interchange(&path).unwrap(), &db);

        assert_eq!(plan.flagged, 0);
        assert_eq!(stored(&db, "start_ddd").status, "human_validated");
    }

    #[test]
    fn a_merely_long_translation_is_accepted_and_untouched_suggestions_keep_their_status() {
        let (db, dir) = project("long");
        let (plan, applied) = run_import(
            &[incoming(
                "start_bbb",
                "It rains.",
                "Il pleut des cordes depuis ce matin.",
                "human_validated",
            )],
            &db,
        );
        assert_eq!((plan.flagged, applied), (0, 1));

        update_translation(db.conn(), "strings_ccc", "Démarrer.", "ai_suggested").unwrap();
        let path = export(&db, &dir, "export.csv");
        run_import(&read_interchange(&path).unwrap(), &db);
        assert_eq!(stored(&db, "strings_ccc").status, "ai_suggested");
    }
}
