//! Global registry of recently parsed projects.
//!
//! Port of `core/storage/recent_projects.py`. Stores only the absolute
//! paths of projects that have been extracted or resumed, as a JSON list
//! in the application config directory (next to `settings.json`). All
//! display data (game name, language, counts) is read live from each
//! project's own database and is never duplicated here.
//!
//! Python holds this behind a `RecentProjects` instance with a default
//! path baked in; every function here instead takes the registry path
//! explicitly, so a test never has to touch the real machine-wide file.

use std::fs;
use std::path::{Path, PathBuf};

/// Where the registry lives on this machine: `<config_dir>/projects.json`.
pub fn default_path() -> PathBuf {
    crate::core::settings::config_dir().join("projects.json")
}

/// Return the stored project paths, most recently added first.
///
/// A missing or unreadable file yields an empty list rather than an
/// error.
pub fn all(registry: &Path) -> Vec<PathBuf> {
    let Ok(contents) = fs::read_to_string(registry) else {
        return Vec::new();
    };
    let Ok(entries) = serde_json::from_str::<Vec<String>>(&contents) else {
        return Vec::new();
    };
    entries.into_iter().map(PathBuf::from).collect()
}

/// Register a project path, moving it to the front if already present.
pub fn add(registry: &Path, project: &Path) {
    let resolved = resolve(project);
    let mut entries: Vec<PathBuf> = all(registry)
        .into_iter()
        .filter(|p| *p != resolved)
        .collect();
    entries.insert(0, resolved);
    save(registry, &entries);
}

/// Drop a project path from the registry.
pub fn remove(registry: &Path, project: &Path) {
    let resolved = resolve(project);
    let entries: Vec<PathBuf> = all(registry)
        .into_iter()
        .filter(|p| *p != resolved)
        .collect();
    save(registry, &entries);
}

/// Normalize a path the way Python's `Path.resolve()` does: absolute
/// whether or not it exists, and — on Windows — without the `\\?\`
/// extended-length prefix `std::fs::canonicalize` adds, which
/// `Path.resolve()` never does. A `source_file` stored by the Python
/// application is a plain drive path; comparing it against a
/// `\\?\`-prefixed one would silently break every relative-path
/// computation the MCP server does, `dunce` existing for exactly this
/// mismatch. `canonicalize()` alone would also refuse a project folder
/// that has since been moved or deleted.
pub fn resolve(path: &Path) -> PathBuf {
    dunce::canonicalize(path).unwrap_or_else(|_| {
        if path.is_absolute() {
            path.to_path_buf()
        } else {
            std::env::current_dir()
                .map(|cwd| cwd.join(path))
                .unwrap_or_else(|_| path.to_path_buf())
        }
    })
}

fn save(registry: &Path, entries: &[PathBuf]) {
    if let Some(parent) = registry.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let strings: Vec<String> = entries
        .iter()
        .map(|p| p.to_string_lossy().into_owned())
        .collect();
    if let Ok(json) = serde_json::to_string_pretty(&strings) {
        let _ = fs::write(registry, json);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_registry() -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "rts-recent-projects-test-{nanos}-{:?}.json",
            std::thread::current().id()
        ))
    }

    #[test]
    fn missing_file_yields_empty_list() {
        let registry = temp_registry();
        assert!(all(&registry).is_empty());
    }

    #[test]
    fn add_moves_existing_entry_to_front() {
        let registry = temp_registry();
        let a = std::env::temp_dir().join("game-a");
        let b = std::env::temp_dir().join("game-b");
        add(&registry, &a);
        add(&registry, &b);
        add(&registry, &a);

        let entries = all(&registry);
        assert_eq!(entries, vec![resolve(&a), resolve(&b)]);
    }

    #[test]
    fn remove_drops_the_entry() {
        let registry = temp_registry();
        let a = std::env::temp_dir().join("game-a");
        let b = std::env::temp_dir().join("game-b");
        add(&registry, &a);
        add(&registry, &b);

        remove(&registry, &a);

        assert_eq!(all(&registry), vec![resolve(&b)]);
    }

    #[test]
    fn garbage_file_yields_empty_list_rather_than_erroring() {
        let registry = temp_registry();
        fs::write(&registry, "not json").unwrap();
        assert!(all(&registry).is_empty());
    }
}
