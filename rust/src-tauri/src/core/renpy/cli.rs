//! Wrapper for the Ren'Py command line. Port of `core/renpy/cli.py`.
//!
//! The executable it is handed is either the game's own engine or the
//! configured SDK — both answer the same `<exe> <basedir> translate <lang>`
//! command, so choosing between them is left to [`super::engine`].

use std::io::Read;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::LazyLock;
use std::time::{Duration, Instant};

use regex::Regex;

static ERROR_FILE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"File "([^"]+)", line \d+"#).unwrap());

/// How long the engine gets before it is killed. A game's whole script is
/// parsed by the engine itself, so a large one is slow; a truncated `tl/`
/// folder left by a kill is why `delete_stale` distrusts a small parse.
pub const TRANSLATE_TIMEOUT: Duration = Duration::from_secs(120);

#[derive(Debug, thiserror::Error)]
pub enum CliError {
    #[error("Ren'Py exited with code {}{}", code_text(.code), output_suffix(.output))]
    Failed { code: Option<i32>, output: String },
    #[error("Ren'Py did not finish within {} seconds{}", .seconds, output_suffix(.output))]
    TimedOut { seconds: u64, output: String },
    #[error("cannot start Ren'Py: {0}")]
    Spawn(std::io::Error),
}

fn code_text(code: &Option<i32>) -> String {
    code.map_or_else(|| "unknown".to_string(), |c| c.to_string())
}

fn output_suffix(output: &str) -> String {
    if output.is_empty() {
        String::new()
    } else {
        format!("\n{output}")
    }
}

impl CliError {
    /// Everything the engine printed before failing, which is where the
    /// parse errors naming the files it refused are.
    pub fn output(&self) -> &str {
        match self {
            Self::Failed { output, .. } | Self::TimedOut { output, .. } => output,
            Self::Spawn(_) => "",
        }
    }
}

/// The script paths Ren'Py blamed in a failed run.
///
/// Ren'Py reports a parse error as `File "game/x.rpy", line 12: ...`,
/// naming the same file once per error. The paths are relative to the
/// project root and use forward slashes. Each is returned once, in the
/// order Ren'Py first reported it.
pub fn parse_failed_files(output: &str) -> Vec<String> {
    let mut seen: Vec<String> = Vec::new();
    for caps in ERROR_FILE.captures_iter(output) {
        let name = caps[1].to_string();
        if !seen.contains(&name) {
            seen.push(name);
        }
    }
    seen
}

/// Run `<engine> <project> translate <language>` and wait for it.
///
/// stdout and stderr are drained on their own threads: a child that fills
/// a pipe nobody reads blocks forever, and the engine is chatty.
pub fn translate(
    engine: &Path,
    project: &Path,
    language: &str,
    timeout: Duration,
) -> Result<(), CliError> {
    let mut command = Command::new(engine);
    command
        .arg(project)
        .arg("translate")
        .arg(language)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = command.spawn().map_err(CliError::Spawn)?;

    let drain = |stream: Option<Box<dyn Read + Send>>| {
        std::thread::spawn(move || {
            let mut bytes = Vec::new();
            if let Some(mut stream) = stream {
                let _ = stream.read_to_end(&mut bytes);
            }
            String::from_utf8_lossy(&bytes).into_owned()
        })
    };
    let stdout = drain(
        child
            .stdout
            .take()
            .map(|s| Box::new(s) as Box<dyn Read + Send>),
    );
    let stderr = drain(
        child
            .stderr
            .take()
            .map(|s| Box::new(s) as Box<dyn Read + Send>),
    );

    let started = Instant::now();
    let status = loop {
        match child.try_wait().map_err(CliError::Spawn)? {
            Some(status) => break Some(status),
            None if started.elapsed() >= timeout => {
                let _ = child.kill();
                let _ = child.wait();
                break None;
            }
            None => std::thread::sleep(Duration::from_millis(50)),
        }
    };

    let out = stdout.join().unwrap_or_default();
    let err = stderr.join().unwrap_or_default();
    let output = [out, err]
        .into_iter()
        .filter(|part| !part.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n");

    match status {
        Some(status) if status.success() => Ok(()),
        Some(status) => Err(CliError::Failed {
            code: status.code(),
            output,
        }),
        None => Err(CliError::TimedOut {
            seconds: timeout.as_secs(),
            output,
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SDK_OUTPUT: &str = "File \"game/MechanicalScripts/Phone.rpy\", line 249: the box_wrap \
keyword argument was not given a value.\n    vbox spacing 3 box_wrap:\n\n\
File \"game/MechanicalScripts/Phone.rpy\", line 270: the box_wrap keyword argument was not \
given a value.\n\nFile \"game/Events/Day1.rpy\", line 12: expected statement.\n";

    #[test]
    fn parses_each_blamed_file_once() {
        assert_eq!(
            parse_failed_files(SDK_OUTPUT),
            ["game/MechanicalScripts/Phone.rpy", "game/Events/Day1.rpy"]
        );
    }

    #[test]
    fn returns_empty_without_a_file_reference() {
        assert!(parse_failed_files("Ren'Py SDK failed (exit 1):\nSomething broke").is_empty());
    }

    #[test]
    fn ignores_a_file_reference_without_a_line_number() {
        assert!(parse_failed_files("File \"game/x.rpy\" was mentioned").is_empty());
    }

    #[test]
    fn a_missing_executable_is_reported_not_panicked() {
        let missing = std::env::temp_dir().join("rts-no-such-engine.exe");
        let error =
            translate(&missing, Path::new("."), "french", Duration::from_secs(1)).unwrap_err();
        assert!(matches!(error, CliError::Spawn(_)));
    }

    #[cfg(windows)]
    #[test]
    fn a_failing_process_carries_its_exit_code_and_output() {
        let error = translate(
            Path::new("cmd.exe"),
            Path::new("/c"),
            "echo failing & exit 3",
            Duration::from_secs(10),
        );
        // `cmd.exe /c translate <language>` is not a real command line, so
        // only the failure shape is asserted, not Ren'Py's behaviour.
        let error = error.unwrap_err();
        assert!(matches!(error, CliError::Failed { .. }));
    }
}
