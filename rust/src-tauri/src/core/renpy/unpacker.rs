//! Selective extraction of `.rpy` sources from `.rpa` archives.
//!
//! The translate command only sees files that exist on disk: a script
//! packed inside an `.rpa` is invisible to it. Writing the `.rpy` members
//! of every archive in `game/` back onto disk, without ever overwriting
//! what is already there, makes Ren'Py's own extraction see them.
//!
//! Ren'Py's engine, unlike the file-listing `translate` itself uses, loads
//! a script from disk and from an archive as two distinct sources with no
//! deduplication: with both present it fails every label they share as
//! "defined twice". [`disable_extracted_archives`] renames a script-only
//! archive out of the way for the run, [`restore_disabled_archives`] puts
//! it back; a mixed archive (script and image/audio members together) is
//! left in place, since renaming it would break the resources it also
//! holds.
//!
//! What this module created is recorded in `.rts/unpacked_sources.json`,
//! in the shape the 1.x application also writes, so that a project can be
//! cleaned up by either version.

use std::collections::{BTreeMap, HashSet};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use super::archive::{validate_member_name, ArchiveError, RpaArchive};
use crate::core::validators::resolve_safe_path;

const DISABLED_SUFFIX: &str = ".disabled";
const EXTRACTABLE_SUFFIXES: [&str; 2] = ["rpy", "rpym"];
const SCRIPT_SUFFIXES: [&str; 4] = ["rpy", "rpym", "rpyc", "rpymc"];
const COMPILED_SUFFIXES: [&str; 2] = ["rpyc", "rpymc"];

/// Ceilings on what one run writes to disk. Index entries may overlap and
/// point at the same block, so a few megabytes of archive can describe far
/// more extracted data than the archive holds.
const MAX_EXTRACTED_BYTES: u64 = 512 * 1024 * 1024;
const MAX_EXTRACTED_MEMBERS: usize = 100_000;

fn manifest_path(project: &Path) -> PathBuf {
    project.join(".rts").join("unpacked_sources.json")
}

/// A single source file extracted from an `.rpa` archive.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UnpackedEntry {
    /// Path relative to `game/`, with forward slashes.
    pub path: String,
    /// Whether a compiled `.rpyc` already sat next to the source before extraction.
    pub rpyc_preexisted: bool,
}

/// An archive temporarily renamed out of Ren'Py's search path.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DisabledArchive {
    /// The archive's name in `game/`.
    pub archive: String,
    /// The temporary name it carries while disabled.
    pub temp_name: String,
}

#[derive(Debug, Default, Serialize)]
struct Manifest {
    entries: Vec<UnpackedEntry>,
    disabled_archives: Vec<DisabledArchive>,
}

/// Read a previously written manifest, an empty one if absent or unreadable.
/// Entries of an unexpected shape are dropped one by one rather than failing
/// the whole file.
fn read_manifest(project: &Path) -> Manifest {
    let Ok(text) = std::fs::read_to_string(manifest_path(project)) else {
        return Manifest::default();
    };
    let Ok(serde_json::Value::Object(raw)) = serde_json::from_str::<serde_json::Value>(&text)
    else {
        return Manifest::default();
    };
    let items = |key: &str| -> Vec<serde_json::Value> {
        raw.get(key)
            .and_then(|value| value.as_array())
            .cloned()
            .unwrap_or_default()
    };
    Manifest {
        entries: items("entries")
            .into_iter()
            .filter_map(|item| serde_json::from_value::<UnpackedEntry>(item).ok())
            .filter(|entry| {
                let valid = is_safe_entry_path(&entry.path);
                if !valid {
                    log::warn!("ignoring unsafe manifest entry {:?}", entry.path);
                }
                valid
            })
            .collect(),
        disabled_archives: items("disabled_archives")
            .into_iter()
            .filter_map(|item| serde_json::from_value::<DisabledArchive>(item).ok())
            .filter(|disabled| {
                let valid = is_safe_disabled_archive(disabled);
                if !valid {
                    log::warn!("ignoring unsafe manifest archive {disabled:?}");
                }
                valid
            })
            .collect(),
    }
}

