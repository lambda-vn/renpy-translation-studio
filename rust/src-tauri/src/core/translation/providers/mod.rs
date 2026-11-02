//! Translation providers: DeepL, Ollama and LibreTranslate, plus the
//! registry that builds them from settings.

pub mod base;
pub mod deepl;
pub mod libretranslate;
pub mod ollama;
pub mod registry;
