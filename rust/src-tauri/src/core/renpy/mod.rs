//! Running Ren'Py and reading and writing its generated translation
//! files. Port of `core/renpy/`: the engine choice and subprocess wrapper
//! (`engine`, `cli`, ported in `rc.2`), the parser and the writer.

pub mod archive;
pub mod character_detector;
pub mod cli;
pub mod engine;
pub mod parser;
pub mod say_line;
pub mod unpacker;
pub mod writer;