/// A manifest path is a member name as this module wrote it: already
/// normalized, relative, without any traversal.
fn is_safe_entry_path(path: &str) -> bool {
    validate_member_name(path).is_ok_and(|normalized| normalized == path)
}

/// A bare `.rpa` file name, and the `<archive>.disabled[.<n>]` name
/// [`disabled_path`] derives from it, nothing else: both are joined to
/// `game/` and renamed.
fn is_safe_disabled_archive(disabled: &DisabledArchive) -> bool {
    let bare = |name: &str| {
        !name.is_empty() && !name.contains(['/', '\\', ':']) && is_safe_entry_path(name)
    };
    let is_archive = Path::new(&disabled.archive)
        .extension()
        .is_some_and(|ext| ext.eq_ignore_ascii_case("rpa"));
    let Some(rest) = disabled.temp_name.strip_prefix(&disabled.archive) else {
        return false;
    };
    let Some(rest) = rest.strip_prefix(DISABLED_SUFFIX) else {
        return false;
    };
    let counter_ok = rest.is_empty()
        || rest
            .strip_prefix('.')
            .is_some_and(|n| !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit()));
    is_archive && bare(&disabled.archive) && bare(&disabled.temp_name) && counter_ok
}

fn write_manifest(project: &Path, manifest: &Manifest) -> Result<(), ArchiveError> {
    let path = manifest_path(project);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let text = serde_json::to_string_pretty(manifest)
        .map_err(|e| ArchiveError::Manifest(e.to_string()))?;
    std::fs::write(path, text)?;
    Ok(())
}

/// The `.rpa` files directly under `game/`, sorted by name.
fn rpa_files(game_dir: &Path) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(game_dir) else {
        return Vec::new();
    };
    let mut files: Vec<PathBuf> = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.is_file()
                && path
                    .extension()
                    .is_some_and(|ext| ext.eq_ignore_ascii_case("rpa"))
        })
        .collect();
    files.sort();
    files
}

fn first_segment(name: &str) -> &str {
    name.split('/').next().unwrap_or("")
}

fn has_suffix(name: &str, suffixes: &[&str]) -> bool {
    Path::new(name)
        .extension()
        .and_then(|ext| ext.to_str())
        .is_some_and(|ext| suffixes.contains(&ext))
}

/// A `.rpy`/`.rpym` member that is not under `tl/`: those carry
/// translations bundled by the game's own build, not sources to translate.
fn is_extractable(name: &str) -> bool {
    first_segment(name) != "tl" && has_suffix(name, &EXTRACTABLE_SUFFIXES)
}

/// Resolve a member name to a path inside `game/`.
///
/// Names are already validated against traversal when the archive is
/// opened, but writing to disk is the point of no return, so it is
/// checked again here, the way the exporter double-checks zip entries.
fn resolve_target(game_dir: &Path, name: &str) -> Result<PathBuf, ArchiveError> {
    resolve_safe_path(&game_dir.join(name), Some(game_dir))
        .map_err(|_| ArchiveError::UnsafePath(name.to_string()))
}

fn try_unlink(path: &Path) -> bool {
    !path.exists() || std::fs::remove_file(path).is_ok()
}

/// Extract the `.rpy`/`.rpym` members of every `.rpa` archive in `game/`.
///
/// Restores any archive a previous, interrupted run left disabled before
/// scanning: a renamed archive does not match the `*.rpa` scan, so without
/// this the game would stay broken by a crash this application caused, and
/// this run would not see that archive's members either.
///
/// A member is skipped whenever a file already sits at its target path: the
/// manifest only ever records files this function itself created, so a
/// second run is safe to repeat.
///
/// Returns every entry known after this run, including ones created by a
/// previous run.
///
/// # Errors
///
/// [`ArchiveError::Io`] on a filesystem failure, the index errors for a
/// malformed archive, [`ArchiveError::UnsafePath`] for a member that would
/// land outside `game/`, [`ArchiveError::ExtractionLimit`] when an archive
/// would write more than the ceilings allow.
pub fn unpack_archived_sources(project: &Path) -> Result<Vec<UnpackedEntry>, ArchiveError> {
    restore_disabled_archives(project)?;

    let game_dir = project.join("game");
    let manifest = read_manifest(project);
    let mut entries: BTreeMap<String, UnpackedEntry> = manifest
        .entries
        .into_iter()
        .map(|entry| (entry.path.clone(), entry))
        .collect();

    let extraction = extract_into(&game_dir, &mut entries);

    let entries: Vec<UnpackedEntry> = entries.into_values().collect();
    if !entries.is_empty() || !manifest.disabled_archives.is_empty() {
        let written = write_manifest(
            project,
            &Manifest {
                entries: entries.clone(),
                disabled_archives: manifest.disabled_archives,
            },
        );
        extraction?;
        written?;
    } else {
        extraction?;
    }
    Ok(entries)
}

