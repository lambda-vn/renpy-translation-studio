mod app_state;
mod commands;
#[cfg(test)]
mod compat_tests;
mod core;
pub mod mcp_server;

use app_state::AppState;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            commands::project::list_recent_projects,
            commands::project::open_project,
            commands::project::forget_project,
            commands::project::delete_project_data,
            commands::project::current_project,
            commands::extract::list_languages,
            commands::extract::inspect_game,
            commands::extract::extract_project,
            commands::interchange::export_interchange,
            commands::interchange::plan_interchange_import,
            commands::interchange::apply_interchange_import,
            commands::interchange::fill_from_memory,
            commands::live::start_live,
            commands::live::stop_live,
            commands::review::get_units,
            commands::review::list_files,
            commands::review::list_units,
            commands::review::save_draft,
            commands::review::validate_unit,
            commands::review::validate_and_propagate,
            commands::review::spread_to_duplicates,
            commands::review::clear_translations,
            commands::review::unwritten_count,
            commands::review::reveal_file,
            commands::review::count_matches,
            commands::review::list_speakers,
            commands::review::project_progress,
            commands::review::get_context,
            commands::review::set_needs_review,
            commands::review::set_note,
            commands::translate::start_translation_job,
            commands::translate::translate_unit,
            commands::translate::cancel_translation_job,
            commands::translate::is_translation_job_running,
            commands::settings::get_settings,
            commands::settings::set_setting,
            commands::settings::is_first_launch,
            commands::settings::validate_sdk_path,
            commands::settings::complete_onboarding,
            commands::settings::memory_stats,
            commands::settings::forget_memory,
            commands::settings::test_deepl_connection,
            commands::settings::test_ollama_connection,
            commands::settings::test_libretranslate_connection,
            commands::characters::list_characters,
            commands::characters::detect_characters,
            commands::characters::upsert_character,
            commands::characters::delete_character,
            commands::universe::get_universe_summary,
            commands::universe::set_universe_summary,
            commands::universe::generate_universe_summary,
            commands::export::save_project,
            commands::export::export_info,
            commands::export::zip_file_name,
            commands::export::export_project,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
