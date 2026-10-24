//! Input validation. Port of `core/validators.py`.

use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use regex::Regex;

use super::languages::get_language;

static LANGUAGE_CODE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[a-z][a-z0-9_]{1,31}$").unwrap());

/// Whether `code` is a Ren'Py language identifier (e.g. `french`).
///
/// The target language doubles as the `tl/<language>/` folder name, so it
/// accepts any filename-safe string, not necessarily a real language.
pub fn validate_language_code(code: &str) -> bool {
    LANGUAGE_CODE.is_match(code)
}

/// Whether `code` is a language providers know how to translate.
///
/// Machine translation and LLM providers only know the fixed set declared
/// in [`super::languages`], so this catches the mismatch before a job
/// silently fails (DeepL) or quietly degrades (an LLM guessing at an
/// unrecognized name).
pub fn is_recognized_language(code: &str) -> bool {
    get_language(code).is_some()
}

/// Whether a directory looks like a Ren'Py project: it holds `game/`.
pub fn validate_project_dir(path: &Path) -> bool {
    path.is_dir() && path.join("game").is_dir()
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
#[error("Path traversal detected: {0}")]
pub struct PathTraversal(pub String);

/// Resolve a path, refusing one that escapes `base`.
///
/// The path need not exist: the longest existing ancestor is resolved and
/// the rest is appended, so a member about to be created is checked too.
pub fn resolve_safe_path(user_path: &Path, base: Option<&Path>) -> Result<PathBuf, PathTraversal> {
    let resolved = resolve_lexically(user_path);
    if let Some(base) = base {
        if !resolved.starts_with(resolve_lexically(base)) {
            return Err(PathTraversal(user_path.display().to_string()));
        }
    }
    Ok(resolved)
}

fn resolve_lexically(path: &Path) -> PathBuf {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir().unwrap_or_default().join(path)
    };
    let mut parts: Vec<std::path::Component> = Vec::new();
    for component in absolute.components() {
        match component {
            std::path::Component::ParentDir => {
                if !matches!(
                    parts.last(),
                    None | Some(std::path::Component::RootDir | std::path::Component::Prefix(_))
                ) {
                    parts.pop();
                }
            }
            std::path::Component::CurDir => {}
            other => parts.push(other),
        }
    }
    let rebuilt: PathBuf = parts.iter().collect();
    let mut existing = rebuilt.clone();
    let mut tail: Vec<std::ffi::OsString> = Vec::new();
    while !existing.exists() {
        match existing.file_name() {
            Some(name) => tail.push(name.to_os_string()),
            None => break,
        }
        if !existing.pop() {
            break;
        }
    }
    let mut resolved = dunce::canonicalize(&existing).unwrap_or(existing);
    for name in tail.into_iter().rev() {
        resolved.push(name);
    }
    resolved
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("rts-validators-{name}-{nanos}"));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn language_codes_follow_the_folder_name_pattern() {
        assert!(validate_language_code("french"));
        assert!(validate_language_code("pt_br"));
        assert!(!validate_language_code("F"));
        assert!(!validate_language_code("French"));
        assert!(!validate_language_code("../x"));
        assert!(!validate_language_code(&"a".repeat(33)));
    }

    #[test]
    fn a_project_is_a_directory_holding_game() {
        let root = scratch("project");
        assert!(!validate_project_dir(&root));
        std::fs::create_dir_all(root.join("game")).unwrap();
        assert!(validate_project_dir(&root));
        assert!(!validate_project_dir(&root.join("missing")));
    }

    #[test]
    fn a_path_inside_the_base_resolves() {
        let base = scratch("inside");
        let target = base.join("game").join("script.rpy");
        assert_eq!(
            resolve_safe_path(&target, Some(&base)).unwrap(),
            dunce::canonicalize(&base)
                .unwrap()
                .join("game")
                .join("script.rpy")
        );
    }

    #[test]
    fn a_traversal_out_of_the_base_is_refused() {
        let base = scratch("outside");
        let escape = base.join("game").join("..").join("..").join("elsewhere");
        assert!(resolve_safe_path(&escape, Some(&base)).is_err());
    }

    #[test]
    fn without_a_base_any_path_resolves() {
        let root = scratch("free");
        assert!(resolve_safe_path(&root.join("x"), None).is_ok());
    }
}
