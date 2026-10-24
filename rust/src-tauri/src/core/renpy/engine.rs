//! Detection of the Ren'Py engine a game ships with. Port of
//! `core/renpy/engine.py`.
//!
//! A packaged Ren'Py game carries its own engine, and that engine answers
//! the same `translate` command as the SDK. It is also the *right* engine
//! by construction: it is the version the game's sources were written for.
//! The SDK installed on the machine is some other version, and Ren'Py 8
//! refuses screen syntax Ren'Py 7 accepted (a property without a value),
//! so extracting a Ren'Py 7 game with the SDK 8 loses every line of the
//! sources it rejects.
//!
//! Finding the launcher is not enough to know it will run: a `-win` build
//! ships Windows runtimes only. The proof lives in `lib/`, one directory
//! per platform the build was made for, so that is what gets tested
//! rather than the mere presence of the executable.
//!
//! Every function takes the platform as an argument and has a thin
//! counterpart for the running one, which is how the three systems are
//! tested from any of them.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Platform {
    Windows,
    Linux,
    Mac,
}

impl Platform {
    /// The platform of the running system, `None` on anything no Ren'Py
    /// build ships a runtime for.
    pub fn current() -> Option<Self> {
        if cfg!(target_os = "windows") {
            Some(Self::Windows)
        } else if cfg!(target_os = "linux") {
            Some(Self::Linux)
        } else if cfg!(target_os = "macos") {
            Some(Self::Mac)
        } else {
            None
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Windows => "Windows",
            Self::Linux => "Linux",
            Self::Mac => "macOS",
        }
    }

    fn token(self) -> &'static str {
        match self {
            Self::Windows => "windows",
            Self::Linux => "linux",
            Self::Mac => "mac",
        }
    }

    fn launcher_suffixes(platform: Option<Self>) -> [&'static str; 2] {
        match platform {
            Some(Self::Windows) => ["exe", "sh"],
            Some(Self::Linux) | Some(Self::Mac) => ["sh", "exe"],
            None => ["exe", "sh"],
        }
    }
}

const ALL_PLATFORMS: [Platform; 3] = [Platform::Windows, Platform::Linux, Platform::Mac];

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum EngineError {
    /// The folder ships no engine and no usable SDK is configured.
    #[error("No Ren'Py engine can run here: this game ships none and no SDK is configured")]
    NotFound,
    /// The folder ships an engine, but only for other systems.
    #[error(
        "This game's own engine was built for {platforms}, which this system cannot run, \
         and no Ren'Py SDK is configured"
    )]
    WrongPlatform { platforms: String },
}

/// The launcher of the game's own engine, if the folder has one.
///
/// The search is ordered by `platform` but never restricted to it: a
/// launcher found for another platform is what lets the caller say "this
/// is a Windows build" rather than "nothing found here".
///
/// A file only counts as a launcher when a `<stem>.py` sits beside it, the
/// entry point every Ren'Py build ships next to its per-platform
/// launchers. Without that pairing the choice would come down to
/// alphabetical order, so an unrelated executable left in the folder, an
/// installer or an unpacking tool, could win it and then be run.
///
/// That `.py` marks the game but is never returned as the launcher: it
/// needs the interpreter the wrappers bring along.
///
/// A `-32.exe` is skipped: it is the 32-bit twin of the launcher next to
/// it, never the only one.
pub fn find_game_launcher_for(project: &Path, platform: Option<Platform>) -> Option<PathBuf> {
    if !project.join("renpy").is_dir() || !project.join("lib").is_dir() {
        return None;
    }
    let entries: Vec<PathBuf> = std::fs::read_dir(project)
        .ok()?
        .filter_map(|entry| entry.ok().map(|e| e.path()))
        .filter(|path| path.is_file())
        .collect();
    for suffix in Platform::launcher_suffixes(platform) {
        let mut candidates: Vec<&PathBuf> = entries
            .iter()
            .filter(|path| {
                path.extension()
                    .is_some_and(|ext| ext.eq_ignore_ascii_case(suffix))
                    && !path
                        .file_stem()
                        .is_some_and(|stem| stem.to_string_lossy().ends_with("-32"))
                    && path.with_extension("py").is_file()
            })
            .collect();
        candidates.sort();
        if let Some(first) = candidates.first() {
            return Some((*first).clone());
        }
    }
    None
}

pub fn find_game_launcher(project: &Path) -> Option<PathBuf> {
    find_game_launcher_for(project, Platform::current())
}