/// Extract every archive into `game_dir`, recording each file in `entries`
/// as soon as it is written so that a failure part-way leaves the caller
/// able to persist exactly what is on disk.
fn extract_into(
    game_dir: &Path,
    entries: &mut BTreeMap<String, UnpackedEntry>,
) -> Result<(), ArchiveError> {
    extract_within(
        game_dir,
        entries,
        MAX_EXTRACTED_BYTES,
        MAX_EXTRACTED_MEMBERS,
    )
}

/// [`extract_into`] with explicit ceilings on the total bytes written and
/// the number of members extracted, across all archives. What earlier runs
/// extracted (`entries` on entry) counts too, so running again after a
/// refusal does not grant a fresh quota.
fn extract_within(
    game_dir: &Path,
    entries: &mut BTreeMap<String, UnpackedEntry>,
    max_bytes: u64,
    max_members: usize,
) -> Result<(), ArchiveError> {
    let mut written_members = entries.len();
    let mut written_bytes: u64 = entries
        .keys()
        .filter_map(|name| resolve_target(game_dir, name).ok())
        .filter_map(|target| std::fs::metadata(target).ok())
        .map(|metadata| metadata.len())
        .fold(0, u64::saturating_add);
    for archive_path in rpa_files(game_dir) {
        let mut archive = RpaArchive::open(&archive_path)?;
        for name in archive.names().to_vec() {
            if !is_extractable(&name) {
                continue;
            }
            let target = resolve_target(game_dir, &name)?;
            if target.exists() {
                continue;
            }
            let rpyc_preexisted = target.with_extension("rpyc").exists();
            if let Some(parent) = target.parent() {
                std::fs::create_dir_all(parent)?;
            }
            let content = archive.read(&name)?;
            written_members += 1;
            written_bytes = written_bytes.saturating_add(content.len() as u64);
            if written_members > max_members || written_bytes > max_bytes {
                return Err(ArchiveError::ExtractionLimit(
                    archive_path.display().to_string(),
                ));
            }
            entries.insert(
                name.clone(),
                UnpackedEntry {
                    path: name,
                    rpyc_preexisted,
                },
            );
            std::fs::write(&target, content)?;
        }
    }
    Ok(())
}

/// Whether `game/`'s archives hold compiled scripts (`.rpyc`, `.rpymc`)
/// outside `tl/` and none of them has its source, neither archived nor
/// on disk.
///
/// Tells apart a game with no archived scripts at all, the common case
/// where extraction has nothing to do, from one shipping only bytecode: no
/// amount of extraction recovers a source from a `.rpyc`, a decompiler
/// would be needed instead.
///
/// A source already on disk counts: an earlier extraction leaves the
/// sources it unpacked in `game/`, and when its manifest is gone (the
/// project's `.rts/` deleted) nothing is unpacked again, although every
/// source is there to translate.
///
/// # Errors
///
/// The errors of [`RpaArchive::open`] for an archive that cannot be read.
pub fn archives_hold_only_compiled_scripts(project: &Path) -> Result<bool, ArchiveError> {
    let game_dir = project.join("game");
    let mut archived_sources: HashSet<String> = HashSet::new();
    let mut compiled: Vec<String> = Vec::new();
    for archive_path in rpa_files(&game_dir) {
        let archive = RpaArchive::open(&archive_path)?;
        for name in archive.names() {
            if is_extractable(name) {
                archived_sources.insert(name.clone());
            } else if first_segment(name) != "tl" && has_suffix(name, &COMPILED_SUFFIXES) {
                compiled.push(name.clone());
            }
        }
    }
    let has_source = |name: &String| {
        let source = name.strip_suffix('c').unwrap_or(name);
        archived_sources.contains(source)
            || resolve_target(&game_dir, source).is_ok_and(|path| path.is_file())
    };
    Ok(!compiled.is_empty() && !compiled.iter().any(has_source))
}

