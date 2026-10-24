//! Reading and writing Ren'Py's own generated translation files. Port
//! of `core/renpy/` — parser and writer only; the extraction subprocess
//! wrapper (`cli.py`, `engine.py`) belongs to a later phase, `beta.2`
//! scoping the Rust app to projects already extracted elsewhere.

pub mod parser;
pub mod say_line;
pub mod writer;