/// The platforms the game's bundled engine can run on, read from the names
/// of the `lib/` subdirectories, which a build carries one of per platform
/// it targets: a `-win` build holds `py2-windows-i686` and
/// `py2-windows-x86_64`, a `-pc` build adds `py3-linux-x86_64`.
pub fn game_platforms(project: &Path) -> BTreeSet<Platform> {
    let Ok(entries) = std::fs::read_dir(project.join("lib")) else {
        return BTreeSet::new();
    };
    let mut found = BTreeSet::new();
    for entry in entries.filter_map(Result::ok) {
        if !entry.path().is_dir() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_lowercase();
        for platform in ALL_PLATFORMS {
            if name.contains(platform.token()) {
                found.insert(platform);
            }
        }
    }
    found
}

/// Whether the game's own engine is usable for the extraction: the folder
/// ships a launcher and a runtime for `platform`.
pub fn can_use_game_engine_for(project: &Path, platform: Option<Platform>) -> bool {
    find_game_launcher_for(project, platform).is_some()
        && platform.is_some_and(|p| game_platforms(project).contains(&p))
}

pub fn can_use_game_engine(project: &Path) -> bool {
    can_use_game_engine_for(project, Platform::current())
}

/// The executable that will run the translate command.
///
/// The game's own engine comes first, the configured SDK is the fallback,
/// and the failure names which of the two situations was hit so the user
/// knows whether selecting an SDK is what is missing.
pub fn resolve_engine_for(
    project: &Path,
    sdk_path: Option<&Path>,
    platform: Option<Platform>,
) -> Result<PathBuf, EngineError> {
    let launcher = find_game_launcher_for(project, platform);
    let platforms = game_platforms(project);
    if let Some(launcher) = &launcher {
        if platform.is_some_and(|p| platforms.contains(&p)) {
            return Ok(launcher.clone());
        }
    }
    if let Some(sdk) = sdk_path {
        if sdk.is_file() {
            return Ok(sdk.to_path_buf());
        }
    }
    if launcher.is_some() && !platforms.is_empty() {
        let labels: Vec<&str> = platforms.iter().map(|p| p.label()).collect();
        return Err(EngineError::WrongPlatform {
            platforms: labels.join(", "),
        });
    }
    Err(EngineError::NotFound)
}

pub fn resolve_engine(project: &Path, sdk_path: Option<&Path>) -> Result<PathBuf, EngineError> {
    resolve_engine_for(project, sdk_path, Platform::current())
}

#[cfg(test)]
mod tests {
    use super::*;

    const WIN_LIB: [&str; 3] = ["py2-windows-i686", "py2-windows-x86_64", "python2.7"];
    const PC_LIB: [&str; 3] = ["py3-linux-x86_64", "py3-windows-x86_64", "python3.9"];

    fn scratch(name: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("rts-engine-{name}-{nanos}"));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    /// A folder shaped like a packaged Ren'Py game.
    fn make_game(root: &Path, launchers: &[&str], lib_dirs: &[&str], with_renpy: bool) -> PathBuf {
        std::fs::create_dir_all(root.join("game")).unwrap();
        if with_renpy {
            std::fs::create_dir_all(root.join("renpy")).unwrap();
        }
        std::fs::create_dir_all(root.join("lib")).unwrap();
        for name in lib_dirs {
            std::fs::create_dir_all(root.join("lib").join(name)).unwrap();
        }
        for name in launchers {
            std::fs::write(root.join(name), b"").unwrap();
        }
        root.to_path_buf()
    }

    #[test]
    fn finds_the_windows_launcher_and_skips_the_32_bit_twin() {
        let game = make_game(
            &scratch("twin"),
            &["Stormside-32.exe", "Stormside.exe", "Stormside.py"],
            &WIN_LIB,
            true,
        );
        assert_eq!(
            find_game_launcher_for(&game, Some(Platform::Windows)),
            Some(game.join("Stormside.exe"))
        );
    }

    #[test]
    fn prefers_the_shell_launcher_on_linux() {
        let game = make_game(
            &scratch("sh"),
            &["Red_Veil.exe", "Red_Veil.sh", "Red_Veil.py"],
            &PC_LIB,
            true,
        );
        assert_eq!(
            find_game_launcher_for(&game, Some(Platform::Linux)),
            Some(game.join("Red_Veil.sh"))
        );
    }

