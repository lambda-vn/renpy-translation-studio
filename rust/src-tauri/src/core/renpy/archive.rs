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

/// Ceiling on the decompressed index, and on what the pickle memo may copy
/// out: a few kilobytes of hostile input must not turn into gigabytes.
/// A 40 000-file game's index is a few megabytes.
const MAX_INDEX_SIZE: usize = 64 * 1024 * 1024;

/// Ceiling on the header line: `RPA-3.2 <offset> <keys>` is far below it,
/// and `read_until` would otherwise buffer a file without any newline.
const MAX_HEADER_SIZE: u64 = 256;

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
    #[error("Archive content too large to extract: {0}")]
    ExtractionLimit(String),
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
    let file_size = file.metadata()?.len();
    let mut reader = BufReader::new(&mut *file);
    let mut header_line = Vec::new();
    (&mut reader)
        .take(MAX_HEADER_SIZE)
        .read_until(b'\n', &mut header_line)?;
    if header_line.last() != Some(&b'\n') {
        return Err(ArchiveError::UnsupportedHeader(
            String::from_utf8_lossy(&header_line).into_owned(),
        ));
    }
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
    let mut decompressed = Vec::new();
    ZlibDecoder::new(BufReader::new(&mut *file))
        .take(MAX_INDEX_SIZE as u64 + 1)
        .read_to_end(&mut decompressed)
        .map_err(|e| ArchiveError::CorruptIndex(e.to_string()))?;
    if decompressed.len() > MAX_INDEX_SIZE {
        return Err(ArchiveError::CorruptIndex("archive index too large".into()));
    }
    let payload = pickle::load(&decompressed)?;
    normalize_index(payload, key, file_size)
}