/// Rename each script-only archive whose sources were unpacked.
///
/// Must only run once every archive has been fully unpacked: renaming makes
/// the whole archive unreadable for the duration, not just the members
/// that were extracted from it.
///
/// Only an archive holding nothing but script files (`.rpy`, `.rpym`, and
/// their compiled forms) is renamed. A mixed archive keeps its images or
/// audio reachable by staying in place; a source it produced that Ren'Py
/// then reports as defined twice falls back to the ordinary
/// discard-and-retry an unparseable source already goes through.
///
/// Returns the archive names (relative to `game/`) that were renamed.
///
/// # Errors
///
/// [`ArchiveError::Io`] when an archive cannot be read or renamed,
/// [`ArchiveError::Manifest`] when the manifest cannot be written.
pub fn disable_extracted_archives(project: &Path) -> Result<Vec<String>, ArchiveError> {
    let game_dir = project.join("game");
    let mut manifest = read_manifest(project);
    let unpacked: std::collections::HashSet<&str> =
        manifest.entries.iter().map(|e| e.path.as_str()).collect();

    let mut renamed = Vec::new();
    for archive_path in rpa_files(&game_dir) {
        let names = RpaArchive::open(&archive_path)?.names().to_vec();
        if !names.iter().any(|name| unpacked.contains(name.as_str())) {
            continue;
        }
        if !names.iter().all(|name| has_suffix(name, &SCRIPT_SUFFIXES)) {
            continue;
        }
        let temp_path = disabled_path(&archive_path);
        let file_name = |path: &Path| {
            path.file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default()
        };
        manifest.disabled_archives.push(DisabledArchive {
            archive: file_name(&archive_path),
            temp_name: file_name(&temp_path),
        });
        write_manifest(project, &manifest)?;
        if let Err(error) = std::fs::rename(&archive_path, &temp_path) {
            manifest.disabled_archives.pop();
            write_manifest(project, &manifest)?;
            return Err(error.into());
        }
        renamed.push(file_name(&archive_path));
    }

    Ok(renamed)
}

/// Rename every archive [`disable_extracted_archives`] renamed, back.
///
/// Must run whether the Ren'Py run that followed succeeded or failed: the
/// game itself reads these archives too, and nothing outside this
/// application knows to look for the temporary name. Safe to call when
/// nothing is disabled.
///
/// # Errors
///
/// [`ArchiveError::Io`] when an archive cannot be renamed back or the
/// manifest written, [`ArchiveError::Manifest`] when it cannot be serialized.
pub fn restore_disabled_archives(project: &Path) -> Result<(), ArchiveError> {
    let game_dir = project.join("game");
    let mut manifest = read_manifest(project);
    if manifest.disabled_archives.is_empty() {
        return Ok(());
    }

    let mut still_disabled = Vec::new();
    for disabled in manifest.disabled_archives {
        let temp_path = game_dir.join(&disabled.temp_name);
        let original_path = game_dir.join(&disabled.archive);
        if temp_path.is_file() {
            std::fs::rename(&temp_path, &original_path)?;
        } else if !original_path.is_file() {
            still_disabled.push(disabled);
        }
    }
    manifest.disabled_archives = still_disabled;
    write_manifest(project, &manifest)
}

