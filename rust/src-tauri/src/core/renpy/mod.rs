//! Reading Ren'Py's own generated translation files. Port of
//! `core/renpy/` — parser only; the extraction subprocess wrapper
//! (`cli.py`, `engine.py`) and the writer belong to a later phase.

pub mod parser;
pub mod say_line;
