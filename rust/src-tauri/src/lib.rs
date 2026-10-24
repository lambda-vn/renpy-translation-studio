mod app_state;
mod commands;
mod core;
pub mod mcp_server;

use app_state::AppState;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            commands::project::list_recent_projects,
            commands::project::open_project,
            commands::project::current_project,
            commands::review::list_files,
            commands::review::list_units,
            commands::review::save_draft,
            commands::review::validate_unit,
            commands::review::set_needs_review,
            commands::review::set_note,
            commands::translate::start_translation_job,
            commands::translate::cancel_translation_job,
            commands::translate::is_translation_job_running,
            commands::settings::get_settings,
            commands::settings::set_setting,
            commands::settings::test_deepl_connection,
            commands::settings::test_ollama_connection,
            commands::settings::test_libretranslate_connection,
            commands::characters::list_characters,
            commands::characters::upsert_character,
            commands::characters::delete_character,
            commands::universe::get_universe_summary,
            commands::universe::set_universe_summary,
            commands::export::save_project,
            commands::export::export_project,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
