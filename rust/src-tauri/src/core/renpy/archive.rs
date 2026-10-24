//! Reader for Ren'Py `.rpa` archive files. Port of `core/renpy/archive.py`.
//!
//! An archive ends with a zlib-compressed Python pickle: its index. The
//! pickle is untrusted, so it is not run. [`pickle`] below understands the
//! few opcodes an index is made of (dicts, lists, tuples, strings, integers)
//! and refuses every other one, in particular anything that would resolve a
//! class or a function. A crafted payload therefore never reaches
//! `__reduce__` on an attacker-chosen callable, because nothing here can
//! call anything.

use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

use flate2::read::ZlibDecoder;

#[derive(Debug, thiserror::Error)]
pub enum ArchiveError {
    #[error("cannot read the archive: {0}")]
    Io(#[from] std::io::Error),
    #[error("Unsupported archive header: {0}")]
    UnsupportedHeader(String),
    #[error("Corrupt archive index: {0}")]
    CorruptIndex(String),
    #[error("Refused to unpickle {0}")]
    Refused(String),
    #[error("Malformed archive index entry: {0}")]
    MalformedEntry(String),
    #[error("Unsafe member name ({reason}): {name}")]
    UnsafeName { name: String, reason: &'static str },
    #[error("No such member in {archive}: {name}")]
    NoSuchMember { archive: String, name: String },
    #[error("Unsafe member path: {0}")]
    UnsafePath(String),
    #[error("{0}")]
    Manifest(String),
}

/// Validate an archive member name and normalize its separators.
///
/// Member names come straight from the archive's index, an untrusted third
/// party, so nothing here may be interpreted as an absolute path or a
/// traversal outside the extraction target.
pub fn validate_member_name(name: &str) -> Result<String, ArchiveError> {
    let normalized = name.replace('\\', "/");
    let refuse = |reason| ArchiveError::UnsafeName {
        name: name.to_string(),
        reason,
    };
    if normalized.starts_with('/') {
        return Err(refuse("absolute path"));
    }
    if normalized.as_bytes().get(1) == Some(&b':') {
        return Err(refuse("drive letter"));
    }
    if normalized.split('/').any(|part| part == "..") {
        return Err(refuse("path traversal"));
    }
    Ok(normalized)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArchiveMember {
    pub offset: u64,
    pub length: u64,
    pub prefix: Vec<u8>,
}

pub struct RpaArchive {
    path: PathBuf,
    file: File,
    names: Vec<String>,
    index: HashMap<String, ArchiveMember>,
}

impl RpaArchive {
    /// Open an `.rpa` archive and read its index.
    pub fn open(path: &Path) -> Result<Self, ArchiveError> {
        let mut file = File::open(path)?;
        let (names, index) = read_index(&mut file)?;
        Ok(Self {
            path: path.to_path_buf(),
            file,
            names,
            index,
        })
    }

    /// The archive-relative names of every member, in index order.
    pub fn names(&self) -> &[String] {
        &self.names
    }

    /// The raw bytes of a single member.
    pub fn read(&mut self, name: &str) -> Result<Vec<u8>, ArchiveError> {
        let member = self
            .index
            .get(name)
            .ok_or_else(|| ArchiveError::NoSuchMember {
                archive: self.path.display().to_string(),
                name: name.to_string(),
            })?
            .clone();
        let remaining = member
            .length
            .checked_sub(member.prefix.len() as u64)
            .ok_or_else(|| ArchiveError::MalformedEntry(name.to_string()))?;
        self.file.seek(SeekFrom::Start(member.offset))?;
        let mut data = member.prefix;
        (&mut self.file).take(remaining).read_to_end(&mut data)?;
        Ok(data)
    }
}

fn read_index(
    file: &mut File,
) -> Result<(Vec<String>, HashMap<String, ArchiveMember>), ArchiveError> {
    let mut reader = BufReader::new(&mut *file);
    let mut header_line = Vec::new();
    reader.read_until(b'\n', &mut header_line)?;
    while matches!(header_line.last(), Some(b'\n' | b'\r')) {
        header_line.pop();
    }
    let header = String::from_utf8(header_line.clone()).map_err(|_| {
        ArchiveError::UnsupportedHeader(String::from_utf8_lossy(&header_line).into_owned())
    })?;

    let parts: Vec<&str> = header.split_whitespace().collect();
    let unsupported = || ArchiveError::UnsupportedHeader(header.clone());
    let magic = parts.first().copied().unwrap_or("");
    let key_start = match magic {
        "RPA-2.0" => None,
        "RPA-3.0" => Some(2),
        "RPA-3.2" => Some(3),
        _ => return Err(unsupported()),
    };
    if parts.len() < 2 {
        return Err(unsupported());
    }
    let offset = u64::from_str_radix(parts[1], 16).map_err(|_| unsupported())?;
    let mut key: i128 = 0;
    if let Some(start) = key_start {
        for subkey in parts.iter().skip(start) {
            key ^= i128::from(u64::from_str_radix(subkey, 16).map_err(|_| unsupported())?);
        }
    }

    drop(reader);
    file.seek(SeekFrom::Start(offset))?;
    let mut compressed = Vec::new();
    file.read_to_end(&mut compressed)?;
    let mut decompressed = Vec::new();
    ZlibDecoder::new(compressed.as_slice())
        .read_to_end(&mut decompressed)
        .map_err(|e| ArchiveError::CorruptIndex(e.to_string()))?;
    let payload = pickle::load(&decompressed)?;
    normalize_index(payload, key)
}

fn normalize_index(
    payload: pickle::Value,
    key: i128,
) -> Result<(Vec<String>, HashMap<String, ArchiveMember>), ArchiveError> {
    let pickle::Value::Dict(pairs) = payload else {
        return Err(ArchiveError::CorruptIndex(
            "Archive index is not a dict".into(),
        ));
    };
    let mut names = Vec::with_capacity(pairs.len());
    let mut index = HashMap::with_capacity(pairs.len());
    for (name, entries) in pairs {
        let pickle::Value::Str(name) = name else {
            return Err(ArchiveError::MalformedEntry(format!("{name:?}")));
        };
        let malformed = || ArchiveError::MalformedEntry(name.clone());
        let pickle::Value::List(entries) = entries else {
            return Err(malformed());
        };
        let Some(pickle::Value::Tuple(entry)) = entries.into_iter().next() else {
            return Err(malformed());
        };
        if !(entry.len() == 2 || entry.len() == 3) {
            return Err(malformed());
        }
        let (pickle::Value::Int(mut offset), pickle::Value::Int(mut length)) =
            (entry[0].clone(), entry[1].clone())
        else {
            return Err(malformed());
        };
        let prefix = match entry.get(2) {
            None => Vec::new(),
            Some(pickle::Value::Str(text)) => text.chars().map(|c| c as u32 as u8).collect(),
            Some(pickle::Value::Bytes(bytes)) => bytes.clone(),
            Some(_) => return Err(ArchiveError::MalformedEntry(format!("prefix of {name}"))),
        };
        if key != 0 {
            offset ^= key;
            length ^= key;
        }
        let (Ok(offset), Ok(length)) = (u64::try_from(offset), u64::try_from(length)) else {
            return Err(malformed());
        };
        let name = validate_member_name(&name)?;
        names.push(name.clone());
        index.insert(
            name,
            ArchiveMember {
                offset,
                length,
                prefix,
            },
        );
    }
    Ok((names, index))
}

/// The subset of the pickle format an archive index uses.
pub mod pickle {
    use super::ArchiveError;

    #[derive(Debug, Clone, PartialEq)]
    pub enum Value {
        None,
        Bool(bool),
        Int(i128),
        Float(f64),
        Str(String),
        Bytes(Vec<u8>),
        List(Vec<Value>),
        Tuple(Vec<Value>),
        Dict(Vec<(Value, Value)>),
    }

    /// A stack slot: a value, or the marker an opcode like `(` leaves.
    enum Slot {
        Mark,
        Value(Value),
    }

    struct Cursor<'a> {
        data: &'a [u8],
        position: usize,
    }

    impl<'a> Cursor<'a> {
        fn take(&mut self, count: usize) -> Result<&'a [u8], ArchiveError> {
            let end = self
                .position
                .checked_add(count)
                .filter(|end| *end <= self.data.len())
                .ok_or_else(|| ArchiveError::CorruptIndex("truncated pickle".into()))?;
            let slice = &self.data[self.position..end];
            self.position = end;
            Ok(slice)
        }

        fn byte(&mut self) -> Result<u8, ArchiveError> {
            Ok(self.take(1)?[0])
        }

        fn le(&mut self, width: usize) -> Result<u64, ArchiveError> {
            let bytes = self.take(width)?;
            Ok(bytes
                .iter()
                .rev()
                .fold(0u64, |acc, byte| (acc << 8) | u64::from(*byte)))
        }

        fn length(&mut self, width: usize) -> Result<usize, ArchiveError> {
            usize::try_from(self.le(width)?)
                .map_err(|_| ArchiveError::CorruptIndex("pickle length overflow".into()))
        }

        fn line(&mut self) -> Result<&'a str, ArchiveError> {
            let rest = &self.data[self.position..];
            let end = rest
                .iter()
                .position(|b| *b == b'\n')
                .ok_or_else(|| ArchiveError::CorruptIndex("truncated pickle".into()))?;
            self.position += end + 1;
            std::str::from_utf8(&rest[..end])
                .map_err(|_| ArchiveError::CorruptIndex("pickle text is not UTF-8".into()))
        }
    }