    #[test]
    fn finds_a_launcher_meant_for_another_platform() {
        let game = make_game(
            &scratch("foreign"),
            &["Stormside.exe", "Stormside.py"],
            &WIN_LIB,
            true,
        );
        assert_eq!(
            find_game_launcher_for(&game, Some(Platform::Linux)),
            Some(game.join("Stormside.exe"))
        );
    }

    #[test]
    fn ignores_an_executable_without_its_python_twin() {
        let game = make_game(
            &scratch("unpaired"),
            &["AAAUnRen.exe", "Stormside.exe", "Stormside.py"],
            &WIN_LIB,
            true,
        );
        assert_eq!(
            find_game_launcher_for(&game, Some(Platform::Windows)),
            Some(game.join("Stormside.exe"))
        );
    }

    #[test]
    fn ignores_a_folder_holding_only_an_unpaired_executable() {
        let game = make_game(&scratch("tool-only"), &["UnRen.exe"], &WIN_LIB, true);
        assert_eq!(find_game_launcher_for(&game, Some(Platform::Windows)), None);
    }

    #[test]
    fn ignores_a_folder_without_the_engine_directories() {
        let game = make_game(&scratch("stray"), &["build.py"], &[], false);
        assert_eq!(find_game_launcher_for(&game, Some(Platform::Linux)), None);
    }

    #[test]
    fn reads_the_platforms_from_the_lib_folder() {
        let game = make_game(&scratch("lib"), &["Red_Veil.sh"], &PC_LIB, true);
        assert_eq!(
            game_platforms(&game),
            BTreeSet::from([Platform::Windows, Platform::Linux])
        );
    }

    #[test]
    fn reports_no_platform_without_a_lib_folder() {
        let root = scratch("nolib");
        std::fs::create_dir_all(root.join("game")).unwrap();
        assert!(game_platforms(&root).is_empty());
    }

    #[test]
    fn a_windows_build_is_unusable_on_linux_and_usable_on_windows() {
        let game = make_game(
            &scratch("usable"),
            &["Stormside.exe", "Stormside.py"],
            &WIN_LIB,
            true,
        );
        assert!(!can_use_game_engine_for(&game, Some(Platform::Linux)));
        assert!(can_use_game_engine_for(&game, Some(Platform::Windows)));
    }

    #[test]
    fn resolves_to_the_game_engine_over_the_sdk() {
        let root = scratch("prefer");
        let game = make_game(
            &root.join("game-root"),
            &["Stormside.exe", "Stormside.py"],
            &WIN_LIB,
            true,
        );
        let sdk = root.join("renpy.exe");
        std::fs::write(&sdk, b"").unwrap();
        assert_eq!(
            resolve_engine_for(&game, Some(&sdk), Some(Platform::Windows)),
            Ok(game.join("Stormside.exe"))
        );
    }

    #[test]
    fn falls_back_to_the_sdk_for_a_foreign_build() {
        let root = scratch("fallback");
        let game = make_game(
            &root.join("game-root"),
            &["Stormside.exe", "Stormside.py"],
            &WIN_LIB,
            true,
        );
        let sdk = root.join("renpy.sh");
        std::fs::write(&sdk, b"").unwrap();
        assert_eq!(
            resolve_engine_for(&game, Some(&sdk), Some(Platform::Linux)),
            Ok(sdk)
        );
    }

    #[test]
    fn names_the_platform_of_the_build_it_cannot_run() {
        let game = make_game(
            &scratch("named"),
            &["Stormside.exe", "Stormside.py"],
            &WIN_LIB,
            true,
        );
        let error = resolve_engine_for(&game, None, Some(Platform::Linux)).unwrap_err();
        assert_eq!(
            error,
            EngineError::WrongPlatform {
                platforms: "Windows".to_string()
            }
        );
        assert!(error.to_string().contains("Windows"));
    }

    #[test]
    fn refuses_a_folder_holding_neither_engine_nor_sdk() {
        let root = scratch("nothing");
        std::fs::create_dir_all(root.join("game")).unwrap();
        assert_eq!(
            resolve_engine_for(&root, None, Some(Platform::Linux)),
            Err(EngineError::NotFound)
        );
    }

    #[test]
    fn ignores_an_sdk_path_that_is_not_a_file() {
        let root = scratch("gone");
        std::fs::create_dir_all(root.join("game")).unwrap();
        let missing = root.join("gone").join("renpy.sh");
        assert_eq!(
            resolve_engine_for(&root, Some(&missing), Some(Platform::Linux)),
            Err(EngineError::NotFound)
        );
    }
}
