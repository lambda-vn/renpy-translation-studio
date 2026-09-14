//! Parser for Ren'Py translation (`.rpy`) files.
//!
//! Port of `core/renpy/parser.py`. Reads only what Ren'Py itself
//! generates under `tl/<language>/` — this is not a parser for game
//! source, and CLAUDE.md is explicit that it must never become one.

use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use regex::Regex;

use super::say_line::{block_lines, find_say};

static TRANSLATE_HEADER: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^translate\s+\S+\s+(\w+)\s*:").unwrap());
static STRINGS_HEADER: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^translate\s+\S+\s+strings\s*:").unwrap());
static OLD_LINE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"^    old "((?:[^"\\]|\\.)*)"$"#).unwrap());
static NEW_LINE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"^    new "((?:[^"\\]|\\.)*)""#).unwrap());
static COMMENT_LINE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^    #(?: (.*))?$").unwrap());
static SRC_MULTILINE_START: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"^(?:(\w+) )?"""$"#).unwrap());
static FILE_REF: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[\w./\-]+\.rpy:\d+$").unwrap());

#[derive(Debug, thiserror::Error)]
pub enum ParseError {
    #[error("cannot read {0}: {1}")]
    Io(PathBuf, std::io::Error),
    #[error("cannot walk {0}: {1}")]
    Walk(PathBuf, walkdir::Error),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TranslationBlock {
    pub block_id: String,
    pub source_file: String,
    pub source_line: i64,
    pub character_variable: Option<String>,
    pub source_text: String,
    pub translated_text: String,
}

/// Whether a parsed block already carries a real translation.
///
/// The Ren'Py SDK seeds every freshly generated block with a copy of the
/// source text, so a translation equal to its source means "not
/// translated yet". Multiline blocks always count as untranslated:
/// their translation line cannot be read back reliably.
pub fn is_translated(block: &TranslationBlock) -> bool {
    if block.source_text.contains('\n') {
        return false;
    }
    !block.translated_text.is_empty() && block.translated_text != block.source_text
}

/// Parse all translation blocks in a single `.rpy` file.
pub fn parse_file(path: &Path) -> Result<Vec<TranslationBlock>, ParseError> {
    let text = std::fs::read_to_string(path).map_err(|e| ParseError::Io(path.to_path_buf(), e))?;
    let source_file = path.to_string_lossy().into_owned();
    let lines: Vec<String> = text.lines().map(String::from).collect();

    let mut blocks = Vec::new();
    let mut i = 0usize;
    while i < lines.len() {
        if STRINGS_HEADER.is_match(&lines[i]) {
            let (mut str_blocks, next) = parse_strings_body(&lines, i + 1, &source_file);
            blocks.append(&mut str_blocks);
            i = next;
        } else if let Some(caps) = TRANSLATE_HEADER.captures(&lines[i]) {
            let block_id = caps[1].to_string();
            let source_line = (i + 1) as i64;
            let (block, next) =
                parse_block_body(&lines, i + 1, &block_id, &source_file, source_line);
            if let Some(block) = block {
                blocks.push(block);
            }
            i = next;
        } else {
            i += 1;
        }
    }
    Ok(blocks)
}

/// Parse all translation blocks in a directory of `.rpy` files (e.g.
/// `tl/french/`), sorted by file path then line number.
pub fn parse_directory(tl_dir: &Path) -> Result<Vec<TranslationBlock>, ParseError> {
    let mut rpy_files: Vec<PathBuf> = Vec::new();
    for entry in walkdir::WalkDir::new(tl_dir) {
        let entry = entry.map_err(|e| ParseError::Walk(tl_dir.to_path_buf(), e))?;
        if entry.file_type().is_file() && entry.path().extension().is_some_and(|e| e == "rpy") {
            rpy_files.push(entry.into_path());
        }
    }
    rpy_files.sort();

    let mut blocks = Vec::new();
    for rpy_file in rpy_files {
        blocks.extend(parse_file(&rpy_file)?);
    }
    Ok(blocks)
}

/// Parse the indented body of a `translate ... <block_id>:` header.
///
/// The translation is read from the block's say statement, which
/// `find_say()` picks out of everything Ren'Py wrote under the header: a
/// `voice` grouped with the dialogue answers to `split_say_line()` just
/// as well, and reading the first line took its audio path for the
/// translation.
fn parse_block_body(
    lines: &[String],
    start: usize,
    block_id: &str,
    source_file: &str,
    source_line: i64,
) -> (Option<TranslationBlock>, usize) {
    let mut i = start;
    let mut comment_contents: Vec<String> = Vec::new();

    while i < lines.len() && lines[i].trim().is_empty() {
        i += 1;
    }

    while i < lines.len() {
        match COMMENT_LINE.captures(&lines[i]) {
            Some(caps) => {
                comment_contents.push(
                    caps.get(1)
                        .map_or(String::new(), |m| m.as_str().to_string()),
                );
                i += 1;
            }
            None => break,
        }
    }

    if comment_contents.is_empty() {
        return (None, i);
    }

    let (char_var, source_text) = parse_comment_source(&comment_contents);

    let mut translated_text = String::new();
    if let Some((offset, say)) = find_say(block_lines(lines, i)) {
        translated_text = say.text;
        i += offset + 1;
    }

    (
        Some(TranslationBlock {
            block_id: block_id.to_string(),
            source_file: source_file.to_string(),
            source_line,
            character_variable: char_var,
            source_text,
            translated_text,
        }),
        i,
    )
}

/// Extract character variable and source text from comment lines.
///
/// Leading SDK file-reference lines (e.g. `renpy/common/x.rpy:28`) are
/// skipped before looking for the actual source line. The comments are
/// the block's statements copied verbatim, so `find_say()` is what picks
/// the one line a translator answers rather than the first one written.
fn parse_comment_source(comment_contents: &[String]) -> (Option<String>, String) {
    if comment_contents.is_empty() {
        return (None, String::new());
    }

    let mut contents = comment_contents;
    while let Some(first) = contents.first() {
        if FILE_REF.is_match(first) {
            contents = &contents[1..];
        } else {
            break;
        }
    }

    if contents.is_empty() {
        return (None, String::new());
    }

    if let Some((_, say)) = find_say(contents) {
        return (say.who, say.text);
    }

    let first = &contents[0];

    if let Some(caps) = SRC_MULTILINE_START.captures(first.as_str()) {
        let char_var = caps.get(1).map(|m| m.as_str().to_string());
        let mut inner = &contents[1..];
        if inner.last().map(String::as_str) == Some("\"\"\"") {
            inner = &inner[..inner.len() - 1];
        }
        return (char_var, inner.join("\n"));
    }

    if let Some(say) = super::say_line::split_say_line(first) {
        return (say.who, say.text);
    }

    (None, first.clone())
}

/// Parse old/new string pairs from a `translate ... strings:` block.
///
/// The block ends at the first non-indented, non-empty line. Each
/// `block_id` is a hash of `(source_file, old_text)`, since strings
/// blocks carry no header identifier to key on.
fn parse_strings_body(
    lines: &[String],
    start: usize,
    source_file: &str,
) -> (Vec<TranslationBlock>, usize) {
    let mut blocks = Vec::new();
    let mut i = start;

    while i < lines.len() {
        let line = &lines[i];
        if !line.trim().is_empty() && !matches!(line.chars().next(), Some(' ') | Some('\t')) {
            break;
        }

        let Some(caps) = OLD_LINE.captures(line) else {
            i += 1;
            continue;
        };
        let old_text = caps[1].to_string();
        let old_line_no = (i + 1) as i64;
        i += 1;

        while i < lines.len() && lines[i].trim().is_empty() {
            i += 1;
        }

        let mut new_text = String::new();
        if i < lines.len() {
            if let Some(caps) = NEW_LINE.captures(&lines[i]) {
                new_text = caps[1].to_string();
                i += 1;
            }
        }

        let mut data = source_file.as_bytes().to_vec();
        data.push(0);
        data.extend_from_slice(old_text.as_bytes());
        let crc = crc32fast::hash(&data);
        let block_id = format!("strings_{crc:08x}");

        blocks.push(TranslationBlock {
            block_id,
            source_file: source_file.to_string(),
            source_line: old_line_no,
            character_variable: None,
            source_text: old_text,
            translated_text: new_text,
        });
    }

    (blocks, i)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_fixture(dir: &Path, name: &str, content: &str) -> PathBuf {
        let path = dir.join(name);
        std::fs::write(&path, content).unwrap();
        path
    }

    fn temp_dir() -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!(
            "rts-parser-test-{nanos}-{:?}",
            std::thread::current().id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    const SIMPLE_DIALOGUE: &str = "translate french start_636ae3f5:\n\
         \x20   # e \"Hello, how are you today?\"\n\
         \x20   e \"\"\n\
         \n\
         translate french start_7ab12c3d:\n\
         \x20   # e \"I am fine, thank you.\"\n\
         \x20   e \"\"\n\
         \n\
         translate french start_9ef45a2b:\n\
         \x20   # m \"Nice to meet you!\"\n\
         \x20   m \"\"\n";

    #[test]
    fn parses_three_dialogue_blocks() {
        let dir = temp_dir();
        let path = write_fixture(&dir, "simple_dialogue.rpy", SIMPLE_DIALOGUE);
        let blocks = parse_file(&path).unwrap();

        assert_eq!(blocks.len(), 3);
        assert_eq!(blocks[0].block_id, "start_636ae3f5");
        assert_eq!(blocks[0].character_variable.as_deref(), Some("e"));
        assert_eq!(blocks[0].source_text, "Hello, how are you today?");
        assert_eq!(blocks[0].translated_text, "");
        assert_eq!(blocks[0].source_line, 1);
        assert_eq!(blocks[2].character_variable.as_deref(), Some("m"));
    }

    #[test]
    fn is_translated_is_false_when_equal_to_source() {
        let dir = temp_dir();
        let path = write_fixture(&dir, "d.rpy", SIMPLE_DIALOGUE);
        let blocks = parse_file(&path).unwrap();
        assert!(!is_translated(&blocks[0]));
    }

    #[test]
    fn is_translated_is_true_for_a_real_translation() {
        let content = "translate french start_x:\n\
             \x20   # e \"Hello.\"\n\
             \x20   e \"Bonjour.\"\n";
        let dir = temp_dir();
        let path = write_fixture(&dir, "d.rpy", content);
        let blocks = parse_file(&path).unwrap();
        assert!(is_translated(&blocks[0]));
    }

    #[test]
    fn multiline_block_is_never_translated() {
        let content = "translate french multi_aa1bb2cc:\n\
             \x20   # e \"\"\"\n\
             \x20   # This is the first line.\n\
             \x20   # This is the second line.\n\
             \x20   # \"\"\"\n\
             \x20   e \"\"\n";
        let dir = temp_dir();
        let path = write_fixture(&dir, "d.rpy", content);
        let blocks = parse_file(&path).unwrap();
        assert_eq!(
            blocks[0].source_text,
            "This is the first line.\nThis is the second line."
        );
        assert!(!is_translated(&blocks[0]));
    }

    #[test]
    fn parses_a_single_strings_pair() {
        let content = "translate french strings:\n    old \"Hello\"\n    new \"Bonjour\"\n";
        let dir = temp_dir();
        let path = write_fixture(&dir, "strings.rpy", content);
        let blocks = parse_file(&path).unwrap();
        assert_eq!(blocks[0].source_text, "Hello");
        assert_eq!(blocks[0].translated_text, "Bonjour");
        assert!(blocks[0].block_id.starts_with("strings_"));
    }

    #[test]
    fn strings_block_empty_new_is_empty_translation() {
        let content = "translate french strings:\n    old \"Hi\"\n    new \"\"\n";
        let dir = temp_dir();
        let path = write_fixture(&dir, "strings.rpy", content);
        let blocks = parse_file(&path).unwrap();
        assert_eq!(blocks[0].translated_text, "");
    }

    #[test]
    fn strings_and_dialogue_coexist_in_one_file() {
        let content = format!(
            "{SIMPLE_DIALOGUE}\ntranslate french strings:\n    old \"Yes\"\n    new \"Oui\"\n"
        );
        let dir = temp_dir();
        let path = write_fixture(&dir, "mixed.rpy", &content);
        let blocks = parse_file(&path).unwrap();
        assert_eq!(blocks.len(), 4);
    }

    #[test]
    fn strings_block_id_is_stable_and_deterministic() {
        let content = "translate french strings:\n    old \"X\"\n    new \"Y\"\n";
        let dir = temp_dir();
        let path1 = write_fixture(&dir, "a.rpy", content);
        let path2 = write_fixture(&dir, "b.rpy", content);
        let blocks1 = parse_file(&path1).unwrap();
        let blocks2 = parse_file(&path1).unwrap();
        let blocks3 = parse_file(&path2).unwrap();
        assert_eq!(blocks1[0].block_id, blocks2[0].block_id);
        // Different source_file feeds the hash, so the same old text in
        // a different file gets a different id.
        assert_ne!(blocks1[0].block_id, blocks3[0].block_id);
    }

    #[test]
    fn parse_directory_walks_and_sorts_rpy_files() {
        let dir = temp_dir();
        std::fs::create_dir_all(dir.join("sub")).unwrap();
        write_fixture(
            &dir,
            "b.rpy",
            "translate french b_id:\n    # e \"B\"\n    e \"\"\n",
        );
        write_fixture(
            &dir.join("sub"),
            "a.rpy",
            "translate french a_id:\n    # e \"A\"\n    e \"\"\n",
        );
        write_fixture(&dir, "not_rpy.txt", "ignored");

        let blocks = parse_directory(&dir).unwrap();
        assert_eq!(blocks.len(), 2);
    }

    #[test]
    fn missing_file_is_a_parse_error() {
        let missing = std::env::temp_dir().join("rts-parser-does-not-exist.rpy");
        assert!(parse_file(&missing).is_err());
    }
}
