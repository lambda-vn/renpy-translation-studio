//! Translation quality checks applied before validation.
//!
//! Port of `core/translation/quality.py`. `QualityIssue.detail` carries
//! the raw matched text (a tag, a `[var]`, an HTML tag, or a length
//! percentage) rather than a localized sentence: the core stays free of
//! UI strings, and whatever frontend eventually consumes this formats
//! `detail` through its own i18n, keyed on `kind`.
//!
//! `extra_var` is the one check CLAUDE.md calls non-negotiable: Ren'Py
//! evaluates the contents of `[...]` as a Python expression, so an
//! interpolation a translation adds that the source did not have is code
//! the shipped game will run. It is refused, not warned about — the
//! caller decides what "refused" means (`has_blocking_issue`).

use std::collections::HashSet;
use std::sync::LazyLock;

use regex::Regex;

pub const LENGTH_WARNING_KIND: &str = "length_warning";

static TAG_PATTERN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\{/?[a-z]+[^}]*\}").unwrap());
static VAR_PATTERN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\[[^\]]+\]").unwrap());
static HTMLTAG_PATTERN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"<[a-zA-Z/][^<>]*>").unwrap());

const LENGTH_RATIO_THRESHOLD: f64 = 1.3;
const MIN_LENGTH_DIFF_FOR_WARNING: i64 = 15;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QualityIssue {
    pub kind: &'static str,
    pub detail: String,
}

/// Remove every Ren'Py text tag (`{b}`, `{w=0.5}`, ...) from `text`.
///
/// Used by `translation::job::needs_translation()` to tell tag-only
/// content (a tag-wrapped ellipsis like `"...{w=0.5}"`) from text a
/// player actually reads.
pub fn strip_tags(text: &str) -> String {
    TAG_PATTERN.replace_all(text, "").into_owned()
}

/// Whether a translation carries a problem that blocks it.
///
/// Everything `check()` reports counts except the length warning, which
/// blocks nothing: a translation running long is a suspicion, and
/// counting it here would drown the tag and interpolation problems it
/// shares the list with.
pub fn has_blocking_issue(source: &str, translation: &str) -> bool {
    check(source, translation)
        .iter()
        .any(|issue| issue.kind != LENGTH_WARNING_KIND)
}

/// Run all quality checks between source and translation.
///
/// See the module docs and CLAUDE.md's "interpolations sont du code
/// Python" note for why `extra_var` exists and must not be softened.
pub fn check(source: &str, translation: &str) -> Vec<QualityIssue> {
    let mut issues = Vec::new();

    let source_tags: HashSet<&str> = TAG_PATTERN.find_iter(source).map(|m| m.as_str()).collect();
    let translation_tags: HashSet<&str> = TAG_PATTERN
        .find_iter(translation)
        .map(|m| m.as_str())
        .collect();
    for tag in sorted(source_tags.difference(&translation_tags)) {
        issues.push(QualityIssue {
            kind: "missing_tag",
            detail: tag.to_string(),
        });
    }
    for tag in sorted(translation_tags.difference(&source_tags)) {
        issues.push(QualityIssue {
            kind: "extra_tag",
            detail: tag.to_string(),
        });
    }

    let source_vars: HashSet<&str> = VAR_PATTERN.find_iter(source).map(|m| m.as_str()).collect();
    let translation_vars: HashSet<&str> = VAR_PATTERN
        .find_iter(translation)
        .map(|m| m.as_str())
        .collect();
    for var in sorted(source_vars.difference(&translation_vars)) {
        issues.push(QualityIssue {
            kind: "missing_var",
            detail: var.to_string(),
        });
    }
    for var in sorted(translation_vars.difference(&source_vars)) {
        issues.push(QualityIssue {
            kind: "extra_var",
            detail: var.to_string(),
        });
    }

    let source_html: HashSet<&str> = HTMLTAG_PATTERN
        .find_iter(source)
        .map(|m| m.as_str())
        .collect();
    let translation_html: HashSet<&str> = HTMLTAG_PATTERN
        .find_iter(translation)
        .map(|m| m.as_str())
        .collect();
    for tag in sorted(translation_html.difference(&source_html)) {
        issues.push(QualityIssue {
            kind: "unexpected_html",
            detail: tag.to_string(),
        });
    }

    // Python's len() on str counts Unicode code points, not bytes —
    // chars().count() is the faithful match; translation.len() would
    // over-count every non-ASCII character and drift from the Python
    // application on any accented or CJK text.
    let source_len = source.chars().count() as i64;
    let translation_len = translation.chars().count() as i64;
    let length_diff = translation_len - source_len;
    if !source.is_empty()
        && length_diff >= MIN_LENGTH_DIFF_FOR_WARNING
        && translation_len as f64 > source_len as f64 * LENGTH_RATIO_THRESHOLD
    {
        let percent = (length_diff as f64 / source_len as f64 * 100.0).round() as i64;
        issues.push(QualityIssue {
            kind: LENGTH_WARNING_KIND,
            detail: format!("{percent}%"),
        });
    }

    issues
}

