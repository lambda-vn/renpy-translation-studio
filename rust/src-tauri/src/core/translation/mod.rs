//! Translation logic: quality checks, LLM prompt building, and the
//! providers that send text out for translation.

pub mod context_builder;
pub mod job;
pub mod providers;
pub mod quality;
pub mod universe_generator;
