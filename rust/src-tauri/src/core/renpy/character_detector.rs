//! Heuristic scanner for Ren'Py `Character()` definitions. Port of
//! `core/renpy/character_detector.py`.
//!
//! Results are heuristic: the user reads them before relying on them.
//! The `tl/` directory is not scanned, being generated output.

use std::collections::HashSet;
use std::path::Path;
use std::sync::LazyLock;

use regex::Regex;

static DEFINE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"define\s+(\w+)\s*=\s*Character\(\s*[_(]*["']([^"']+)["']"#).unwrap()
});
static ASSIGNMENT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?m)^(\w+)\s*=\s*Character\(\s*[_(]*["']([^"']+)["']"#).unwrap()
});

/// A character definition found while scanning source files.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DetectedCharacter {
    pub variable: String,
    pub display_name: String,
    /// Path of the defining file, relative to the project root.
    pub source_file: String,
}

/// Every character defined in the project's `.rpy` sources, one per
/// variable, the first match winning. Files are visited in path order so
/// that "first" means the same thing on every run.
pub fn detect(project: &Path) -> Vec<DetectedCharacter> {
    let source_dir = project.join("game");
    let tl_dir = source_dir.join("tl");

    let mut files: Vec<_> = walkdir::WalkDir::new(&source_dir)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_file()
                && entry.path().extension().is_some_and(|ext| ext == "rpy")
                && !entry.path().starts_with(&tl_dir)
        })
        .map(|entry| entry.into_path())
        .collect();
    files.sort();

    let mut seen: HashSet<String> = HashSet::new();
    let mut found = Vec::new();
    for file in files {
        let Ok(bytes) = std::fs::read(&file) else {
            continue;
        };
        let content = String::from_utf8_lossy(&bytes);
        let relative = file
            .strip_prefix(project)
            .unwrap_or(&file)
            .to_string_lossy()
            .into_owned();
        for pattern in [&*DEFINE, &*ASSIGNMENT] {
            for caps in pattern.captures_iter(&content) {
                let variable = caps[1].to_string();
                if seen.insert(variable.clone()) {
                    found.push(DetectedCharacter {
                        variable,
                        display_name: caps[2].to_string(),
                        source_file: relative.clone(),
                    });
                }
            }
        }
    }
    found
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use super::*;

    fn project(name: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("rts-detector-{name}-{nanos}"));
        std::fs::create_dir_all(dir.join("game")).unwrap();
        dir
    }

    fn write(path: &Path, content: &str) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, content).unwrap();
    }

    #[test]
    fn detects_a_define_character() {
        let dir = project("define");
        write(
            &dir.join("game").join("script.rpy"),
            "define e = Character(\"Eileen\")\n",
        );
        let found = detect(&dir);
        assert_eq!(found.len(), 1);
        assert_eq!(
            (found[0].variable.as_str(), found[0].display_name.as_str()),
            ("e", "Eileen")
        );
    }

    #[test]
    fn detects_a_bare_assignment_and_translated_names() {
        let dir = project("bare");
        write(
            &dir.join("game").join("script.rpy"),
            "m = Character(\"Mary\")\ndefine t = Character(_(\"Tom\"), color=\"#fff\")\n",
        );
        let found = detect(&dir);
        let names: Vec<_> = found
            .iter()
            .map(|c| (c.variable.as_str(), c.display_name.as_str()))
            .collect();
        assert!(names.contains(&("m", "Mary")));
        assert!(names.contains(&("t", "Tom")));
    }

    #[test]
    fn the_tl_directory_is_not_scanned() {
        let dir = project("tl");
        write(
            &dir.join("game").join("script.rpy"),
            "define e = Character(\"Eileen\")\n",
        );
        write(
            &dir.join("game")
                .join("tl")
                .join("french")
                .join("script.rpy"),
            "define e = Character(\"Eileen FR\")\n",
        );
        let found = detect(&dir);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].display_name, "Eileen");
    }

    #[test]
    fn the_first_match_wins() {
        let dir = project("dedup");
        write(
            &dir.join("game").join("script.rpy"),
            "define e = Character(\"Eileen\")\ndefine e = Character(\"Eileen Again\")\n",
        );
        let found = detect(&dir);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].display_name, "Eileen");
    }

    #[test]
    fn the_source_file_is_relative_to_the_project() {
        let dir = project("relative");
        write(
            &dir.join("game").join("chapter1.rpy"),
            "define e = Character(\"Eileen\")\n",
        );
        let found = detect(&dir);
        assert_eq!(
            PathBuf::from(&found[0].source_file),
            PathBuf::from("game").join("chapter1.rpy")
        );
    }

    #[test]
    fn a_script_without_characters_yields_nothing() {
        let dir = project("none");
        write(
            &dir.join("game").join("script.rpy"),
            "label start:\n    \"Hello\"\n",
        );
        assert!(detect(&dir).is_empty());
    }
}
