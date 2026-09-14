//! Translation providers. Port of `core/translation/providers/`.
//!
//! No shared `TranslationProvider` trait yet — Python's is a structural
//! `Protocol`, checked at the call site rather than at definition, and
//! the registry that would need one here is job-engine territory
//! (`2.0.0-alpha.3`), not built yet. Each provider stands alone until
//! then.

pub mod base;
pub mod deepl;
pub mod libretranslate;
