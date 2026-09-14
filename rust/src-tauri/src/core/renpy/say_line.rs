//! Locating the spoken string inside a Ren'Py say statement.
//!
//! Port of `core/renpy/say_line.py`. A say statement is not just a
//! quoted string on a line — it can carry a speaker, image attributes,
//! a transition, an id or keyword arguments:
//!
//! ```text
//! e "Hello"
//! MC happy "Hello"
//! "Store clerk" "Not so fast!" with hpunch
//! e "Hello" (what_color="#fff")
//! ```
//!
//! Both the parser, which reads the statement, and the eventual writer,
//! which puts a translation back into it, have to agree on which quoted
//! string is the one a translator sees — this module is that single
//! answer.
//!
//! Every scan here works over `Vec<char>` rather than byte-indexed
//! `&str` slicing: Python's indices are Unicode codepoints, and a
//! speaker name or a translated line can carry non-ASCII text, so a
//! byte-indexed port would panic or misalign on the very first accented
//! character.

const HEAD_TOKEN_EXTRA: [char; 2] = ['@', '.'];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SayLine {
    /// Everything before the opening quote, verbatim: indentation, the
    /// speaker and its image attributes.
    pub prefix: String,
    /// The spoken string, still escaped as it appears in the file.
    pub text: String,
    /// Everything after the closing quote, verbatim: a `with` clause, an
    /// id, keyword arguments, the line break.
    pub suffix: String,
    /// The character variable the line is attributed to, `None` for
    /// narration.
    pub who: Option<String>,
}

fn skip_spaces(chars: &[char], start: usize) -> usize {
    let mut index = start;
    while index < chars.len() && (chars[index] == ' ' || chars[index] == '\t') {
        index += 1;
    }
    index
}

fn end_of_token(chars: &[char], start: usize) -> usize {
    let mut index = start;
    while index < chars.len()
        && (chars[index].is_alphanumeric()
            || chars[index] == '_'
            || HEAD_TOKEN_EXTRA.contains(&chars[index]))
    {
        index += 1;
    }
    index
}

/// The index just past a double-quoted string literal starting at
/// `start`, or `None` when it runs to the end of the line unterminated.
fn end_of_literal(chars: &[char], start: usize) -> Option<usize> {
    let mut index = start + 1;
    while index < chars.len() {
        match chars[index] {
            '\\' => index += 2,
            '"' => return Some(index + 1),
            '\r' | '\n' => return None,
            _ => index += 1,
        }
    }
    None
}

fn resolve_who(prefix: &str, quoted_speaker: Option<&str>) -> Option<String> {
    if let Some(speaker) = quoted_speaker {
        return Some(speaker.to_string());
    }
    let name = prefix.split_whitespace().next()?;
    let stripped: String = name.chars().filter(|&c| c != '_').collect();
    if !stripped.is_empty() && stripped.chars().all(char::is_alphanumeric) {
        Some(name.to_string())
    } else {
        None
    }
}

/// Split a say statement around the string a translation replaces.
///
/// The spoken string is the last quoted literal of the statement head,
/// the head being what stands before the first thing that is neither a
/// speaker token nor a literal. A quoted speaker is only recognized when
/// nothing precedes it.
///
/// Returns `None` when the line holds no usable string: blank, not a
/// say statement, an unterminated literal, or a `"""` opening a
/// multiline block (whose spoken text is not on this line at all).
pub fn split_say_line(line: &str) -> Option<SayLine> {
    let chars: Vec<char> = line.chars().collect();
    let mut literals: Vec<(usize, usize)> = Vec::new();
    let mut named_speaker = false;
    let mut index = skip_spaces(&chars, 0);

    while index < chars.len() {
        if chars[index] == '"' {
            let end = end_of_literal(&chars, index)?;
            literals.push((index, end));
            if named_speaker || literals.len() == 2 {
                break;
            }
            index = skip_spaces(&chars, end);
            continue;
        }
        if !literals.is_empty() {
            break;
        }
        let token_end = end_of_token(&chars, index);
        if token_end == index {
            return None;
        }
        named_speaker = true;
        index = skip_spaces(&chars, token_end);
    }

    let (start, end) = *literals.last()?;
    if chars.get(end) == Some(&'"') {
        return None;
    }
    let quoted_speaker = if literals.len() == 2 {
        let (s0, e0) = literals[0];
        Some(chars[s0 + 1..e0 - 1].iter().collect::<String>())
    } else {
        None
    };
    let prefix: String = chars[..start].iter().collect();
    let text: String = chars[start + 1..end - 1].iter().collect();
    let suffix: String = chars[end..].iter().collect();
    let who = resolve_who(&prefix, quoted_speaker.as_deref());

    Some(SayLine {
        prefix,
        text,
        suffix,
        who,
    })
}