/// Remove named sources this module unpacked, forgetting them.
///
/// Meant for the `.rpy` Ren'Py refuses to parse. A game shipping a source
/// its own engine cannot compile blocks the whole run, since Ren'Py loads
/// every script before generating anything; dropping the file lets the
/// archived `.rpyc` take over, which is what ran before any of this and
/// still runs the game.
///
/// A name absent from the manifest is ignored rather than deleted, so an
/// error blaming one of the game's own files never removes it. That check
/// is what makes the caller free to pass paths read out of Ren'Py's output.
///
/// `names` are paths as Ren'Py reports them, relative to the project root
/// (`game/x.rpy`) or to `game/` (`x.rpy`). Returns the manifest-relative
/// paths actually removed.
///
/// # Errors
///
/// [`ArchiveError::Io`] or [`ArchiveError::Manifest`] when the manifest
/// cannot be written back.
pub fn discard_unpacked_files(
    project: &Path,
    names: &[String],
) -> Result<Vec<String>, ArchiveError> {
    let game_dir = project.join("game");
    let mut manifest = read_manifest(project);
    let mut by_path: BTreeMap<String, UnpackedEntry> = manifest
        .entries
        .drain(..)
        .map(|entry| (entry.path.clone(), entry))
        .collect();

    let mut discarded = Vec::new();
    for name in names {
        let normalized = name.replace('\\', "/");
        let normalized = normalized
            .strip_prefix("game/")
            .unwrap_or(&normalized)
            .to_string();
        let Some(entry) = by_path.get(&normalized) else {
            continue;
        };
        let target = resolve_target(&game_dir, &entry.path)?;
        if !entry.rpyc_preexisted {
            try_unlink(&target.with_extension("rpyc"));
        }
        if !try_unlink(&target) {
            continue;
        }
        by_path.remove(&normalized);
        discarded.push(normalized);
    }

    if !discarded.is_empty() {
        manifest.entries = by_path.into_values().collect();
        write_manifest(project, &manifest)?;
    }
    Ok(discarded)
}

/// Remove every source file created by [`unpack_archived_sources`].
///
/// Restores any archive still disabled first: this is meant to run once a
/// translation has been exported and nothing is expected to still be
/// mid-run, but an archive left renamed would otherwise break the game
/// permanently.
///
/// A `.rpyc` compiled from a freshly extracted `.rpy` is removed alongside
/// it, but only when the manifest recorded that no `.rpyc` sat there before
/// extraction: one that already existed belongs to the project, not to us.
/// Directories left empty are pruned, but `game/` itself never is.
///
/// A file that cannot be deleted (open elsewhere) stays in the manifest
/// instead of being silently forgotten, so a later call can still find and
/// remove it.
///
/// # Errors
///
/// [`ArchiveError::Io`] when an archive cannot be restored or the
/// manifest cannot be updated; [`ArchiveError::Manifest`] when it cannot
/// be serialized.
pub fn remove_unpacked_sources(project: &Path) -> Result<(), ArchiveError> {
    restore_disabled_archives(project)?;

    let game_dir = project.join("game");
    let manifest = read_manifest(project);

    let mut remaining = Vec::new();
    let mut parent_dirs: Vec<PathBuf> = Vec::new();
    for entry in manifest.entries {
        let target = resolve_target(&game_dir, &entry.path)?;
        if !entry.rpyc_preexisted {
            try_unlink(&target.with_extension("rpyc"));
        }
        if try_unlink(&target) {
            if let Some(parent) = target.parent() {
                parent_dirs.push(parent.to_path_buf());
            }
        } else {
            remaining.push(entry);
        }
    }

    parent_dirs.sort();
    parent_dirs.dedup();
    parent_dirs.sort_by_key(|dir| std::cmp::Reverse(dir.components().count()));
    for directory in parent_dirs {
        prune_empty_directories(&directory, &game_dir);
    }

    if remaining.is_empty() {
        let path = manifest_path(project);
        if path.exists() {
            std::fs::remove_file(path)?;
        }
        Ok(())
    } else {
        write_manifest(
            project,
            &Manifest {
                entries: remaining,
                disabled_archives: Vec::new(),
            },
        )
    }
}

/// Remove `directory` and its now-empty ancestors, stopping at `boundary`,
/// which is never removed.
fn prune_empty_directories(directory: &Path, boundary: &Path) {
    let boundary = dunce::canonicalize(boundary).unwrap_or_else(|_| boundary.to_path_buf());
    let mut current = dunce::canonicalize(directory).unwrap_or_else(|_| directory.to_path_buf());
    while current != boundary && current.starts_with(&boundary) {
        let empty = std::fs::read_dir(&current).is_ok_and(|mut entries| entries.next().is_none());
        if !current.is_dir() || !empty || std::fs::remove_dir(&current).is_err() {
            return;
        }
        if !current.pop() {
            return;
        }
    }
}

