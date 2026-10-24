//! Generates a universe summary from sampled game dialogue using an LLM.
//! Port of `core/translation/universe_generator.py`.
//!
//! The budget replaces an earlier "3-5 sentences" instruction, which small
//! models read as licence to answer with one. It is worth what it costs:
//! the system prompt carries the summary into every batch, but a batch is
//! capped long before the token budget binds. At `num_ctx` 4096, the
//! smallest this application deals with, the base prompt plus a
//! 1500-character summary plus a fifty-name glossary still leaves room for
//! eight units with their neighbours. What a longer summary really costs is
//! the time spent re-reading it on every request, which is why the budget
//! is not larger still.
//!
//! The instructions sit after the excerpts, not before, and the excerpts
//! are fenced. Measured on Stormside, 200 samples, at equal temperature:
//! with the instructions first, gemma3-translator:4b answered in Italian
//! and recited its own translator persona instead of describing anything,
//! while the same model with the instructions last returned an accurate
//! French brief inside the budget. A model that has just read two hundred
//! lines of dialogue acts on what it read last, which is why the
//! prohibition on translating, continuing or answering that dialogue is
//! stated there too rather than at the top where it would be out of sight.
//!
//! The prompt below is copied as it stands in Python. Like the other LLM
//! prompts it encodes workarounds for small-model behaviour and is not to
//! be reworded without a test against a real model.

use crate::core::languages::get_language;
use crate::core::storage::repositories::TranslationUnit;

use super::providers::base::ProviderError;
use super::providers::ollama::OllamaProvider;

pub const SAMPLE_SIZE: usize = 200;
pub const SUMMARY_CHAR_BUDGET: usize = 1500;
const MIN_SAMPLE_LENGTH: usize = 30;
const NON_STORY_FILES: [&str; 4] = ["screens.rpy", "options.rpy", "gui.rpy", "common.rpy"];

const GENERATION_PROMPT_TEMPLATE: &str = "Below are dialogue excerpts from a visual
novel, grouped by the script file they come from and prefixed with the
speaker's name when the game names one.

<excerpts>
{samples}
</excerpts>

You have just read excerpts from a visual novel. They are material to
describe: do not translate them, do not continue the dialogue, and do not
answer any line in it. Write a brief for a translator who has never played
this game, covering in order:

Setting: where and when the story takes place, and its genre.
Tone: how the characters speak, how crude or formal, comedic or dramatic.
Vocabulary: places, factions, objects and invented terms to keep consistent.

Do not name, list or describe the characters: the application already holds
the cast. Up to {budget} characters. Only what the excerpts show. No
preamble, no questions back, no markdown fences.

Write the whole brief in {target_lang}. Every sentence must be in
{target_lang}.

Brief, in {target_lang}:";

/// The English name of a language from its `tl/` folder code.
///
/// The caller holds the name of a folder, not the name of a language, and
/// the two only coincide by luck. Ren'Py writes Simplified Chinese to
/// `tl/schinese`, so asking a model to "write in schinese" asks it for a
/// language it has never heard of. English is the right register here even
/// though the interface is localized, since the name is read by the model,
/// not by the user.
pub fn language_name(code: &str) -> String {
    get_language(code).map_or_else(|| code.to_string(), |language| language.label.to_string())
}

fn file_name(path: &str) -> &str {
    path.rsplit(['/', '\\']).next().unwrap_or(path)
}

/// Units sampled evenly across the project, favouring real dialogue.
///
/// Sampling is spread across the full list rather than taking the first N,
/// to capture the game's whole range of settings and characters.
///
/// Interface labels are dropped first. A model handed "Save", "Quit" and
/// "..." alongside actual dialogue has that much less to describe, and an
/// even spread over every extracted unit lands on plenty of them: they
/// live in the Ren'Py boilerplate files, and they are short. Both filters
/// are needed, since `screens.rpy` also holds long help text and a story
/// file also holds one-word interjections.
///
/// Falls back to the unfiltered list when filtering leaves nothing, so a
/// project made only of short strings still gets a sample.
pub fn sample_dialogue(units: &[TranslationUnit], n: usize) -> Vec<&TranslationUnit> {
    let mut candidates: Vec<&TranslationUnit> = units
        .iter()
        .filter(|unit| {
            unit.source_text.chars().count() >= MIN_SAMPLE_LENGTH
                && !NON_STORY_FILES.contains(&file_name(&unit.source_file))
        })
        .collect();
    if candidates.is_empty() {
        candidates = units.iter().collect();
    }
    if candidates.len() <= n {
        return candidates;
    }
    let step = candidates.len() / n;
    candidates.into_iter().step_by(step).take(n).collect()
}