    fn corrupt(message: &str) -> ArchiveError {
        ArchiveError::CorruptIndex(message.to_string())
    }

    fn signed_le(bytes: &[u8]) -> Result<i128, ArchiveError> {
        if bytes.len() > 16 {
            return Err(corrupt("integer too large"));
        }
        if bytes.is_empty() {
            return Ok(0);
        }
        let negative = bytes[bytes.len() - 1] & 0x80 != 0;
        let mut value: i128 = if negative { -1 } else { 0 };
        for byte in bytes.iter().rev() {
            value = (value << 8) | i128::from(*byte);
        }
        Ok(value)
    }

    /// Decode a pickle made only of plain containers and scalars.
    pub fn load(data: &[u8]) -> Result<Value, ArchiveError> {
        let mut cursor = Cursor { data, position: 0 };
        let mut stack: Vec<Slot> = Vec::new();
        let mut memo: Vec<Option<Value>> = Vec::new();

        fn pop_value(stack: &mut Vec<Slot>) -> Result<Value, ArchiveError> {
            match stack.pop() {
                Some(Slot::Value(value)) => Ok(value),
                _ => Err(corrupt("pickle stack underflow")),
            }
        }

        fn pop_to_mark(stack: &mut Vec<Slot>) -> Result<Vec<Value>, ArchiveError> {
            let mark = stack
                .iter()
                .rposition(|slot| matches!(slot, Slot::Mark))
                .ok_or_else(|| corrupt("pickle mark missing"))?;
            stack
                .split_off(mark + 1)
                .into_iter()
                .map(|slot| match slot {
                    Slot::Value(value) => Ok(value),
                    Slot::Mark => Err(corrupt("nested pickle mark")),
                })
                .collect::<Result<Vec<_>, _>>()
                .inspect(|_| {
                    stack.pop();
                })
        }

        fn remember(memo: &mut Vec<Option<Value>>, index: usize, value: Value) {
            if memo.len() <= index {
                memo.resize(index + 1, None);
            }
            memo[index] = Some(value);
        }

        fn recall(memo: &[Option<Value>], index: usize) -> Result<Value, ArchiveError> {
            memo.get(index)
                .cloned()
                .flatten()
                .ok_or_else(|| corrupt("pickle memo miss"))
        }

        fn set_items(target: &mut Value, items: Vec<Value>) -> Result<(), ArchiveError> {
            let Value::Dict(pairs) = target else {
                return Err(corrupt("SETITEMS on a non-dict"));
            };
            let mut items = items.into_iter();
            while let Some(key) = items.next() {
                let value = items.next().ok_or_else(|| corrupt("odd SETITEMS"))?;
                pairs.push((key, value));
            }
            Ok(())
        }

        loop {
            let opcode = cursor.byte()?;
            match opcode {
                b'.' => return pop_value(&mut stack),
                0x80 => {
                    cursor.byte()?;
                }
                0x95 => {
                    cursor.take(8)?;
                }
                b'(' => stack.push(Slot::Mark),
                b'N' => stack.push(Slot::Value(Value::None)),
                0x88 => stack.push(Slot::Value(Value::Bool(true))),
                0x89 => stack.push(Slot::Value(Value::Bool(false))),
                b'}' => stack.push(Slot::Value(Value::Dict(Vec::new()))),
                b']' => stack.push(Slot::Value(Value::List(Vec::new()))),
                b')' => stack.push(Slot::Value(Value::Tuple(Vec::new()))),
                b'd' => {
                    let items = pop_to_mark(&mut stack)?;
                    let mut dict = Value::Dict(Vec::new());
                    set_items(&mut dict, items)?;
                    stack.push(Slot::Value(dict));
                }
                b'l' => {
                    let items = pop_to_mark(&mut stack)?;
                    stack.push(Slot::Value(Value::List(items)));
                }
                b't' => {
                    let items = pop_to_mark(&mut stack)?;
                    stack.push(Slot::Value(Value::Tuple(items)));
                }
                0x85..=0x87 => {
                    let count = usize::from(opcode - 0x84);
                    let mut items = Vec::with_capacity(count);
                    for _ in 0..count {
                        items.push(pop_value(&mut stack)?);
                    }
                    items.reverse();
                    stack.push(Slot::Value(Value::Tuple(items)));
                }
                b's' => {
                    let value = pop_value(&mut stack)?;
                    let key = pop_value(&mut stack)?;
                    let Some(Slot::Value(target)) = stack.last_mut() else {
                        return Err(corrupt("SETITEM without a dict"));
                    };
                    set_items(target, vec![key, value])?;
                }
                b'u' => {
                    let items = pop_to_mark(&mut stack)?;
                    let Some(Slot::Value(target)) = stack.last_mut() else {
                        return Err(corrupt("SETITEMS without a dict"));
                    };
                    set_items(target, items)?;
                }
                b'a' => {
                    let item = pop_value(&mut stack)?;
                    let Some(Slot::Value(Value::List(list))) = stack.last_mut() else {
                        return Err(corrupt("APPEND without a list"));
                    };
                    list.push(item);
                }
                b'e' => {
                    let items = pop_to_mark(&mut stack)?;
                    let Some(Slot::Value(Value::List(list))) = stack.last_mut() else {
                        return Err(corrupt("APPENDS without a list"));
                    };
                    list.extend(items);
                }
                b'I' | b'L' => {
                    let text = cursor.line()?.trim_end_matches('L');
                    let value = match text {
                        "00" => Value::Bool(false),
                        "01" => Value::Bool(true),
                        number => {
                            Value::Int(number.parse::<i128>().map_err(|_| corrupt("bad integer"))?)
                        }
                    };
                    stack.push(Slot::Value(value));
                }
                b'J' => {
                    let value = cursor.le(4)? as u32 as i32;
                    stack.push(Slot::Value(Value::Int(i128::from(value))));
                }
                b'K' => {
                    let value = cursor.byte()?;
                    stack.push(Slot::Value(Value::Int(i128::from(value))));
                }
                b'M' => {
                    let value = cursor.le(2)?;
                    stack.push(Slot::Value(Value::Int(i128::from(value))));
                }
                0x8a => {
                    let length = usize::from(cursor.byte()?);
                    let value = signed_le(cursor.take(length)?)?;
                    stack.push(Slot::Value(Value::Int(value)));
                }
                0x8b => {
                    let length = cursor.length(4)?;
                    let value = signed_le(cursor.take(length)?)?;
                    stack.push(Slot::Value(Value::Int(value)));
                }
                b'F' => {
                    let value = cursor
                        .line()?
                        .parse::<f64>()
                        .map_err(|_| corrupt("bad float"))?;
                    stack.push(Slot::Value(Value::Float(value)));
                }
                b'G' => {
                    let bytes = cursor.take(8)?;
                    let mut array = [0u8; 8];
                    array.copy_from_slice(bytes);
                    stack.push(Slot::Value(Value::Float(f64::from_be_bytes(array))));
                }
                // Python 2 `str`, decoded as latin-1 like the Python reader.
                b'T' | b'U' => {
                    let length = if opcode == b'T' {
                        cursor.length(4)?
                    } else {
                        usize::from(cursor.byte()?)
                    };
                    let text: String = cursor
                        .take(length)?
                        .iter()
                        .map(|b| char::from(*b))
                        .collect();
                    stack.push(Slot::Value(Value::Str(text)));
                }
                b'X' | 0x8c | 0x8d => {
                    let length = match opcode {
                        b'X' => cursor.length(4)?,
                        0x8c => usize::from(cursor.byte()?),
                        _ => cursor.length(8)?,
                    };
                    let text = std::str::from_utf8(cursor.take(length)?)
                        .map_err(|_| corrupt("pickle string is not UTF-8"))?
                        .to_string();
                    stack.push(Slot::Value(Value::Str(text)));
                }
                b'B' | b'C' | 0x8e => {
                    let length = match opcode {
                        b'B' => cursor.length(4)?,
                        b'C' => usize::from(cursor.byte()?),
                        _ => cursor.length(8)?,
                    };
                    stack.push(Slot::Value(Value::Bytes(cursor.take(length)?.to_vec())));
                }
                b'p' => {
                    let index = cursor
                        .line()?
                        .parse::<usize>()
                        .map_err(|_| corrupt("bad memo index"))?;
                    let value = match stack.last() {
                        Some(Slot::Value(value)) => value.clone(),
                        _ => return Err(corrupt("PUT on an empty stack")),
                    };
                    remember(&mut memo, index, value);
                }
                b'q' | b'r' => {
                    let index = if opcode == b'q' {
                        usize::from(cursor.byte()?)
                    } else {
                        cursor.length(4)?
                    };
                    let value = match stack.last() {
                        Some(Slot::Value(value)) => value.clone(),
                        _ => return Err(corrupt("PUT on an empty stack")),
                    };
                    remember(&mut memo, index, value);
                }
                0x94 => {
                    let value = match stack.last() {
                        Some(Slot::Value(value)) => value.clone(),
                        _ => return Err(corrupt("MEMOIZE on an empty stack")),
                    };
                    let index = memo.len();
                    remember(&mut memo, index, value);
                }
                b'g' => {
                    let index = cursor
                        .line()?
                        .parse::<usize>()
                        .map_err(|_| corrupt("bad memo index"))?;
                    stack.push(Slot::Value(recall(&memo, index)?));
                }
                b'h' | b'j' => {
                    let index = if opcode == b'h' {
                        usize::from(cursor.byte()?)
                    } else {
                        cursor.length(4)?
                    };
                    stack.push(Slot::Value(recall(&memo, index)?));
                }
                // GLOBAL, REDUCE, BUILD, INST, OBJ, NEWOBJ, STACK_GLOBAL,
                // EXT*, persistent ids, ...: all of them would resolve or
                // call something, and none belongs in an index.
                other => {
                    return Err(ArchiveError::Refused(format!("opcode 0x{other:02x}")));
                }
            }
        }
    }
}

