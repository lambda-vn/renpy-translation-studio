//! Translation zip exporter. Port of `core/exporter.py`.

use std::fs::File;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use regex::Regex;

static GAME_NAME_SANITIZE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[^a-zA-Z0-9_\-]").unwrap());
static BUILD_NAME: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"build\.name\s*=\s*["']([^"']+)["']"#).unwrap());

/// Determine and sanitize the game name.
///
/// Reads `build.name` from `game/options.rpy` when available; falls
/// back to the project directory's own name.
pub fn resolve_game_name(project_path: &Path) -> String {
    let name = read_build_name(project_path).unwrap_or_else(|| {
        project_path
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default()
    });
    GAME_NAME_SANITIZE.replace_all(&name, "-").into_owned()
}

/// The file name the export screen proposes for the zip:
/// `<game name>_<language>.zip`, the name sanitized with `_` (not the `-`
/// of [`resolve_game_name`]) and `game` when blank, `lang` when the
/// project records no target language.
pub fn zip_file_name(game_name: &str, language: &str) -> String {
    let trimmed = game_name.trim();
    let name =
        GAME_NAME_SANITIZE.replace_all(if trimmed.is_empty() { "game" } else { trimmed }, "_");
    let language = if language.is_empty() {
        "lang"
    } else {
        language
    };
    format!("{name}_{language}.zip")
}

fn read_build_name(project_path: &Path) -> Option<String> {
    let options = project_path.join("game").join("options.rpy");
    let content = std::fs::read_to_string(options).ok()?;
    BUILD_NAME
        .captures(&content)
        .map(|caps| caps[1].to_string())
}

#[derive(Debug, thiserror::Error)]
pub enum ExportError {
    #[error("path traversal detected: {0}")]
    PathTraversal(String),
    #[error("cannot walk {0}: {1}")]
    Walk(PathBuf, walkdir::Error),
    #[error("cannot read {0}: {1}")]
    Read(PathBuf, std::io::Error),
    #[error(transparent)]
    Zip(#[from] zip::result::ZipError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

/// Build a zip archive from a translation language directory.
///
/// The zip structure follows `<game_name>/game/tl/<language>/<file>`.
/// `.rpyc` files are skipped, and a zip entry name with a `..`
/// component refuses the whole export rather than let a stray symlink
/// under `tl_dir` write outside the archive's own prefix.
pub fn export(
    tl_dir: &Path,
    game_name: &str,
    language: &str,
    output_path: &Path,
) -> Result<(), ExportError> {
    let mut entries: Vec<PathBuf> = Vec::new();
    for entry in walkdir::WalkDir::new(tl_dir) {
        let entry = entry.map_err(|e| ExportError::Walk(tl_dir.to_path_buf(), e))?;
        if entry.file_type().is_file() {
            entries.push(entry.into_path());
        }
    }
    entries.sort();

    let file = File::create(output_path)?;
    let mut zip = zip::ZipWriter::new(file);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);

    for src in entries {
        if src.extension().is_some_and(|ext| ext == "rpyc") {
            continue;
        }
        let rel = src.strip_prefix(tl_dir).expect("walked under tl_dir");
        if rel.components().any(|c| c.as_os_str() == "..") {
            return Err(ExportError::PathTraversal(rel.display().to_string()));
        }
        let rel_posix: Vec<String> = rel
            .components()
            .map(|c| c.as_os_str().to_string_lossy().into_owned())
            .collect();
        let arc_name = format!("{game_name}/game/tl/{language}/{}", rel_posix.join("/"));

        zip.start_file(&arc_name, options)?;
        let mut content = Vec::new();
        File::open(&src)
            .and_then(|mut f| f.read_to_end(&mut content))
            .map_err(|e| ExportError::Read(src.clone(), e))?;
        zip.write_all(&content)?;
    }
    zip.finish()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(name: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!(
            "rts-exporter-test-{name}-{nanos}-{:?}",
            std::thread::current().id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn resolve_game_name_reads_build_name_from_options() {
        let project = temp_dir("game-name");
        std::fs::create_dir_all(project.join("game")).unwrap();
        std::fs::write(
            project.join("game").join("options.rpy"),
            "define build.name = \"My Game!\"\n",
        )
        .unwrap();

        assert_eq!(resolve_game_name(&project), "My-Game-");
    }

    #[test]
    fn zip_file_name_sanitizes_with_underscores() {
        assert_eq!(zip_file_name("My Game!", "french"), "My_Game__french.zip");
        assert_eq!(zip_file_name("  ", "french"), "game_french.zip");
        assert_eq!(zip_file_name("Game", ""), "Game_lang.zip");
    }

    #[test]
    fn resolve_game_name_falls_back_to_directory_name() {
        let project = temp_dir("fallback").join("Some Game 2");
        assert_eq!(resolve_game_name(&project), "Some-Game-2");
    }

    #[test]
    fn export_builds_the_expected_zip_layout() {
        let tl_dir = temp_dir("tl-src");
        std::fs::create_dir_all(tl_dir.join("common")).unwrap();
        std::fs::write(tl_dir.join("script.rpy"), "translate french start_x:\n").unwrap();
        std::fs::write(
            tl_dir.join("common").join("common.rpy"),
            "translate french strings:\n",
        )
        .unwrap();
        std::fs::write(tl_dir.join("script.rpyc"), b"compiled, skipped").unwrap();

        let output = temp_dir("out").join("game_french.zip");
        export(&tl_dir, "My-Game", "french", &output).unwrap();

        let file = File::open(&output).unwrap();
        let mut archive = zip::ZipArchive::new(file).unwrap();
        let mut names: Vec<String> = (0..archive.len())
            .map(|i| archive.by_index(i).unwrap().name().to_string())
            .collect();
        names.sort();
        assert_eq!(
            names,
            vec![
                "My-Game/game/tl/french/common/common.rpy".to_string(),
                "My-Game/game/tl/french/script.rpy".to_string(),
            ]
        );
    }
}