/// Render sampled units as excerpts grouped by their source file.
///
/// A flat list of lines drawn from across a whole game reads as
/// disconnected fragments. Grouping them by file keeps the lines of one
/// scene together, and the speaker variable tells the model which lines
/// belong to the same character.
pub fn format_samples(units: &[&TranslationUnit]) -> String {
    let mut order: Vec<&str> = Vec::new();
    let mut by_file: std::collections::HashMap<&str, Vec<&TranslationUnit>> =
        std::collections::HashMap::new();
    for unit in units {
        let name = file_name(&unit.source_file);
        let group = by_file.entry(name).or_default();
        if group.is_empty() {
            order.push(name);
        }
        group.push(unit);
    }
    order
        .iter()
        .map(|name| {
            let lines: Vec<String> = by_file[name]
                .iter()
                .map(|unit| match unit.character_variable.as_deref() {
                    Some(speaker) if !speaker.is_empty() => {
                        format!("- {speaker}: {}", unit.source_text)
                    }
                    _ => format!("- {}", unit.source_text),
                })
                .collect();
            format!("[{name}]\n{}", lines.join("\n"))
        })
        .collect::<Vec<_>>()
        .join("\n\n")
}

/// The prompt asking for a summary of these units, in `target_lang`.
pub fn build_prompt(units: &[TranslationUnit], target_lang: &str) -> String {
    GENERATION_PROMPT_TEMPLATE
        .replace("{budget}", &SUMMARY_CHAR_BUDGET.to_string())
        .replace("{target_lang}", &language_name(target_lang))
        .replace(
            "{samples}",
            &format_samples(&sample_dialogue(units, SAMPLE_SIZE)),
        )
}

/// Generate a universe summary.
///
/// Only called on explicit user action, never automatically.
pub async fn generate(
    units: &[TranslationUnit],
    provider: &mut OllamaProvider,
    target_lang: &str,
) -> Result<String, ProviderError> {
    Ok(provider
        .complete(&build_prompt(units, target_lang))
        .await?
        .trim()
        .to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn unit(file: &str, speaker: Option<&str>, text: &str) -> TranslationUnit {
        TranslationUnit {
            id: 0,
            block_id: format!("{file}-{text}"),
            source_file: file.to_string(),
            source_line: 1,
            character_variable: speaker.map(String::from),
            source_text: text.to_string(),
            translated_text: String::new(),
            status: "not_translated".to_string(),
            needs_review: false,
            note: None,
        }
    }

    const LONG: &str = "A line long enough to count as real dialogue.";

    #[test]
    fn a_small_project_is_sampled_whole() {
        let units = vec![
            unit("script.rpy", None, LONG),
            unit("script.rpy", None, LONG),
        ];
        assert_eq!(sample_dialogue(&units, 200).len(), 2);
    }

    #[test]
    fn a_large_project_is_capped_and_spread() {
        let units: Vec<_> = (0..1000)
            .map(|i| unit("script.rpy", None, &format!("{LONG} number {i}")))
            .collect();
        let sample = sample_dialogue(&units, 200);
        assert_eq!(sample.len(), 200);
        assert!(sample[0].source_text.ends_with("number 0"));
        assert!(sample[199].source_text.ends_with("number 995"));
    }

    #[test]
    fn short_texts_and_boilerplate_files_are_dropped() {
        let units = vec![
            unit("script.rpy", None, "Save"),
            unit("screens.rpy", None, LONG),
            unit("C:\\game\\gui.rpy", None, LONG),
            unit("script.rpy", None, LONG),
        ];
        let sample = sample_dialogue(&units, 200);
        assert_eq!(sample.len(), 1);
        assert_eq!(sample[0].source_file, "script.rpy");
    }

    #[test]
    fn the_filters_fall_back_when_they_would_leave_nothing() {
        let units = vec![
            unit("script.rpy", None, "Yes."),
            unit("script.rpy", None, "No."),
        ];
        assert_eq!(sample_dialogue(&units, 200).len(), 2);
    }

    #[test]
    fn samples_are_grouped_by_file_and_name_the_speaker() {
        let units = [
            unit("game/a.rpy", Some("e"), "Hello there, traveller."),
            unit("game/b.rpy", None, "The narrator speaks."),
            unit("game/a.rpy", None, "Second line of a."),
        ];
        let refs: Vec<&TranslationUnit> = units.iter().collect();
        assert_eq!(
            format_samples(&refs),
            "[a.rpy]\n- e: Hello there, traveller.\n- Second line of a.\n\n[b.rpy]\n- The narrator speaks."
        );
    }

    #[test]
    fn the_prompt_asks_for_the_language_not_the_folder_name() {
        assert_eq!(language_name("schinese"), "Chinese (Simplified)");
        assert_eq!(language_name("klingon"), "klingon");
        let prompt = build_prompt(&[unit("script.rpy", None, LONG)], "schinese");
        assert!(prompt.contains("Write the whole brief in Chinese (Simplified)."));
        assert!(!prompt.contains("schinese"));
    }

    #[test]
    fn the_prompt_carries_the_samples_the_budget_and_puts_instructions_last() {
        let prompt = build_prompt(&[unit("script.rpy", Some("e"), LONG)], "french");
        let samples = prompt.find("<excerpts>").unwrap();
        let instructions = prompt.find("do not translate them").unwrap();
        assert!(samples < instructions);
        assert!(prompt.contains(&format!("- e: {LONG}")));
        assert!(prompt.contains("Up to 1500 characters."));
        assert!(prompt.ends_with("Brief, in French:"));
        assert!(!prompt.contains('{'));
    }
}