fn normalize_index(
    payload: pickle::Value,
    key: i128,
    file_size: u64,
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
        let file_bytes = length
            .checked_sub(prefix.len() as u64)
            .ok_or_else(malformed)?;
        if offset
            .checked_add(file_bytes)
            .is_none_or(|end| end > file_size)
        {
            return Err(malformed());
        }
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

    /// How deep a value may nest, a scalar counting as one.
    ///
    /// A real index is a dict of lists of tuples of scalars, four levels.
    /// One byte of input adds a level (`0x85` wraps the top in a tuple),
    /// and `clone`, `drop` and `weight` recurse once per level: unbounded,
    /// a few kilobytes of forged index overflow the stack and abort the
    /// process, which no `Result` can catch.
    const MAX_DEPTH: usize = 16;

    /// A stack slot: a value with its depth, or the marker an opcode like
    /// `(` leaves.
    enum Slot {
        Mark,
        Value(Value, usize),
    }

    fn scalar(value: Value) -> Slot {
        Slot::Value(value, 1)
    }

    /// The depth a container holding values `items` deep reaches, refused
    /// past [`MAX_DEPTH`].
    fn nest(items: usize) -> Result<usize, ArchiveError> {
        let depth = items + 1;
        if depth > MAX_DEPTH {
            return Err(corrupt("pickle nested too deep"));
        }
        Ok(depth)
    }

    /// Split popped values from their depths, returning the depth a
    /// container holding them reaches.
    fn contents(items: Vec<(Value, usize)>) -> Result<(Vec<Value>, usize), ArchiveError> {
        let depth = nest(items.iter().map(|(_, depth)| *depth).max().unwrap_or(0))?;
        Ok((items.into_iter().map(|(value, _)| value).collect(), depth))
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
        let mut memo: Vec<Option<(Value, usize)>> = Vec::new();
        let mut budget = super::MAX_INDEX_SIZE;

        fn pop_value(stack: &mut Vec<Slot>) -> Result<(Value, usize), ArchiveError> {
            match stack.pop() {
                Some(Slot::Value(value, depth)) => Ok((value, depth)),
                _ => Err(corrupt("pickle stack underflow")),
            }
        }

        fn pop_to_mark(stack: &mut Vec<Slot>) -> Result<Vec<(Value, usize)>, ArchiveError> {
            let mark = stack
                .iter()
                .rposition(|slot| matches!(slot, Slot::Mark))
                .ok_or_else(|| corrupt("pickle mark missing"))?;
            stack
                .split_off(mark + 1)
                .into_iter()
                .map(|slot| match slot {
                    Slot::Value(value, depth) => Ok((value, depth)),
                    Slot::Mark => Err(corrupt("nested pickle mark")),
                })
                .collect::<Result<Vec<_>, _>>()
                .inspect(|_| {
                    stack.pop();
                })
        }

        // A real pickle numbers its memo densely, one PUT per entry, so an
        // index past the input size is forged to make `resize` allocate.
        fn remember(
            memo: &mut Vec<Option<(Value, usize)>>,
            index: usize,
            value: (Value, usize),
            limit: usize,
            budget: &mut usize,
        ) -> Result<(), ArchiveError> {
            *budget = budget
                .checked_sub(weight(&value.0))
                .ok_or_else(|| corrupt("pickle memo copies too large"))?;
            if index > limit {
                return Err(corrupt("pickle memo index out of range"));
            }
            if memo.len() <= index {
                memo.resize(index + 1, None);
            }
            memo[index] = Some(value);
            Ok(())
        }

        fn weight(value: &Value) -> usize {
            match value {
                Value::Str(text) => 1 + text.len(),
                Value::Bytes(bytes) => 1 + bytes.len(),
                Value::List(items) | Value::Tuple(items) => {
                    1 + items.iter().map(weight).sum::<usize>()
                }
                Value::Dict(pairs) => {
                    1 + pairs
                        .iter()
                        .map(|(k, v)| weight(k) + weight(v))
                        .sum::<usize>()
                }
                _ => 1,
            }
        }

        // Each GET copies a whole value, so nesting GETs doubles the size
        // at every level; `budget` caps what all copies may add up to.
        fn recall(
            memo: &[Option<(Value, usize)>],
            index: usize,
            budget: &mut usize,
        ) -> Result<Slot, ArchiveError> {
            let (value, depth) = memo
                .get(index)
                .and_then(Option::as_ref)
                .ok_or_else(|| corrupt("pickle memo miss"))?;
            *budget = budget
                .checked_sub(weight(value))
                .ok_or_else(|| corrupt("pickle memo copies too large"))?;
            Ok(Slot::Value(value.clone(), *depth))
        }

        /// The top of the stack, copied for the memo.
        fn top(stack: &[Slot], refusal: &str) -> Result<(Value, usize), ArchiveError> {
            match stack.last() {
                Some(Slot::Value(value, depth)) => Ok((value.clone(), *depth)),
                _ => Err(corrupt(refusal)),
            }
        }

        /// The container on top of the stack, its depth raised to at least
        /// `reach` for what it is about to hold.
        fn target(stack: &mut [Slot], reach: usize) -> Result<&mut Value, ArchiveError> {
            let Some(Slot::Value(target, depth)) = stack.last_mut() else {
                return Err(corrupt("pickle container missing"));
            };
            *depth = (*depth).max(reach);
            Ok(target)
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
                b'.' => return pop_value(&mut stack).map(|(value, _)| value),
                0x80 => {
                    cursor.byte()?;
                }
                0x95 => {
                    cursor.take(8)?;
                }
                b'(' => stack.push(Slot::Mark),
                b'N' => stack.push(scalar(Value::None)),
                0x88 => stack.push(scalar(Value::Bool(true))),
                0x89 => stack.push(scalar(Value::Bool(false))),
                b'}' => stack.push(scalar(Value::Dict(Vec::new()))),
                b']' => stack.push(scalar(Value::List(Vec::new()))),
                b')' => stack.push(scalar(Value::Tuple(Vec::new()))),
                b'd' => {
                    let (items, depth) = contents(pop_to_mark(&mut stack)?)?;
                    let mut dict = Value::Dict(Vec::new());
                    set_items(&mut dict, items)?;
                    stack.push(Slot::Value(dict, depth));
                }
                b'l' => {
                    let (items, depth) = contents(pop_to_mark(&mut stack)?)?;
                    stack.push(Slot::Value(Value::List(items), depth));
                }
                b't' => {
                    let (items, depth) = contents(pop_to_mark(&mut stack)?)?;
                    stack.push(Slot::Value(Value::Tuple(items), depth));
                }
                0x85..=0x87 => {
                    let count = usize::from(opcode - 0x84);
                    let mut items = Vec::with_capacity(count);
                    for _ in 0..count {
                        items.push(pop_value(&mut stack)?);
                    }
                    items.reverse();
                    let (items, depth) = contents(items)?;
                    stack.push(Slot::Value(Value::Tuple(items), depth));
                }
                b's' => {
                    let value = pop_value(&mut stack)?;
                    let key = pop_value(&mut stack)?;
                    let (items, depth) = contents(vec![key, value])?;
                    set_items(target(&mut stack, depth)?, items)?;
                }
                b'u' => {
                    let (items, depth) = contents(pop_to_mark(&mut stack)?)?;
                    set_items(target(&mut stack, depth)?, items)?;
                }
                b'a' => {
                    let (item, depth) = pop_value(&mut stack)?;
                    let Value::List(list) = target(&mut stack, nest(depth)?)? else {
                        return Err(corrupt("APPEND without a list"));
                    };
                    list.push(item);
                }
                b'e' => {
                    let (items, depth) = contents(pop_to_mark(&mut stack)?)?;
                    let Value::List(list) = target(&mut stack, depth)? else {
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
                    stack.push(scalar(value));
                }
                b'J' => {
                    let value = cursor.le(4)? as u32 as i32;
                    stack.push(scalar(Value::Int(i128::from(value))));
                }
                b'K' => {
                    let value = cursor.byte()?;
                    stack.push(scalar(Value::Int(i128::from(value))));
                }
                b'M' => {
                    let value = cursor.le(2)?;
                    stack.push(scalar(Value::Int(i128::from(value))));
                }
                0x8a => {
                    let length = usize::from(cursor.byte()?);
                    let value = signed_le(cursor.take(length)?)?;
                    stack.push(scalar(Value::Int(value)));
                }
                0x8b => {
                    let length = cursor.length(4)?;
                    let value = signed_le(cursor.take(length)?)?;
                    stack.push(scalar(Value::Int(value)));
                }
                b'F' => {
                    let value = cursor
                        .line()?
                        .parse::<f64>()
                        .map_err(|_| corrupt("bad float"))?;
                    stack.push(scalar(Value::Float(value)));
                }
                b'G' => {
                    let bytes = cursor.take(8)?;
                    let mut array = [0u8; 8];
                    array.copy_from_slice(bytes);
                    stack.push(scalar(Value::Float(f64::from_be_bytes(array))));
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
                    stack.push(scalar(Value::Str(text)));
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
                    stack.push(scalar(Value::Str(text)));
                }
                b'B' | b'C' | 0x8e => {
                    let length = match opcode {
                        b'B' => cursor.length(4)?,
                        b'C' => usize::from(cursor.byte()?),
                        _ => cursor.length(8)?,
                    };
                    stack.push(scalar(Value::Bytes(cursor.take(length)?.to_vec())));
                }
                b'p' => {
                    let index = cursor
                        .line()?
                        .parse::<usize>()
                        .map_err(|_| corrupt("bad memo index"))?;
                    let value = top(&stack, "PUT on an empty stack")?;
                    remember(&mut memo, index, value, data.len(), &mut budget)?;
                }
                b'q' | b'r' => {
                    let index = if opcode == b'q' {
                        usize::from(cursor.byte()?)
                    } else {
                        cursor.length(4)?
                    };
                    let value = top(&stack, "PUT on an empty stack")?;
                    remember(&mut memo, index, value, data.len(), &mut budget)?;
                }
                0x94 => {
                    let value = top(&stack, "MEMOIZE on an empty stack")?;
                    let index = memo.len();
                    remember(&mut memo, index, value, data.len(), &mut budget)?;
                }
                b'g' => {
                    let index = cursor
                        .line()?
                        .parse::<usize>()
                        .map_err(|_| corrupt("bad memo index"))?;
                    stack.push(recall(&memo, index, &mut budget)?);
                }
                b'h' | b'j' => {
                    let index = if opcode == b'h' {
                        usize::from(cursor.byte()?)
                    } else {
                        cursor.length(4)?
                    };
                    stack.push(recall(&memo, index, &mut budget)?);
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

    #[test]
    fn a_forged_memo_index_is_refused_before_allocating() {
        let pickle = [0x80, 0x02, b']', b'r', 0xff, 0xff, 0xff, 0xff, b'.'];
        assert!(matches!(
            pickle::load(&pickle),
            Err(ArchiveError::CorruptIndex(_))
        ));
    }

    #[test]
    fn growing_memoized_list_is_capped() {
        let mut pickle = vec![0x80, 0x02, b']', b'q', 0];
        for _ in 0..20_000 {
            pickle.extend_from_slice(&[b'N', b'a', b'q', 0]);
        }
        pickle.push(b'.');
        assert!(matches!(
            pickle::load(&pickle),
            Err(ArchiveError::CorruptIndex(_))
        ));
    }

    #[test]
    fn header_without_newline_within_the_ceiling_is_refused() {
        let dir = scratch("longheader");
        let path = dir.join("long.rpa");
        std::fs::write(&path, vec![b'A'; 300]).unwrap();
        assert!(matches!(
            RpaArchive::open(&path),
            Err(ArchiveError::UnsupportedHeader(_))
        ));
    }

    #[test]
    fn entries_pointing_past_the_end_of_the_file_are_refused() {
        let payload = |offset: i128, length: i128| {
            pickle::Value::Dict(vec![(
                pickle::Value::Str("a.rpy".into()),
                pickle::Value::List(vec![pickle::Value::Tuple(vec![
                    pickle::Value::Int(offset),
                    pickle::Value::Int(length),
                ])]),
            )])
        };
        assert!(normalize_index(payload(100, 10), 0, 110).is_ok());
        assert!(matches!(
            normalize_index(payload(100, 11), 0, 110),
            Err(ArchiveError::MalformedEntry(_))
        ));
        assert!(matches!(
            normalize_index(payload(i128::from(u64::MAX), 1), 0, 110),
            Err(ArchiveError::MalformedEntry(_))
        ));
    }

    #[test]
    fn nested_memo_copies_are_capped() {
        // Each round replaces memo 0 by a pair of itself: 2^64 nodes if unbounded.
        let mut pickle = vec![0x80, 0x02, b']', b'q', 0];
        for _ in 0..64 {
            pickle.extend_from_slice(&[b'h', 0, b'h', 0, 0x86, b'q', 0]);
        }
        pickle.push(b'.');
        assert!(matches!(
            pickle::load(&pickle),
            Err(ArchiveError::CorruptIndex(_))
        ));
    }

    #[test]
    fn a_pickle_nested_past_the_depth_limit_is_refused() {
        let nested = |levels: usize| {
            let mut pickle = vec![0x80, 2, b'N'];
            pickle.extend(std::iter::repeat_n(0x85, levels));
            pickle.push(b'.');
            pickle
        };
        assert!(pickle::load(&nested(15)).is_ok());
        assert!(matches!(
            pickle::load(&nested(16)),
            Err(ArchiveError::CorruptIndex(_))
        ));
        assert!(matches!(
            pickle::load(&nested(1_000_000)),
            Err(ArchiveError::CorruptIndex(_))
        ));
    }

    #[test]
    fn appending_a_deep_value_raises_the_list_depth() {
        let mut pickle = vec![0x80, 2, b']', b'N'];
        pickle.extend(std::iter::repeat_n(0x85, 15));
        pickle.extend_from_slice(b"a.");
        assert!(matches!(
            pickle::load(&pickle),
            Err(ArchiveError::CorruptIndex(_))
        ));
    }
}
