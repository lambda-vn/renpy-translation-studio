//! Running Ren'Py and reading and writing its generated translation
//! files: the engine choice and subprocess wrapper (`engine`, `cli`), the
//! `.rpa` archive reader and unpacker, the parser and the writer.

pub mod archive;
pub mod character_detector;
pub mod cli;
pub mod engine;
pub mod parser;
pub mod say_line;
pub mod unpacker;
pub mod writer;
