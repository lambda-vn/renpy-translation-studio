//! Builds structured LLM prompts for translation with surrounding
//! context. Port of `core/translation/context_builder.py`.
//!
//! CLAUDE.md is explicit: the prompt text here and the JSON response
//! schema in `providers::ollama` encode hard-won workarounds for small
//! quantized model bugs, and must not be "improved" or paraphrased
//! without a real test against a small model. Every string in
//! `build_system_prompt` and `build_batch_prompt` is copied verbatim
//! from the Python original, not re-derived from its English meaning.

use crate::core::storage::repositories::Character;

const TOKENS_PER_CHAR_ESTIMATE: f64 = 0.25;
const OUTPUT_MARGIN_RATIO: f64 = 0.20;
pub const MAX_UNITS_PER_BATCH: usize = 8;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContextualUnit {
    pub block_id: String,
    pub source_text: String,
    pub character_variable: Option<String>,
    pub prev_text: Option<String>,
    pub next_text: Option<String>,
}

/// Estimate token count using a conservative character-based heuristic.
///
/// Intentionally imprecise — the `truncate=false` safety net in the
/// Ollama request handles cases where the real count exceeds budget.
pub fn estimate_tokens(text: &str) -> i64 {
    ((text.chars().count() as f64) * TOKENS_PER_CHAR_ESTIMATE)
        .floor()
        .max(1.0) as i64
}

/// Build the static system prompt injected before every batch request.
pub fn build_system_prompt(
    universe_summary: Option<&str>,
    characters: &[Character],
    source_lang: &str,
    target_lang: &str,
) -> String {
    let mut parts: Vec<String> = vec![
        format!(
            "You are a visual novel translator. Translate from {source_lang} to {target_lang}."
        ),
        "The source text can contain Ren'Py text tags: any token wrapped \
         in curly braces, such as {b}, {i}, {u}, {w}, {nw}, {p}, {fast}, \
         {a=...}...{/a}, {color=...}...{/color}, {size=+10}. They control \
         timing, pauses, styling and links in the game engine and are \
         never part of the sentence itself. Copy every {tag} found in the \
         source into the translation verbatim, in the same relative \
         position, even for tag names you don't recognize."
            .to_string(),
        "Preserve all Python interpolations ([variable_name]) exactly as they appear.".to_string(),
        "When the source text stutters or hesitates (e.g. \"W-what?\", \
         \"Sl..ow d..own\", \"I... I don't know\"), translate the intended \
         sentence and reproduce an equivalent stutter or hesitation on the \
         corresponding words in the target language."
            .to_string(),
        "Never use HTML tags (such as <a>, <h1>, <p>) — Ren'Py does not \
         use HTML markup, only the {tag} syntax shown above."
            .to_string(),
        "Return ONLY a JSON array: [{\"block_id\": \"...\", \"translation\": \"...\"}]".to_string(),
        "Do not add explanations or wrap in markdown code blocks.".to_string(),
    ];

    if let Some(summary) = universe_summary.filter(|s| !s.is_empty()) {
        parts.push(format!("\nUniverse context:\n{summary}"));
    }
    if !characters.is_empty() {
        let glossary = characters
            .iter()
            .map(|c| {
                let notes = c.notes.as_deref().filter(|n| !n.is_empty());
                match notes {
                    Some(notes) => format!("- {} ({}): {}", c.variable, c.display_name, notes),
                    None => format!("- {} ({})", c.variable, c.display_name),
                }
            })
            .collect::<Vec<_>>()
            .join("\n");
        parts.push(format!("\nCharacters:\n{glossary}"));
    }

    parts.join("\n\n")
}

/// Build the user message for a batch of translation units.
pub fn build_batch_prompt(units: &[ContextualUnit]) -> String {
    units
        .iter()
        .map(|unit| {
            let mut entry = vec![format!("block_id: {}", unit.block_id)];
            if let Some(prev) = unit.prev_text.as_deref().filter(|s| !s.is_empty()) {
                entry.push(format!("context_before: {prev}"));
            }
            if let Some(who) = unit.character_variable.as_deref().filter(|s| !s.is_empty()) {
                entry.push(format!("speaker: {who}"));
            }
            entry.push(format!("source: {}", unit.source_text));
            if let Some(next) = unit.next_text.as_deref().filter(|s| !s.is_empty()) {
                entry.push(format!("context_after: {next}"));
            }
            entry.join("\n")
        })
        .collect::<Vec<_>>()
        .join("\n\n---\n\n")
}