#[cfg(test)]
pub(crate) mod test_support {
    use std::io::Write;
    use std::path::{Path, PathBuf};

    use flate2::write::ZlibEncoder;
    use flate2::Compression;

    pub(crate) fn scratch(name: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("rts-archive-{name}-{nanos}"));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    /// A protocol-2 pickle of `{name: [(offset, length)]}` as Python 2
    /// writes it: byte strings for the keys, plain integers.
    pub(crate) fn index_pickle(entries: &[(&str, u32, u32)]) -> Vec<u8> {
        let mut out = vec![0x80, 0x02, b'}', b'q', 0, b'('];
        for (name, offset, length) in entries {
            out.push(b'U');
            out.push(name.len() as u8);
            out.extend_from_slice(name.as_bytes());
            out.extend_from_slice(&[b']', b'q', 1]);
            for number in [offset, length] {
                out.push(b'J');
                out.extend_from_slice(&number.to_le_bytes());
            }
            out.extend_from_slice(&[0x86, b'a']);
        }
        out.push(b'u');
        out.push(b'.');
        out
    }

    /// Write an archive. `key` obfuscates offsets for RPA-3.0.
    pub(crate) fn write_archive(path: &Path, members: &[(&str, &[u8])], key: Option<u32>) {
        let header_room = 64usize;
        let mut body = Vec::new();
        let mut entries = Vec::new();
        for (name, data) in members {
            let offset = (header_room + body.len()) as u32;
            entries.push((
                *name,
                offset ^ key.unwrap_or(0),
                data.len() as u32 ^ key.unwrap_or(0),
            ));
            body.extend_from_slice(data);
        }
        let index_offset = (header_room + body.len()) as u64;
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(&index_pickle(&entries)).unwrap();
        let compressed = encoder.finish().unwrap();

        let header = match key {
            Some(key) => format!("RPA-3.0 {index_offset:016x} {key:08x}\n"),
            None => format!("RPA-2.0 {index_offset:016x}\n"),
        };
        let mut file = header.into_bytes();
        file.resize(header_room, b' ');
        file.extend_from_slice(&body);
        file.extend_from_slice(&compressed);
        std::fs::write(path, file).unwrap();
    }
}

