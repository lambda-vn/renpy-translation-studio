//! Translation logic: quality checks, LLM prompt building, and the
//! providers that send text out for translation. Port of
//! `core/translation/`. `job.py` (the background job engine) and
//! `universe_generator.py` are not ported here — job orchestration is
//! `2.0.0-alpha.3`.

pub mod context_builder;
pub mod providers;
pub mod quality;