/// An unused sibling name for temporarily disabling an archive.
fn disabled_path(archive: &Path) -> PathBuf {
    let name = archive
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default();
    let mut candidate = archive.with_file_name(format!("{name}{DISABLED_SUFFIX}"));
    let mut attempt = 1;
    while candidate.exists() {
        candidate = archive.with_file_name(format!("{name}{DISABLED_SUFFIX}.{attempt}"));
        attempt += 1;
    }
    candidate
}

#[cfg(test)]
mod tests {
    use super::super::archive::test_support::{scratch, write_archive};
    use super::*;

    fn game(name: &str) -> PathBuf {
        let project = scratch(name);
        std::fs::create_dir_all(project.join("game")).unwrap();
        project
    }

    fn archive_in(project: &Path, file: &str, members: &[(&str, &[u8])]) {
        write_archive(&project.join("game").join(file), members, None);
    }

    #[test]
    fn extraction_stops_past_the_member_and_byte_ceilings() {
        let project = game("limits");
        archive_in(
            &project,
            "scripts.rpa",
            &[("a.rpy", b"12345"), ("b.rpy", b"12345")],
        );
        let game_dir = project.join("game");

        let mut entries = BTreeMap::new();
        assert!(matches!(
            extract_within(&game_dir, &mut entries, 1024, 1),
            Err(ArchiveError::ExtractionLimit(_))
        ));
        assert!(entries.len() <= 1);

        let project = game("limits-bytes");
        archive_in(&project, "scripts.rpa", &[("a.rpy", b"12345")]);
        let mut entries = BTreeMap::new();
        assert!(matches!(
            extract_within(&project.join("game"), &mut entries, 4, 10),
            Err(ArchiveError::ExtractionLimit(_))
        ));
        assert!(entries.is_empty());
        assert!(!project.join("game").join("a.rpy").exists());
    }

    #[test]
    fn a_second_run_after_a_refusal_gets_no_fresh_quota() {
        let project = game("limits-rerun");
        archive_in(
            &project,
            "scripts.rpa",
            &[("a.rpy", b"12345"), ("b.rpy", b"12345")],
        );
        let game_dir = project.join("game");

        let mut entries = BTreeMap::new();
        assert!(extract_within(&game_dir, &mut entries, 1024, 1).is_err());
        assert!(game_dir.join("a.rpy").exists());

        assert!(matches!(
            extract_within(&game_dir, &mut entries, 1024, 1),
            Err(ArchiveError::ExtractionLimit(_))
        ));
        assert!(!game_dir.join("b.rpy").exists());

        let project = game("limits-rerun-bytes");
        archive_in(
            &project,
            "scripts.rpa",
            &[("a.rpy", b"12345"), ("b.rpy", b"12345")],
        );
        let game_dir = project.join("game");
        let mut entries = BTreeMap::new();
        assert!(extract_within(&game_dir, &mut entries, 7, 10).is_err());
        assert!(matches!(
            extract_within(&game_dir, &mut entries, 7, 10),
            Err(ArchiveError::ExtractionLimit(_))
        ));
        assert!(!game_dir.join("b.rpy").exists());
    }

    #[test]
    fn extracts_scripts_but_not_images_nor_the_games_own_translations() {
        let project = game("extract");
        archive_in(
            &project,
            "scripts.rpa",
            &[
                ("script.rpy", b"label start:"),
                ("events/day1.rpy", b"label day1:"),
                ("images/bg.png", b"png"),
                ("tl/french/script.rpy", b"translate"),
            ],
        );

        let entries = unpack_archived_sources(&project).unwrap();

        let paths: Vec<&str> = entries.iter().map(|e| e.path.as_str()).collect();
        assert_eq!(paths, ["events/day1.rpy", "script.rpy"]);
        assert_eq!(
            std::fs::read(project.join("game").join("events").join("day1.rpy")).unwrap(),
            b"label day1:"
        );
        assert!(!project.join("game").join("images").exists());
        assert!(!project.join("game").join("tl").exists());
    }