fn sorted<'a>(items: impl Iterator<Item = &'a &'a str>) -> Vec<&'a str> {
    let mut items: Vec<&str> = items.copied().collect();
    items.sort_unstable();
    items
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kinds(issues: &[QualityIssue]) -> Vec<&str> {
        issues.iter().map(|i| i.kind).collect()
    }

    #[test]
    fn identical_text_has_no_issues() {
        assert!(check("Hello [name]!", "Hello [name]!").is_empty());
    }

    #[test]
    fn missing_tag_is_reported() {
        let issues = check("Click {b}here{/b}.", "Click here.");
        assert_eq!(kinds(&issues), vec!["missing_tag", "missing_tag"]);
    }

    #[test]
    fn extra_var_is_reported_and_blocking() {
        let issues = check("Hello.", "Hello [player_name].");
        assert_eq!(kinds(&issues), vec!["extra_var"]);
        assert!(has_blocking_issue("Hello.", "Hello [player_name]."));
    }

    #[test]
    fn missing_var_is_reported_and_blocking() {
        let issues = check("Hello [name].", "Hello.");
        assert_eq!(kinds(&issues), vec!["missing_var"]);
        assert!(has_blocking_issue("Hello [name].", "Hello."));
    }

    #[test]
    fn unexpected_html_is_reported() {
        let issues = check("Bold text.", "<b>Bold</b> text.");
        assert_eq!(kinds(&issues), vec!["unexpected_html", "unexpected_html"]);
    }

    #[test]
    fn long_translation_warns_but_does_not_block() {
        let source = "Back";
        let translation = "Return to the previous screen now";
        let issues = check(source, translation);
        assert_eq!(kinds(&issues), vec![LENGTH_WARNING_KIND]);
        assert!(!has_blocking_issue(source, translation));
    }

    #[test]
    fn short_ratio_blowup_is_not_a_warning() {
        // "Retour" is 50% longer than "Back" by ratio, but only 2
        // characters — under MIN_LENGTH_DIFF_FOR_WARNING.
        assert!(check("Back", "Retour").is_empty());
    }

    #[test]
    fn length_check_counts_unicode_codepoints_not_bytes() {
        // Each "é" is 2 bytes in UTF-8 but 1 codepoint: a byte-based
        // length check would over-count this and misfire.
        let source = "café";
        let translation = "café au lait, bien chaud";
        let issues = check(source, translation);
        assert_eq!(kinds(&issues), vec![LENGTH_WARNING_KIND]);
    }

    #[test]
    fn empty_source_never_warns_on_length() {
        assert!(check("", "some long translation appearing from nowhere").is_empty());
    }

    #[test]
    fn strip_tags_removes_renpy_markup_only() {
        assert_eq!(strip_tags("...{w=0.5}"), "...");
        assert_eq!(strip_tags("{i}Hello{/i} [name]"), "Hello [name]");
        assert_eq!(strip_tags("no tags here"), "no tags here");
    }
}
