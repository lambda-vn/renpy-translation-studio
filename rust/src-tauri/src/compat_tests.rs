//! Compatibility with what the 1.0.0 Python application wrote.
//!
//! The fixtures under `tests/fixtures/compat/` were produced by the code
//! of the `v1.0.0` tag itself (`rust/scripts/make_compat_fixtures.py`),
//! never by hand: a hand-written file would only prove the Rust code
//! agrees with itself. Every test works on a temporary copy, so a run
//! can never alter the committed bytes.
//!
//! Frozen contract under test (see CLAUDE.md, "Compatibilité"): the
//! SQLite project schema, the `settings.json` keys, the machine-wide
//! translation memory and the recent-projects registry.

use std::path::{Path, PathBuf};

use crate::core::settings::Settings;
use crate::core::storage::{recent_projects, repositories, translation_memory};
use crate::mcp_server::session::open_project;

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/compat")
}

fn scratch(name: &str) -> PathBuf {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let dir = std::env::temp_dir().join(format!(
        "rts-compat-{name}-{nanos}-{:?}",
        std::thread::current().id()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn copy_file(from: &Path, to_dir: &Path) -> PathBuf {
    let to = to_dir.join(from.file_name().unwrap());
    std::fs::copy(from, &to).unwrap();
    to
}

fn project_copy() -> PathBuf {
    let project = scratch("project");
    let rts = project.join(".rts");
    std::fs::create_dir_all(&rts).unwrap();
    copy_file(&fixtures().join("project/.rts/translations.db"), &rts);
    project
}

#[test]
fn a_1_0_0_project_database_opens_and_reads_back_exactly() {
    let session = open_project(&project_copy()).unwrap();
    let conn = session.conn();

    let counts = repositories::count_by_status(conn).unwrap();
    assert_eq!(counts["human_validated"], 2);
    assert_eq!(counts["ai_suggested"], 1);
    assert_eq!(counts["draft"], 1);
    assert_eq!(counts["imported"], 1);
    assert_eq!(counts["not_translated"], 1);

    let units = repositories::get_all(conn, None, None).unwrap();
    let by_id = |id: &str| units.iter().find(|u| u.block_id == id).unwrap();

    let a1 = by_id("start_a1");
    assert_eq!(a1.source_text, "Hello [name].");
    assert_eq!(a1.translated_text, "Bonjour [name].");
    assert_eq!(a1.status, "human_validated");
    assert_eq!(a1.character_variable.as_deref(), Some("e"));
    assert_eq!(a1.source_line, 10);
    assert!(a1.source_file.ends_with("script.rpy"));

    assert_eq!(by_id("start_a3").translated_text, "\u{2026}");
    assert_eq!(by_id("start_a3").character_variable, None);

    let a4 = by_id("start_a4");
    assert_eq!(
        a4.source_text,
        "Caf\u{e9} \u{e0} la cr\u{e8}me \u{2014} \u{fc}ber"
    );
    assert_eq!(a4.translated_text, "Caf\u{e9} \u{e0} la cr\u{e8}me");
    assert_eq!(a4.status, "imported");

    let a5 = by_id("start_a5");
    assert!(a5.needs_review, "set_note raises the review flag");
    assert_eq!(a5.note.as_deref(), Some("check the tone"));
    assert_eq!(a5.status, "not_translated");

    assert_eq!(by_id("strings_deadbeef").translated_text, "Oui");
}

#[test]
fn characters_and_project_meta_are_read_back() {
    let session = open_project(&project_copy()).unwrap();
    let conn = session.conn();

    let characters = repositories::get_all_characters(conn).unwrap();
    let eileen = characters.iter().find(|c| c.variable == "e").unwrap();
    assert_eq!(eileen.display_name, "Eileen");
    assert_eq!(
        eileen.notes.as_deref(),
        Some("female, formal\nEileen -> Aline")
    );
    assert_eq!(
        characters.iter().find(|c| c.variable == "m").unwrap().notes,
        None
    );

    assert_eq!(session.source_language(), "english");
    assert_eq!(session.target_language(), "french");
    assert_eq!(
        repositories::get_project_meta(conn, "universe_summary")
            .unwrap()
            .as_deref(),
        Some("A quiet seaside town.")
    );
}

#[test]
fn progress_filters_and_search_agree_with_the_data() {
    let session = open_project(&project_copy()).unwrap();
    let conn = session.conn();

    let progress = repositories::project_progress(conn).unwrap();
    assert_eq!(progress.lines, 6);
    assert_eq!(progress.validated_lines, 2);

    let file = repositories::get_files(conn)
        .unwrap()
        .into_iter()
        .find(|f| f.source_file.ends_with("script.rpy"))
        .unwrap();
    assert_eq!(file.total, 5);

    let (page, total) = repositories::get_page(
        conn,
        &file.source_file,
        0,
        50,
        None,
        "cr\u{e8}me",
        None,
        false,
    )
    .unwrap();
    assert_eq!((page.len(), total), (1, 1));

    let (flagged, _) =
        repositories::get_page(conn, &file.source_file, 0, 50, None, "", None, true).unwrap();
    assert_eq!(flagged.len(), 1);
    assert_eq!(flagged[0].block_id, "start_a5");
}

#[test]
fn rust_writes_keep_the_database_valid_and_protect_validated_lines() {
    let session = open_project(&project_copy()).unwrap();
    let conn = session.conn();

    repositories::update_translation(conn, "start_a1", "overwritten", "ai_suggested").unwrap();
    let a1 = repositories::get_many(conn, &["start_a1".to_string()]).unwrap();
    assert_eq!(a1[0].translated_text, "Bonjour [name].");

    repositories::update_translations(
        conn,
        &[(
            "start_a5".to_string(),
            "\u{c0} faire.".to_string(),
            "ai_suggested".to_string(),
        )],
    )
    .unwrap();
    repositories::set_note(conn, "start_a2", "second look").unwrap();

    let integrity: String = conn
        .query_row("PRAGMA integrity_check", [], |r| r.get(0))
        .unwrap();
    assert_eq!(integrity, "ok");
    let journal: String = conn
        .query_row("PRAGMA journal_mode", [], |r| r.get(0))
        .unwrap();
    assert_eq!(journal.to_lowercase(), "wal");

    let a5 = repositories::get_many(conn, &["start_a5".to_string()]).unwrap();
    assert_eq!(a5[0].translated_text, "\u{c0} faire.");
    assert_eq!(a5[0].status, "ai_suggested");
}

#[test]
fn settings_json_written_by_1_0_0_loads_and_keeps_its_keys_on_save() {
    let dir = scratch("settings");
    let file = copy_file(&fixtures().join("config/settings.json"), &dir);

    let mut settings = Settings::load_from(file.clone());
    assert!(!settings.is_first_launch());
    assert_eq!(settings.get("locale").as_deref(), Some("fr"));
    assert_eq!(settings.get("theme").as_deref(), Some("dark"));
    assert_eq!(settings.get("default_provider").as_deref(), Some("ollama"));
    assert_eq!(settings.get("ollama_model").as_deref(), Some("llama3.1"));
    assert_eq!(settings.get("ollama_batch_size").as_deref(), Some("8"));
    assert_eq!(
        settings.get("libretranslate_url").as_deref(),
        Some("http://localhost:5000")
    );
    assert_eq!(settings.get("verbose_logging").as_deref(), Some("true"));
    assert_eq!(settings.get("sdk_path"), None);

    settings.set("locale", Some("en")).unwrap();
    let saved: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&file).unwrap()).unwrap();
    assert_eq!(saved["locale"], "en");
    assert_eq!(saved["ollama_model"], "llama3.1");
    assert_eq!(saved["sdk_path"], serde_json::Value::Null);
}

#[test]
fn translation_memory_written_by_1_0_0_answers_exact_and_normalized_lookups() {
    let dir = scratch("memory");
    let path = copy_file(&fixtures().join("config/memory.db"), &dir);
    let memory = translation_memory::open(&path).unwrap();

    let asked: Vec<String> = [
        "Hello.",
        "HELLO!",
        "Yes",
        "Caf\u{e9} \u{e0} la cr\u{e8}me",
        "Press [key]!",
        "Press [KEY]!",
        "Never stored",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    let found = translation_memory::lookup(&memory, &asked, "english", "french").unwrap();

    assert_eq!(found["Hello."], "Bonjour.");
    assert_eq!(found["HELLO!"], "Bonjour.");
    assert_eq!(found["Yes"], "Oui");
    assert_eq!(
        found["Caf\u{e9} \u{e0} la cr\u{e8}me"],
        "Caf\u{e9} cr\u{e8}me"
    );
    assert_eq!(found["Press [key]!"], "Appuyez sur [key] !");
    assert!(
        !found.contains_key("Press [KEY]!"),
        "a variable of another case must never share a translation"
    );
    assert!(!found.contains_key("Never stored"));

    let german =
        translation_memory::lookup(&memory, &["Hello.".to_string()], "english", "german").unwrap();
    assert_eq!(german["Hello."], "Hallo.");

    assert_eq!(
        translation_memory::stats(&memory).unwrap(),
        vec![
            ("english".to_string(), "french".to_string(), 4),
            ("english".to_string(), "german".to_string(), 1),
        ]
    );
}

#[test]
fn the_memory_written_by_1_0_0_fills_a_1_0_0_project() {
    let session = open_project(&project_copy()).unwrap();
    let dir = scratch("fill");
    let memory_path = copy_file(&fixtures().join("config/memory.db"), &dir);
    let memory = translation_memory::open(&memory_path).unwrap();
    translation_memory::remember(
        &memory,
        &[("Still to do.".to_string(), "\u{c0} faire.".to_string())],
        "english",
        "french",
    )
    .unwrap();

    let filled = crate::core::project_actions::fill_from_memory(
        session.conn(),
        &memory_path,
        &session.source_language(),
        &session.target_language(),
    )
    .unwrap();
    assert_eq!(filled, 1);

    let a5 = repositories::get_many(session.conn(), &["start_a5".to_string()]).unwrap();
    assert_eq!(a5[0].translated_text, "\u{c0} faire.");
    assert_eq!(a5[0].status, "imported");
}

#[test]
fn the_recent_projects_registry_written_by_1_0_0_is_read_most_recent_first() {
    let dir = scratch("registry");
    let file = copy_file(&fixtures().join("config/projects.json"), &dir);

    let entries: Vec<String> = recent_projects::all(&file)
        .iter()
        .map(|p| p.to_string_lossy().into_owned())
        .collect();
    assert_eq!(
        entries,
        vec!["D:\\VN\\Games\\Demo", "D:\\VN\\Games\\Demo\\Other"]
    );

    let fresh = scratch("registered-project");
    recent_projects::add(&file, &fresh);
    let after: Vec<String> = recent_projects::all(&file)
        .iter()
        .map(|p| p.to_string_lossy().into_owned())
        .collect();
    assert_eq!(after.len(), 3);
    assert_eq!(
        &after[1..],
        &entries[..],
        "existing entries are kept in order"
    );
}

/// Opt-in: `cargo test --lib real_machine -- --ignored --nocapture`.
///
/// Reads what the Python application left in the real machine-wide config
/// directory (copied first, so nothing there is ever written) and the
/// projects of its registry, as a check against data with a real history
/// rather than a minimal fixture.
#[test]
#[ignore = "reads this machine's real 1.x data"]
fn real_machine_data_is_readable() {
    let real = crate::core::settings::config_dir();
    let dir = scratch("real-machine");

    if real.join("settings.json").is_file() {
        let file = copy_file(&real.join("settings.json"), &dir);
        let mut settings = Settings::load_from(file);
        println!("settings: locale={:?}", settings.get("locale"));
    }
    if real.join("memory.db").is_file() {
        let path = copy_file(&real.join("memory.db"), &dir);
        let memory = translation_memory::open(&path).unwrap();
        println!("memory: {:?}", translation_memory::stats(&memory).unwrap());
    }
    if real.join("projects.json").is_file() {
        let file = copy_file(&real.join("projects.json"), &dir);
        for project in recent_projects::all(&file) {
            let db = crate::core::storage::Database::path_for(&project);
            if !db.is_file() {
                println!("project {}: no database", project.display());
                continue;
            }
            let rts = scratch("real-project").join(".rts");
            std::fs::create_dir_all(&rts).unwrap();
            copy_file(&db, &rts);
            let session = open_project(rts.parent().unwrap()).unwrap();
            println!(
                "project {}: {:?} ({} -> {})",
                project.display(),
                repositories::count_by_status(session.conn()).unwrap(),
                session.source_language(),
                session.target_language()
            );
        }
    }
}
