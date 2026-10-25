//! The application log. Port of `core/logging_config.py`.
//!
//! Python wrote to the console, which a packaged desktop application does
//! not have: this writes to `<config_dir>/renpy-translation-studio.log`
//! instead. As in 1.0.0, only this application's own modules are logged,
//! never the libraries (reqwest, tauri...), so verbose mode shows its
//! diagnostics rather than framework traffic. `verbose_logging` set: DEBUG
//! and up; unset: warnings and errors only. [`set_verbose`] applies a
//! change at once, without a restart.
//!
//! Nothing logged here may carry an API key: providers log endpoints,
//! sizes and responses, never their headers.

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use log::{LevelFilter, Log, Metadata, Record};

/// Past this size at startup, the log is moved to `.log.1` (replacing the
/// previous one) and a new one begins: two files at most, never unbounded.
const MAX_SIZE: u64 = 5 * 1024 * 1024;

/// The module path prefix of this crate's own code.
const OWN_TARGET: &str = "rust_lib";

/// Where the log lives on this machine.
pub fn log_path() -> PathBuf {
    crate::core::settings::config_dir().join("renpy-translation-studio.log")
}

/// Install the file logger once, at startup. A log that cannot be opened
/// (read-only folder...) leaves logging off rather than stopping the app.
pub fn init(verbose: bool) {
    let Ok(file) = open_log(&log_path()) else {
        return;
    };
    if log::set_boxed_logger(Box::new(FileLogger {
        file: Mutex::new(file),
    }))
    .is_ok()
    {
        set_verbose(verbose);
    }
}

/// Apply the `verbose_logging` setting.
pub fn set_verbose(verbose: bool) {
    log::set_max_level(if verbose {
        LevelFilter::Debug
    } else {
        LevelFilter::Warn
    });
}

fn open_log(path: &Path) -> std::io::Result<File> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    if fs::metadata(path).is_ok_and(|m| m.len() > MAX_SIZE) {
        let _ = fs::rename(path, path.with_extension("log.1"));
    }
    OpenOptions::new().create(true).append(true).open(path)
}

struct FileLogger {
    file: Mutex<File>,
}

impl Log for FileLogger {
    fn enabled(&self, metadata: &Metadata) -> bool {
        metadata.level() <= log::max_level() && metadata.target().starts_with(OWN_TARGET)
    }

    fn log(&self, record: &Record) {
        if !self.enabled(record.metadata()) {
            return;
        }
        let line = format_line(
            &utc_timestamp(SystemTime::now()),
            record.level().as_str(),
            record.target(),
            &record.args().to_string(),
        );
        if let Ok(mut file) = self.file.lock() {
            let _ = file.write_all(line.as_bytes());
        }
    }

    fn flush(&self) {
        if let Ok(mut file) = self.file.lock() {
            let _ = file.flush();
        }
    }
}

/// One log line, the 1.0.0 layout: `time LEVEL module: message`, with the
/// crate prefix dropped from the module path.
fn format_line(time: &str, level: &str, target: &str, message: &str) -> String {
    let module = target
        .strip_prefix(OWN_TARGET)
        .map(|rest| rest.trim_start_matches("::"))
        .unwrap_or(target);
    format!("{time} {level:<5} {module}: {message}\n")
}

/// `YYYY-MM-DD HH:MM:SSZ` (UTC), from the civil-from-days algorithm (no
/// date crate for one timestamp per line).
fn utc_timestamp(now: SystemTime) -> String {
    let secs = now.duration_since(UNIX_EPOCH).map_or(0, |d| d.as_secs());
    let days = (secs / 86_400) as i64;
    let rem = secs % 86_400;
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02} {:02}:{:02}:{:02}Z",
        rem / 3600,
        rem % 3600 / 60,
        rem % 60
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn timestamp_is_utc_calendar_time() {
        assert_eq!(utc_timestamp(UNIX_EPOCH), "1970-01-01 00:00:00Z");
        let leap_day = UNIX_EPOCH + Duration::from_secs(1_709_210_096);
        assert_eq!(utc_timestamp(leap_day), "2024-02-29 12:34:56Z");
        let year_end = UNIX_EPOCH + Duration::from_secs(1_798_761_599);
        assert_eq!(utc_timestamp(year_end), "2026-12-31 23:59:59Z");
    }

    #[test]
    fn line_drops_the_crate_prefix() {
        assert_eq!(
            format_line(
                "2026-10-25 18:00:00Z",
                "WARN",
                "rust_lib::core::translation::job",
                "stopped"
            ),
            "2026-10-25 18:00:00Z WARN  core::translation::job: stopped\n"
        );
    }

    #[test]
    fn oversized_log_is_set_aside_at_open() {
        let dir = std::env::temp_dir().join(format!("rts-log-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        let path = dir.join("app.log");
        fs::create_dir_all(&dir).unwrap();
        fs::write(&path, vec![b'x'; (MAX_SIZE + 1) as usize]).unwrap();

        drop(open_log(&path).unwrap());

        assert_eq!(fs::metadata(&path).unwrap().len(), 0);
        assert_eq!(
            fs::metadata(path.with_extension("log.1")).unwrap().len(),
            MAX_SIZE + 1
        );
        let _ = fs::remove_dir_all(&dir);
    }
}