/// Split units into batches that fit within the model's context window.
///
/// Reserves [`OUTPUT_MARGIN_RATIO`] of the context window for the
/// output, and uses the system prompt's token count as a fixed overhead
/// per batch. Also caps each batch at `max_units` regardless of
/// remaining token budget: smaller LLMs reliably follow the
/// structured-JSON-array instruction for a handful of units but tend to
/// drop most of a large batch even when it fits comfortably, and are
/// most likely to attach a translation to the wrong `block_id` on a
/// batch of short, similar labels — keeping batches small reduces how
/// many easily-confused items a model has to keep straight at once.
pub fn split_into_batches(
    units: &[ContextualUnit],
    system_prompt: &str,
    num_ctx: i64,
    max_units: usize,
) -> Vec<Vec<ContextualUnit>> {
    let output_margin = ((num_ctx as f64) * OUTPUT_MARGIN_RATIO) as i64;
    let system_tokens = estimate_tokens(system_prompt);
    let available = num_ctx - system_tokens - output_margin;

    let mut batches: Vec<Vec<ContextualUnit>> = Vec::new();
    let mut current_batch: Vec<ContextualUnit> = Vec::new();
    let mut current_tokens: i64 = 0;

    for unit in units {
        let unit_text = build_batch_prompt(std::slice::from_ref(unit));
        let unit_tokens = estimate_tokens(&unit_text);

        if !current_batch.is_empty()
            && (current_tokens + unit_tokens > available || current_batch.len() >= max_units)
        {
            batches.push(std::mem::take(&mut current_batch));
            current_tokens = 0;
        }

        current_batch.push(unit.clone());
        current_tokens += unit_tokens;
    }

    if !current_batch.is_empty() {
        batches.push(current_batch);
    }

    batches
}

#[cfg(test)]
mod tests {
    use super::*;

    fn character(variable: &str, display_name: &str, notes: Option<&str>) -> Character {
        Character {
            id: 1,
            variable: variable.to_string(),
            display_name: display_name.to_string(),
            notes: notes.map(str::to_string),
        }
    }

    fn unit(block_id: &str, source: &str) -> ContextualUnit {
        ContextualUnit {
            block_id: block_id.to_string(),
            source_text: source.to_string(),
            character_variable: None,
            prev_text: None,
            next_text: None,
        }
    }

    #[test]
    fn system_prompt_names_languages() {
        let prompt = build_system_prompt(None, &[], "english", "french");
        assert!(prompt
            .starts_with("You are a visual novel translator. Translate from english to french."));
        assert!(!prompt.contains("Universe context"));
        assert!(!prompt.contains("Characters:"));
    }

    #[test]
    fn system_prompt_includes_universe_and_glossary_when_present() {
        let characters = vec![
            character("e", "Eileen", Some("narrator")),
            character("m", "Marissa", None),
        ];
        let prompt = build_system_prompt(Some("A fantasy world."), &characters, "en", "fr");
        assert!(prompt.contains("\nUniverse context:\nA fantasy world."));
        assert!(prompt.contains("- e (Eileen): narrator"));
        assert!(prompt.contains("- m (Marissa)"));
        assert!(!prompt.contains("- m (Marissa):"));
    }

    #[test]
    fn batch_prompt_includes_context_only_when_present() {
        let mut u = unit("a", "Hello.");
        u.prev_text = Some("Once upon a time.".to_string());
        u.character_variable = Some("e".to_string());
        let prompt = build_batch_prompt(&[u]);
        assert_eq!(
            prompt,
            "block_id: a\ncontext_before: Once upon a time.\nspeaker: e\nsource: Hello."
        );
    }

    #[test]
    fn batch_prompt_joins_multiple_units_with_separator() {
        let prompt = build_batch_prompt(&[unit("a", "Hi."), unit("b", "Bye.")]);
        assert_eq!(
            prompt,
            "block_id: a\nsource: Hi.\n\n---\n\nblock_id: b\nsource: Bye."
        );
    }

    #[test]
    fn split_into_batches_respects_max_units() {
        let units: Vec<ContextualUnit> = (0..20).map(|i| unit(&i.to_string(), "short")).collect();
        let system_prompt = "system";
        let batches = split_into_batches(&units, system_prompt, 8192, MAX_UNITS_PER_BATCH);
        assert!(batches.iter().all(|b| b.len() <= MAX_UNITS_PER_BATCH));
        assert_eq!(batches.iter().map(Vec::len).sum::<usize>(), 20);
    }

    #[test]
    fn split_into_batches_respects_token_budget_over_a_tiny_context() {
        let long_text = "word ".repeat(200);
        let units = vec![unit("a", &long_text), unit("b", &long_text)];
        // A tiny context window can't fit two of these in one batch even
        // though max_units alone would allow it.
        let batches = split_into_batches(&units, "sys", 100, MAX_UNITS_PER_BATCH);
        assert!(batches.len() >= 2);
    }

    #[test]
    fn split_into_batches_never_produces_an_empty_batch() {
        let units = vec![unit("a", "x")];
        let batches = split_into_batches(&units, "sys", 8192, MAX_UNITS_PER_BATCH);
        assert_eq!(batches.len(), 1);
        assert_eq!(batches[0].len(), 1);
    }
}