/// Whether a line's first string literal opens with three double quotes
/// — the start of a triple-quoted statement whose text is not on this
/// line.
fn opens_multiline(line: &str) -> bool {
    let chars: Vec<char> = line.chars().collect();
    match chars.iter().position(|&c| c == '"') {
        Some(idx) => chars.get(idx..idx + 3) == Some(&['"', '"', '"'][..]),
        None => false,
    }
}

/// The body of the translate block whose header precedes `start`:
/// everything written under it, blank lines and comments included, up
/// to the first line standing in column one.
pub fn block_lines(lines: &[String], start: usize) -> &[String] {
    let mut end = start;
    while end < lines.len() {
        let line = &lines[end];
        let indented = matches!(line.chars().next(), Some(' ') | Some('\t'));
        if line.trim().is_empty() || indented {
            end += 1;
        } else {
            break;
        }
    }
    &lines[start..end]
}

/// Locate the say statement among the lines of one translate block.
///
/// A block is not always a single statement: Ren'Py groups with a line
/// of dialogue what belongs to it (a `voice`, an `nvl clear`), commented
/// then live, the say statement last. Returns the index of the *last*
/// matching line and its split form, or `None` when the block holds no
/// say statement, or opens a multiline literal whose text this cannot
/// point at.
pub fn find_say(lines: &[String]) -> Option<(usize, SayLine)> {
    let mut found = None;
    for (index, line) in lines.iter().enumerate() {
        if opens_multiline(line) {
            return None;
        }
        if let Some(say) = split_say_line(line) {
            found = Some((index, say));
        }
    }
    found
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lines(raw: &[&str]) -> Vec<String> {
        raw.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn plain_narration() {
        let say = split_say_line(r#"    "Hello""#).unwrap();
        assert_eq!(say.text, "Hello");
        assert_eq!(say.who, None);
    }

    #[test]
    fn variable_speaker() {
        let say = split_say_line(r#"    e "Hello""#).unwrap();
        assert_eq!(say.text, "Hello");
        assert_eq!(say.who.as_deref(), Some("e"));
    }

    #[test]
    fn speaker_with_image_attributes() {
        let say = split_say_line(r#"    MC happy "Hello""#).unwrap();
        assert_eq!(say.text, "Hello");
        assert_eq!(say.who.as_deref(), Some("MC"));
        assert_eq!(say.prefix, "    MC happy ");
    }

    #[test]
    fn quoted_speaker() {
        let say = split_say_line(r#"    "Store clerk" "Not so fast!" with hpunch"#).unwrap();
        assert_eq!(say.text, "Not so fast!");
        assert_eq!(say.who.as_deref(), Some("Store clerk"));
        assert_eq!(say.suffix, " with hpunch");
    }

    #[test]
    fn keyword_arguments_suffix() {
        let say = split_say_line(r##"    e "Hello" (what_color="#fff")"##).unwrap();
        assert_eq!(say.text, "Hello");
        assert_eq!(say.suffix, r##" (what_color="#fff")"##);
    }

    #[test]
    fn blank_line_has_no_say() {
        assert_eq!(split_say_line("    "), None);
        assert_eq!(split_say_line(""), None);
    }

    #[test]
    fn non_say_statement_has_no_say() {
        assert_eq!(split_say_line("    jump start"), None);
    }

    #[test]
    fn unterminated_literal_is_none() {
        assert_eq!(split_say_line(r#"    e "Hello"#), None);
    }

    #[test]
    fn adjacent_string_after_literal_is_rejected() {
        // Guards against misreading a statement with three literals in a
        // row as a valid two-literal (speaker, text) statement.
        assert_eq!(split_say_line(r#"    "a" "b""c""#), None);
    }

    #[test]
    fn underscore_only_prefix_has_no_speaker() {
        let say = split_say_line(r#"    ___ "Hello""#).unwrap();
        assert_eq!(say.who, None);
    }

    #[test]
    fn accented_speaker_variable_is_read_correctly() {
        let say = split_say_line(r#"    François "Bonjour""#).unwrap();
        assert_eq!(say.text, "Bonjour");
        assert_eq!(say.who.as_deref(), Some("François"));
    }

    #[test]
    fn opens_multiline_is_detected() {
        assert!(opens_multiline(r#"    e """"#));
        assert!(!opens_multiline(r#"    e "Hello""#));
    }

    #[test]
    fn find_say_skips_voice_and_picks_dialogue_last() {
        let block = lines(&[r#"    voice "v/e01.ogg""#, r#"    e "Hello""#]);
        let (index, say) = find_say(&block).unwrap();
        assert_eq!(index, 1);
        assert_eq!(say.text, "Hello");
    }

    #[test]
    fn find_say_returns_none_for_multiline_block() {
        let block = lines(&[r#"    e """"#, "    Some long text.", r#"    """"#]);
        assert_eq!(find_say(&block), None);
    }

    #[test]
    fn block_lines_stops_at_column_one() {
        let all = lines(&[
            "    # comment",
            r#"    e "Hello""#,
            "translate french strings:",
        ]);
        assert_eq!(block_lines(&all, 0), &all[0..2]);
    }
}