#[cfg(test)]
mod tests {
    use super::test_support::{scratch, write_archive};
    use super::*;

    #[test]
    fn member_names_are_normalized_and_unsafe_ones_refused() {
        assert_eq!(validate_member_name("a\\b\\c.rpy").unwrap(), "a/b/c.rpy");
        for bad in ["/etc/passwd", "C:/x", "a/../b", "..\\x"] {
            assert!(validate_member_name(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn reads_the_members_of_an_unobfuscated_archive() {
        let dir = scratch("v2");
        let path = dir.join("scripts.rpa");
        write_archive(
            &path,
            &[("script.rpy", b"label start:\n"), ("sub\\more.rpy", b"x")],
            None,
        );

        let mut archive = RpaArchive::open(&path).unwrap();

        assert_eq!(archive.names(), ["script.rpy", "sub/more.rpy"]);
        assert_eq!(archive.read("script.rpy").unwrap(), b"label start:\n");
        assert_eq!(archive.read("sub/more.rpy").unwrap(), b"x");
        assert!(matches!(
            archive.read("missing.rpy"),
            Err(ArchiveError::NoSuchMember { .. })
        ));
    }

    #[test]
    fn reads_an_archive_obfuscated_with_a_key() {
        let dir = scratch("v3");
        let path = dir.join("scripts.rpa");
        write_archive(&path, &[("a.rpy", b"hello")], Some(0x00AB_CDEF));

        let mut archive = RpaArchive::open(&path).unwrap();

        assert_eq!(archive.read("a.rpy").unwrap(), b"hello");
    }

    #[test]
    fn a_file_that_is_not_an_archive_is_refused() {
        let dir = scratch("junk");
        let path = dir.join("junk.rpa");
        std::fs::write(&path, b"not an archive\n").unwrap();
        assert!(matches!(
            RpaArchive::open(&path),
            Err(ArchiveError::UnsupportedHeader(_))
        ));
    }

    #[test]
    fn an_index_that_resolves_a_function_is_refused() {
        // protocol 2: GLOBAL os system, then REDUCE.
        let mut pickle = vec![0x80, 0x02, b'c'];
        pickle.extend_from_slice(b"os\nsystem\n");
        pickle.extend_from_slice(&[b'X', 4, 0, 0, 0]);
        pickle.extend_from_slice(b"calc");
        pickle.extend_from_slice(&[0x85, b'R', b'.']);
        assert!(matches!(
            pickle::load(&pickle),
            Err(ArchiveError::Refused(_))
        ));
    }

    #[test]
    fn a_member_name_escaping_the_game_folder_is_refused_at_open() {
        let dir = scratch("escape");
        let path = dir.join("evil.rpa");
        write_archive(&path, &[("../outside.rpy", b"x")], None);
        assert!(matches!(
            RpaArchive::open(&path),
            Err(ArchiveError::UnsafeName { .. })
        ));
    }

    #[test]
    fn a_truncated_pickle_is_corrupt_not_a_panic() {
        assert!(matches!(
            pickle::load(&[0x80, 0x02, b'}', b'q']),
            Err(ArchiveError::CorruptIndex(_))
        ));
    }

    #[test]
    fn python_3_pickles_with_framing_and_memoization_load() {
        // protocol 4: {'a.rpy': [(1, 2)]}
        let mut pickle = vec![
            0x80, 0x04, 0x95, 0, 0, 0, 0, 0, 0, 0, 0, b'}', 0x94, 0x8c, 5,
        ];
        pickle.extend_from_slice(b"a.rpy");
        pickle.extend_from_slice(&[
            0x94, b']', 0x94, b'K', 1, b'K', 2, 0x86, 0x94, b'a', b's', b'.',
        ]);
        assert_eq!(
            pickle::load(&pickle).unwrap(),
            pickle::Value::Dict(vec![(
                pickle::Value::Str("a.rpy".into()),
                pickle::Value::List(vec![pickle::Value::Tuple(vec![
                    pickle::Value::Int(1),
                    pickle::Value::Int(2)
                ])])
            )])
        );
    }
}
