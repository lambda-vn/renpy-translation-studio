//! Selective extraction of `.rpy` sources from `.rpa` archives. Port of
//! `core/renpy/unpacker.py`.
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
//! in the same shape the Python application writes, so that each side can
//! clean up after the other.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use super::archive::{ArchiveError, RpaArchive};
use crate::core::validators::resolve_safe_path;

const DISABLED_SUFFIX: &str = ".disabled";
const EXTRACTABLE_SUFFIXES: [&str; 2] = ["rpy", "rpym"];
const SCRIPT_SUFFIXES: [&str; 4] = ["rpy", "rpym", "rpyc", "rpymc"];

fn manifest_path(project: &Path) -> PathBuf {
    project.join(".rts").join("unpacked_sources.json")
}

/// A single source file extracted from an `.rpa` archive.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UnpackedEntry {
    pub path: String,
    pub rpyc_preexisted: bool,
}

/// An archive temporarily renamed out of Ren'Py's search path.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DisabledArchive {
    pub archive: String,
    pub temp_name: String,
}

#[derive(Debug, Default, Serialize)]
struct Manifest {
    entries: Vec<UnpackedEntry>,
    disabled_archives: Vec<DisabledArchive>,
}

/// Read a previously written manifest, an empty one if absent or unreadable.
/// Entries of an unexpected shape are dropped one by one, as the Python
/// reader does, rather than failing the whole file.
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
            .filter_map(|item| serde_json::from_value(item).ok())
            .collect(),
        disabled_archives: items("disabled_archives")
            .into_iter()
            .filter_map(|item| serde_json::from_value(item).ok())
            .collect(),
    }
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
pub fn unpack_archived_sources(project: &Path) -> Result<Vec<UnpackedEntry>, ArchiveError> {
    restore_disabled_archives(project)?;

    let game_dir = project.join("game");
    let manifest = read_manifest(project);
    let mut entries: BTreeMap<String, UnpackedEntry> = manifest
        .entries
        .into_iter()
        .map(|entry| (entry.path.clone(), entry))
        .collect();

    for archive_path in rpa_files(&game_dir) {
        let mut archive = RpaArchive::open(&archive_path)?;
        for name in archive.names().to_vec() {
            if !is_extractable(&name) {
                continue;
            }
            let target = resolve_target(&game_dir, &name)?;
            if target.exists() {
                continue;
            }
            let rpyc_preexisted = target.with_extension("rpyc").exists();
            if let Some(parent) = target.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(&target, archive.read(&name)?)?;
            entries.insert(
                name.clone(),
                UnpackedEntry {
                    path: name,
                    rpyc_preexisted,
                },
            );
        }
    }

    let entries: Vec<UnpackedEntry> = entries.into_values().collect();
    if !entries.is_empty() || !manifest.disabled_archives.is_empty() {
        write_manifest(
            project,
            &Manifest {
                entries: entries.clone(),
                disabled_archives: manifest.disabled_archives,
            },
        )?;
    }
    Ok(entries)
}

/// Whether `game/`'s archives hold a compiled script (`.rpyc`) outside `tl/`.
///
/// Tells apart a game with no archived scripts at all, the common case
/// where extraction has nothing to do, from one shipping only bytecode: no
/// amount of extraction recovers a source from a `.rpyc`, a decompiler
/// would be needed instead.
pub fn archives_contain_compiled_scripts(project: &Path) -> Result<bool, ArchiveError> {
    for archive_path in rpa_files(&project.join("game")) {
        let archive = RpaArchive::open(&archive_path)?;
        if archive
            .names()
            .iter()
            .any(|name| first_segment(name) != "tl" && has_suffix(name, &["rpyc"]))
        {
            return Ok(true);
        }
    }
    Ok(false)
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
pub fn disable_extracted_archives(project: &Path) -> Result<Vec<String>, ArchiveError> {
    let game_dir = project.join("game");
    let mut manifest = read_manifest(project);
    let unpacked: std::collections::HashSet<&str> =
        manifest.entries.iter().map(|e| e.path.as_str()).collect();

    let mut renamed = Vec::new();
    let mut disabled = Vec::new();
    for archive_path in rpa_files(&game_dir) {
        let names = RpaArchive::open(&archive_path)?.names().to_vec();
        if !names.iter().any(|name| unpacked.contains(name.as_str())) {
            continue;
        }
        if !names.iter().all(|name| has_suffix(name, &SCRIPT_SUFFIXES)) {
            continue;
        }
        let temp_path = disabled_path(&archive_path);
        std::fs::rename(&archive_path, &temp_path)?;
        let file_name = |path: &Path| {
            path.file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default()
        };
        disabled.push(DisabledArchive {
            archive: file_name(&archive_path),
            temp_name: file_name(&temp_path),
        });
        renamed.push(file_name(&archive_path));
    }

    if !renamed.is_empty() {
        manifest.disabled_archives.extend(disabled);
        write_manifest(project, &manifest)?;
    }
    Ok(renamed)
}

/// Rename every archive [`disable_extracted_archives`] renamed, back.
///
/// Must run whether the Ren'Py run that followed succeeded or failed: the
/// game itself reads these archives too, and nothing outside this
/// application knows to look for the temporary name. Safe to call when
/// nothing is disabled.
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
        assert!(archives_contain_compiled_scripts(&project).unwrap());
        assert!(unpack_archived_sources(&project).unwrap().is_empty());

        let other = game("no-bytecode");
        archive_in(&other, "images.rpa", &[("bg.png", b"png")]);
        assert!(!archives_contain_compiled_scripts(&other).unwrap());
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