    #[test]
    fn a_file_already_on_disk_is_never_overwritten_nor_claimed() {
        let project = game("preexisting");
        std::fs::write(project.join("game").join("script.rpy"), "mine").unwrap();
        archive_in(&project, "scripts.rpa", &[("script.rpy", b"theirs")]);

        let entries = unpack_archived_sources(&project).unwrap();

        assert!(entries.is_empty());
        assert_eq!(
            std::fs::read_to_string(project.join("game").join("script.rpy")).unwrap(),
            "mine"
        );
    }

    #[test]
    fn a_second_run_is_idempotent_and_keeps_the_manifest() {
        let project = game("idempotent");
        archive_in(&project, "scripts.rpa", &[("script.rpy", b"x")]);

        let first = unpack_archived_sources(&project).unwrap();
        let second = unpack_archived_sources(&project).unwrap();

        assert_eq!(first, second);
        assert_eq!(first.len(), 1);
    }

    #[test]
    fn the_manifest_is_written_in_the_python_shape() {
        let project = game("manifest");
        std::fs::write(project.join("game").join("script.rpyc"), "compiled").unwrap();
        archive_in(&project, "scripts.rpa", &[("script.rpy", b"x")]);

        unpack_archived_sources(&project).unwrap();

        let raw: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(manifest_path(&project)).unwrap())
                .unwrap();
        assert_eq!(raw["entries"][0]["path"], "script.rpy");
        assert_eq!(raw["entries"][0]["rpyc_preexisted"], true);
        assert!(raw["disabled_archives"].as_array().unwrap().is_empty());
    }

    #[test]
    fn detects_an_archive_holding_only_bytecode() {
        let project = game("bytecode");
        archive_in(&project, "scripts.rpa", &[("script.rpyc", b"bytes")]);
        assert!(archives_hold_only_compiled_scripts(&project).unwrap());
        assert!(unpack_archived_sources(&project).unwrap().is_empty());

        let other = game("no-bytecode");
        archive_in(&other, "images.rpa", &[("bg.png", b"png")]);
        assert!(!archives_hold_only_compiled_scripts(&other).unwrap());
    }

    #[test]
    fn bytecode_whose_source_is_archived_is_not_compiled_only() {
        let project = game("bytecode-with-source");
        archive_in(
            &project,
            "scripts.rpa",
            &[("script.rpy", b"x"), ("script.rpyc", b"bytes")],
        );
        assert!(!archives_hold_only_compiled_scripts(&project).unwrap());
    }

    #[test]
    fn a_source_left_on_disk_without_its_manifest_counts() {
        let project = game("source-on-disk");
        archive_in(
            &project,
            "scripts.rpa",
            &[("script.rpy", b"x"), ("script.rpyc", b"bytes")],
        );
        unpack_archived_sources(&project).unwrap();
        std::fs::remove_dir_all(project.join(".rts")).unwrap();

        assert!(unpack_archived_sources(&project).unwrap().is_empty());
        assert!(!archives_hold_only_compiled_scripts(&project).unwrap());
    }

    #[test]
    fn bytecode_with_only_its_source_on_disk_is_not_compiled_only() {
        let project = game("bytecode-source-on-disk");
        archive_in(&project, "scripts.rpa", &[("script.rpyc", b"bytes")]);
        std::fs::write(project.join("game").join("script.rpy"), "x").unwrap();
        assert!(!archives_hold_only_compiled_scripts(&project).unwrap());
    }

    #[test]
    fn a_script_only_archive_is_disabled_then_restored() {
        let project = game("disable");
        archive_in(&project, "scripts.rpa", &[("script.rpy", b"x")]);
        unpack_archived_sources(&project).unwrap();

        let renamed = disable_extracted_archives(&project).unwrap();

        assert_eq!(renamed, ["scripts.rpa"]);
        assert!(!project.join("game").join("scripts.rpa").exists());
        assert!(project.join("game").join("scripts.rpa.disabled").is_file());

        restore_disabled_archives(&project).unwrap();

        assert!(project.join("game").join("scripts.rpa").is_file());
        assert!(!project.join("game").join("scripts.rpa.disabled").exists());
        assert!(read_manifest(&project).disabled_archives.is_empty());
    }

    #[test]
    fn a_mixed_archive_stays_in_place() {
        let project = game("mixed");
        archive_in(
            &project,
            "assets.rpa",
            &[("script.rpy", b"x"), ("images/bg.png", b"png")],
        );
        unpack_archived_sources(&project).unwrap();

        assert!(disable_extracted_archives(&project).unwrap().is_empty());
        assert!(project.join("game").join("assets.rpa").is_file());
    }

    #[test]
    fn an_interrupted_run_is_repaired_by_the_next_unpack() {
        let project = game("interrupted");
        archive_in(&project, "scripts.rpa", &[("script.rpy", b"x")]);
        unpack_archived_sources(&project).unwrap();
        disable_extracted_archives(&project).unwrap();

        unpack_archived_sources(&project).unwrap();

        assert!(project.join("game").join("scripts.rpa").is_file());
    }

    #[test]
    fn discarding_removes_only_what_the_manifest_recorded() {
        let project = game("discard");
        archive_in(&project, "scripts.rpa", &[("broken.rpy", b"x")]);
        std::fs::write(project.join("game").join("mine.rpy"), "mine").unwrap();
        unpack_archived_sources(&project).unwrap();

        let discarded = discard_unpacked_files(
            &project,
            &["game/broken.rpy".to_string(), "game\\mine.rpy".to_string()],
        )
        .unwrap();

        assert_eq!(discarded, ["broken.rpy"]);
        assert!(!project.join("game").join("broken.rpy").exists());
        assert!(project.join("game").join("mine.rpy").is_file());
        assert!(read_manifest(&project).entries.is_empty());
    }

    #[test]
    fn a_forged_manifest_is_never_acted_on() {
        let project = game("forged");
        let victim = project.join("victim.rpy");
        std::fs::write(&victim, "keep").unwrap();
        std::fs::write(project.join("game").join("a.rpa"), "x").unwrap();
        std::fs::create_dir_all(project.join(".rts")).unwrap();
        std::fs::write(
            manifest_path(&project),
            r#"{"entries": [
                {"path": "../victim.rpy", "rpyc_preexisted": true},
                {"path": "ok.rpy", "rpyc_preexisted": true}],
              "disabled_archives": [
                {"archive": "../victim.rpy", "temp_name": "../victim.rpy"},
                {"archive": "a.rpa", "temp_name": "../victim.rpy"},
                {"archive": "a.rpa", "temp_name": "a.rpa.disabled"}]}"#,
        )
        .unwrap();

        let manifest = read_manifest(&project);

        assert_eq!(manifest.entries.len(), 1);
        assert_eq!(manifest.entries[0].path, "ok.rpy");
        assert_eq!(manifest.disabled_archives.len(), 1);
        remove_unpacked_sources(&project).unwrap();
        assert_eq!(std::fs::read_to_string(victim).unwrap(), "keep");
    }

    #[test]
    fn removing_the_unpacked_sources_keeps_the_rpyc_that_was_there() {
        let project = game("remove");
        std::fs::write(project.join("game").join("kept.rpyc"), "old").unwrap();
        archive_in(
            &project,
            "scripts.rpa",
            &[("kept.rpy", b"x"), ("deep/dir/new.rpy", b"y")],
        );
        unpack_archived_sources(&project).unwrap();
        std::fs::write(
            project
                .join("game")
                .join("deep")
                .join("dir")
                .join("new.rpyc"),
            "c",
        )
        .unwrap();
        disable_extracted_archives(&project).unwrap();

        remove_unpacked_sources(&project).unwrap();

        let game_dir = project.join("game");
        assert!(!game_dir.join("kept.rpy").exists());
        assert!(game_dir.join("kept.rpyc").is_file());
        assert!(!game_dir.join("deep").exists());
        assert!(game_dir.is_dir());
        assert!(game_dir.join("scripts.rpa").is_file());
        assert!(!manifest_path(&project).exists());
    }
}
