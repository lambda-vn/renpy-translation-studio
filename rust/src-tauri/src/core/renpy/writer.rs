//! Writes validated translations back into Ren'Py `.rpy` files.
//!
//! Port of `core/renpy/writer.py`. Always backs up a file to
//! `backup_dir` before touching it, and only ever rewrites the one line
//! per block a translation belongs on — `say_line::find_say` is the same
//! lookup `core::renpy::parser` uses to read it, so the two modules
//! cannot disagree about which line that is.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use regex::Regex;

use super::say_line::{block_lines, find_say, split_say_line};

static UNESCAPED_QUOTE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r#"(\\*)""#).unwrap());
static TRAILING_BACKSLASHES: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\\+$").unwrap());
static HEADER: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^translate \w+ (\w+):\s*$").unwrap());
static STRINGS_HEADER: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^translate \w+ strings:\s*$").unwrap());
static OLD_LINE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"^    old "((?:[^"\\]|\\.)*)""#).unwrap());
static NEW_LINE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"^    new "((?:[^"\\]|\\.)*)""#).unwrap());

#[derive(Debug, thiserror::Error)]
pub enum WriteError {
    #[error("cannot read {0}: {1}")]
    Read(PathBuf, std::io::Error),
    #[error("cannot write {0}: {1}")]
    Write(PathBuf, std::io::Error),
    #[error("cannot back up {0}: {1}")]
    Backup(PathBuf, std::io::Error),
    #[error("cannot walk {0}: {1}")]
    Walk(PathBuf, walkdir::Error),
}

/// Rewrites editable lines in `tl/<lang>/*.rpy` with validated
/// translations. Always creates a backup in `backup_dir` before
/// modifying any file.
pub struct TranslateBlockWriter {
    tl_dir: PathBuf,
    backup_dir: PathBuf,
}

impl TranslateBlockWriter {
    pub fn new(tl_dir: PathBuf, backup_dir: PathBuf) -> Self {
        Self { tl_dir, backup_dir }
    }

    /// Write every provided translation into its `.rpy` file.
    ///
    /// `translations` maps a dialogue block's `block_id` to its
    /// validated text; `old_to_new` maps a `strings:` block's original
    /// text to its translation, since a strings block carries no header
    /// identifier to key on.
    pub fn write_all(
        &self,
        translations: &HashMap<String, String>,
        old_to_new: &HashMap<String, String>,
    ) -> Result<(), WriteError> {
        for entry in walkdir::WalkDir::new(&self.tl_dir) {
            let entry = entry.map_err(|e| WriteError::Walk(self.tl_dir.clone(), e))?;
            if entry.file_type().is_file() && entry.path().extension().is_some_and(|e| e == "rpy") {
                self.write_file(entry.path(), translations, old_to_new)?;
            }
        }
        Ok(())
    }

    /// Back up a file if changed, then rewrite its editable lines.
    fn write_file(
        &self,
        path: &Path,
        translations: &HashMap<String, String>,
        old_to_new: &HashMap<String, String>,
    ) -> Result<(), WriteError> {
        let content =
            std::fs::read_to_string(path).map_err(|e| WriteError::Read(path.to_path_buf(), e))?;
        let modified = apply_translations(&content, translations, old_to_new);
        if modified == content {
            return Ok(());
        }
        self.backup(path)?;
        std::fs::write(path, modified).map_err(|e| WriteError::Write(path.to_path_buf(), e))
    }

    fn backup(&self, path: &Path) -> Result<(), WriteError> {
        let relative = path.strip_prefix(&self.tl_dir).unwrap_or(path);
        let backup_path = self.backup_dir.join(relative);
        if let Some(parent) = backup_path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| WriteError::Backup(path.to_path_buf(), e))?;
        }
        std::fs::copy(path, &backup_path).map_err(|e| WriteError::Backup(path.to_path_buf(), e))?;
        Ok(())
    }
}

/// Split into lines with their line endings still attached, the way
/// Python's `str.splitlines(keepends=True)` does for `\n`/`\r\n` — the
/// writer has to hand back untouched lines byte-for-byte, unlike the
/// parser, which only ever reads line content.
fn split_keepends(content: &str) -> Vec<String> {
    let mut result = Vec::new();
    let mut start = 0;
    for (i, byte) in content.as_bytes().iter().enumerate() {
        if *byte == b'\n' {
            result.push(content[start..=i].to_string());
            start = i + 1;
        }
    }
    if start < content.len() {
        result.push(content[start..].to_string());
    }
    result
}

/// The index of the line a translation is written into: the block's say
/// statement, which is neither its first line nor always its only
/// statement. Ren'Py writes a blank line under every header, then the
/// commented source, and it groups the `voice` playing under a line of
/// dialogue, or the `nvl clear` before it, into the same block —
/// stopping at the first line that was neither blank nor a comment would
/// land on `voice "v/e01.ogg"` and replace the audio path with the
/// dialogue's translation.
fn find_editable_line(lines: &[String], start: usize) -> Option<usize> {
    let (offset, _) = find_say(block_lines(lines, start))?;
    Some(start + offset)
}

/// Replace editable lines for matching blocks.
///
/// Handles two block formats: dialogue blocks (`translate lang
/// block_id:` / comment / editable line) and strings blocks (`translate
/// lang strings:` / `old "..."` / `new "..."`). A dialogue block header
/// also exits strings mode, since a strings block only ends at the next
/// block header or a non-indented line.
fn apply_translations(
    content: &str,
    translations: &HashMap<String, String>,
    old_to_new: &HashMap<String, String>,
) -> String {
    let lines = split_keepends(content);
    let mut result = String::with_capacity(content.len());
    let mut i = 0usize;
    let mut in_strings = false;
    let mut pending_old: Option<String> = None;

    while i < lines.len() {
        let line = &lines[i];

        if STRINGS_HEADER.is_match(line) {
            in_strings = true;
            pending_old = None;
            result.push_str(line);
            i += 1;
            continue;
        }

        if let Some(caps) = HEADER.captures(line) {
            in_strings = false;
            pending_old = None;
            let block_id = caps[1].to_string();
            result.push_str(line);
            i += 1;
            if let Some(new_text) = translations.get(&block_id) {
                if let Some(editable) = find_editable_line(&lines, i) {
                    for skipped in &lines[i..editable] {
                        result.push_str(skipped);
                    }
                    result.push_str(&replace_quoted(&lines[editable], new_text));
                    i = editable + 1;
                }
            }
            continue;
        }

        if in_strings {
            let starts_indented = matches!(line.chars().next(), Some(' ') | Some('\t'));
            if !line.trim().is_empty() && !starts_indented {
                in_strings = false;
                pending_old = None;
                result.push_str(line);
                i += 1;
                continue;
            }

            if let Some(caps) = OLD_LINE.captures(line) {
                pending_old = Some(caps[1].to_string());
                result.push_str(line);
                i += 1;
                continue;
            }

            if NEW_LINE.is_match(line) && pending_old.is_some() && !old_to_new.is_empty() {
                let old = pending_old.as_deref().unwrap();
                match old_to_new.get(old) {
                    Some(new_text) => result.push_str(&replace_quoted(line, new_text)),
                    None => result.push_str(line),
                }
                pending_old = None;
                i += 1;
                continue;
            }
        }

        result.push_str(line);
        i += 1;
    }

    result
}

/// Neutralize characters that would break out of a `.rpy` string
/// literal.
///
/// Translations come from external providers (or human edits) and are
/// inserted verbatim between double quotes by [`replace_quoted`]. A raw
/// double quote would terminate the string literal early and a raw line
/// break would inject new script lines — both would let a hostile
/// "translation" plant arbitrary Ren'Py statements in the generated
/// file. A quote preceded by an odd number of backslashes is already
/// escaped and left untouched, since providers commonly echo the `\"`
/// sequences present in the source text.
///
/// Text ending on an odd number of backslashes gets one more, because
/// [`replace_quoted`] appends the closing quote right after it: the last
/// backslash would escape that quote and let the literal run to the end
/// of the line, which Ren'Py refuses to load.
fn escape_translation(text: &str) -> String {
    let escaped = UNESCAPED_QUOTE.replace_all(text, |caps: &regex::Captures| {
        let backslashes = &caps[1];
        if backslashes.chars().count() % 2 == 1 {
            format!("{backslashes}\"")
        } else {
            format!("{backslashes}\\\"")
        }
    });
    let escaped = TRAILING_BACKSLASHES.replace(&escaped, |caps: &regex::Captures| {
        let matched = &caps[0];
        if matched.chars().count() % 2 == 1 {
            format!("{matched}\\")
        } else {
            matched.to_string()
        }
    });
    escaped
        .replace("\r\n", "\\n")
        .replace('\n', "\\n")
        .replace('\r', "\\n")
}

/// Replace the spoken string of an editable line with a translation.
///
/// The string is located by [`split_say_line`], the same way the parser
/// located the source text this translation answers, so the two cannot
/// disagree about which of a line's quoted strings belongs to the
/// translator. Everything else is kept verbatim: indentation, the
/// speaker, a `with` clause, keyword arguments, the line break. Taking
/// everything between the first and the last quote of the line instead
/// would overwrite the speaker of `"Store clerk" "Not so fast!"` and
/// swallow the arguments of `e "Hi" (what_color="#fff")`.
fn replace_quoted(line: &str, new_text: &str) -> String {
    match split_say_line(line) {
        Some(say) => format!(
            "{}\"{}\"{}",
            say.prefix,
            escape_translation(new_text),
            say.suffix
        ),
        None => line.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_tl_dir() -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!(
            "rts-writer-test-{nanos}-{:?}",
            std::thread::current().id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn translations(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn writes_a_simple_dialogue_translation() {
        let tl_dir = temp_tl_dir();
        let backup_dir = tl_dir.join("backup");
        let path = tl_dir.join("script.rpy");
        std::fs::write(
            &path,
            "translate french start_x:\n    # e \"Hello.\"\n    e \"\"\n",
        )
        .unwrap();

        let writer = TranslateBlockWriter::new(tl_dir.clone(), backup_dir.clone());
        writer
            .write_all(&translations(&[("start_x", "Bonjour.")]), &HashMap::new())
            .unwrap();

        let written = std::fs::read_to_string(&path).unwrap();
        assert_eq!(
            written,
            "translate french start_x:\n    # e \"Hello.\"\n    e \"Bonjour.\"\n"
        );
        assert!(backup_dir.join("script.rpy").is_file());
    }

    #[test]
    fn unmodified_file_is_left_untouched_and_not_backed_up() {
        let tl_dir = temp_tl_dir();
        let backup_dir = tl_dir.join("backup");
        let path = tl_dir.join("script.rpy");
        let original = "translate french start_x:\n    # e \"Hello.\"\n    e \"\"\n";
        std::fs::write(&path, original).unwrap();

        let writer = TranslateBlockWriter::new(tl_dir, backup_dir.clone());
        writer.write_all(&HashMap::new(), &HashMap::new()).unwrap();

        assert_eq!(std::fs::read_to_string(&path).unwrap(), original);
        assert!(!backup_dir.exists());
    }

    #[test]
    fn skips_a_voice_line_grouped_under_the_same_block() {
        let tl_dir = temp_tl_dir();
        let path = tl_dir.join("script.rpy");
        std::fs::write(
            &path,
            "translate french start_x:\n    # e \"Hello.\"\n    voice \"v/e01.ogg\"\n    e \"\"\n",
        )
        .unwrap();

        let writer = TranslateBlockWriter::new(tl_dir.clone(), tl_dir.join("backup"));
        writer
            .write_all(&translations(&[("start_x", "Bonjour.")]), &HashMap::new())
            .unwrap();

        let written = std::fs::read_to_string(&path).unwrap();
        assert!(written.contains("voice \"v/e01.ogg\"\n"));
        assert!(written.ends_with("    e \"Bonjour.\"\n"));
    }

    #[test]
    fn writes_a_strings_block_by_old_text() {
        let tl_dir = temp_tl_dir();
        let path = tl_dir.join("common.rpy");
        std::fs::write(
            &path,
            "translate french strings:\n    old \"Yes\"\n    new \"\"\n",
        )
        .unwrap();

        let mut old_to_new = HashMap::new();
        old_to_new.insert("Yes".to_string(), "Oui".to_string());

        let writer = TranslateBlockWriter::new(tl_dir.clone(), tl_dir.join("backup"));
        writer.write_all(&HashMap::new(), &old_to_new).unwrap();

        let written = std::fs::read_to_string(&path).unwrap();
        assert_eq!(
            written,
            "translate french strings:\n    old \"Yes\"\n    new \"Oui\"\n"
        );
    }

    #[test]
    fn a_dialogue_header_ends_strings_mode() {
        let tl_dir = temp_tl_dir();
        let path = tl_dir.join("mixed.rpy");
        std::fs::write(
            &path,
            "translate french strings:\n    old \"Yes\"\n\
translate french start_x:\n    # e \"Hi\"\n    e \"\"\n",
        )
        .unwrap();

        let mut old_to_new = HashMap::new();
        // Would misfire as a "new" line for "Yes" if strings mode leaked
        // past the dialogue header.
        old_to_new.insert("Yes".to_string(), "SHOULD NOT APPEAR".to_string());

        let writer = TranslateBlockWriter::new(tl_dir.clone(), tl_dir.join("backup"));
        writer
            .write_all(&translations(&[("start_x", "Salut")]), &old_to_new)
            .unwrap();

        let written = std::fs::read_to_string(&path).unwrap();
        assert!(!written.contains("SHOULD NOT APPEAR"));
        assert!(written.contains("e \"Salut\""));
    }

    #[test]
    fn escapes_a_raw_quote_in_the_translation() {
        let tl_dir = temp_tl_dir();
        let path = tl_dir.join("script.rpy");
        std::fs::write(
            &path,
            "translate french start_x:\n    # e \"Hi\"\n    e \"\"\n",
        )
        .unwrap();

        let writer = TranslateBlockWriter::new(tl_dir.clone(), tl_dir.join("backup"));
        writer
            .write_all(
                &translations(&[("start_x", "She said \"hi\".")]),
                &HashMap::new(),
            )
            .unwrap();

        let written = std::fs::read_to_string(&path).unwrap();
        assert!(written.contains(r#"e "She said \"hi\"."#));
    }

    #[test]
    fn escapes_a_line_break_as_literal_n() {
        let tl_dir = temp_tl_dir();
        let path = tl_dir.join("script.rpy");
        std::fs::write(
            &path,
            "translate french start_x:\n    # e \"Hi\"\n    e \"\"\n",
        )
        .unwrap();

        let writer = TranslateBlockWriter::new(tl_dir.clone(), tl_dir.join("backup"));
        writer
            .write_all(
                &translations(&[("start_x", "Line one\nLine two")]),
                &HashMap::new(),
            )
            .unwrap();

        let written = std::fs::read_to_string(&path).unwrap();
        assert!(written.contains(r#"e "Line one\nLine two""#));
    }

    #[test]
    fn preserves_speaker_and_with_clause() {
        let tl_dir = temp_tl_dir();
        let path = tl_dir.join("script.rpy");
        std::fs::write(
            &path,
            "translate french start_x:\n    # \"Store clerk\" \"Not so fast!\" with hpunch\n    \"Store clerk\" \"\" with hpunch\n",
        )
        .unwrap();

        let writer = TranslateBlockWriter::new(tl_dir.clone(), tl_dir.join("backup"));
        writer
            .write_all(
                &translations(&[("start_x", "Pas si vite !")]),
                &HashMap::new(),
            )
            .unwrap();

        let written = std::fs::read_to_string(&path).unwrap();
        assert!(written.contains("\"Store clerk\" \"Pas si vite !\" with hpunch"));
    }

    #[test]
    fn crlf_line_endings_are_preserved() {
        let tl_dir = temp_tl_dir();
        let path = tl_dir.join("script.rpy");
        std::fs::write(
            &path,
            "translate french start_x:\r\n    # e \"Hi\"\r\n    e \"\"\r\n",
        )
        .unwrap();

        let writer = TranslateBlockWriter::new(tl_dir.clone(), tl_dir.join("backup"));
        writer
            .write_all(&translations(&[("start_x", "Salut")]), &HashMap::new())
            .unwrap();

        let written = std::fs::read_to_string(&path).unwrap();
        assert_eq!(
            written,
            "translate french start_x:\r\n    # e \"Hi\"\r\n    e \"Salut\"\r\n"
        );
    }

    #[test]
    fn split_keepends_matches_python_semantics() {
        assert_eq!(split_keepends("a\nb\r\nc"), vec!["a\n", "b\r\n", "c"]);
        assert_eq!(split_keepends("a\n"), vec!["a\n"]);
        assert_eq!(split_keepends(""), Vec::<String>::new());
    }
}
