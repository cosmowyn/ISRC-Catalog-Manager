from tests.app._app_shell_support import AppShellTestCase


class AppShellStartupCoreTests(AppShellTestCase):
    test_startup_builds_main_window_with_core_actions = (
        AppShellTestCase.case_startup_builds_main_window_with_core_actions
    )
    test_startup_status_messages_cover_real_bootstrap_phases_and_ready_boundary = (
        AppShellTestCase.case_startup_status_messages_cover_real_bootstrap_phases_and_ready_boundary
    )
    test_startup_splash_waits_for_catalog_refresh_completion = (
        AppShellTestCase.case_startup_splash_waits_for_catalog_refresh_completion
    )
    test_startup_prepares_database_before_live_open = (
        AppShellTestCase.case_startup_prepares_database_before_live_open
    )
    test_startup_ignores_repo_demo_runtime_last_path_for_normal_settings = (
        AppShellTestCase.case_startup_ignores_repo_demo_runtime_last_path_for_normal_settings
    )
    test_trace_logging_sanitizes_reserved_logrecord_field_names = (
        AppShellTestCase.case_trace_logging_sanitizes_reserved_logrecord_field_names
    )
    test_audio_conversion_format_prompt_uses_export_button_label = (
        AppShellTestCase.case_audio_conversion_format_prompt_uses_export_button_label
    )
    test_startup_first_launch_prompt_can_open_settings_and_clears_pending_flag = (
        AppShellTestCase.case_startup_first_launch_prompt_can_open_settings_and_clears_pending_flag
    )
    test_owner_bootstrap_requires_assigning_a_party_before_normal_use = (
        AppShellTestCase.case_owner_bootstrap_requires_assigning_a_party_before_normal_use
    )
    test_window_title_defaults_to_app_name_then_owner_then_manual_override = (
        AppShellTestCase.case_window_title_defaults_to_app_name_then_owner_then_manual_override
    )
    test_file_menu_groups_xml_import_under_import_exchange_and_preserves_wiring = (
        AppShellTestCase.case_file_menu_groups_xml_import_under_import_exchange_and_preserves_wiring
    )
    test_file_menu_nests_profile_maintenance_under_profiles_and_removes_verify_integrity = (
        AppShellTestCase.case_file_menu_nests_profile_maintenance_under_profiles_and_removes_verify_integrity
    )
    test_file_menu_groups_exchange_exports_and_saved_import_reset = (
        AppShellTestCase.case_file_menu_groups_exchange_exports_and_saved_import_reset
    )
    test_edit_menu_exposes_catalog_table_edit_actions_and_preserves_enablement = (
        AppShellTestCase.case_edit_menu_exposes_catalog_table_edit_actions_and_preserves_enablement
    )
    test_settings_view_history_help_menus_and_action_ribbon_context_menu_use_streamlined_structure = (
        AppShellTestCase.case_settings_view_history_help_menus_and_action_ribbon_context_menu_use_streamlined_structure
    )
    test_moved_and_renamed_actions_preserve_dialog_routing = (
        AppShellTestCase.case_moved_and_renamed_actions_preserve_dialog_routing
    )
    test_main_window_shortcuts_cover_help_media_and_workspace_actions = (
        AppShellTestCase.case_main_window_shortcuts_cover_help_media_and_workspace_actions
    )
    test_bundled_themes_are_available_and_not_persisted_as_user_library_entries = (
        AppShellTestCase.case_bundled_themes_are_available_and_not_persisted_as_user_library_entries
    )
    test_catalog_menu_hides_top_level_release_creation_and_removes_legacy_tools = (
        AppShellTestCase.case_catalog_menu_hides_top_level_release_creation_and_removes_legacy_tools
    )
    test_catalog_workspace_menu_groups_intent_actions_and_preserves_workspace_routes = (
        AppShellTestCase.case_catalog_workspace_menu_groups_intent_actions_and_preserves_workspace_routes
    )
    test_profiles_toolbar_visibility_persists_in_view_preferences = (
        AppShellTestCase.case_profiles_toolbar_visibility_persists_in_view_preferences
    )
    test_album_art_export_uses_album_title_and_bulk_export_stays_on_focused_column = (
        AppShellTestCase.case_album_art_export_uses_album_title_and_bulk_export_stays_on_focused_column
    )
    test_bulk_audio_attach_workflow_matches_files_updates_artists_and_records_history = (
        AppShellTestCase.case_bulk_audio_attach_workflow_matches_files_updates_artists_and_records_history
    )
    test_history_budget_preflight_can_open_cleanup_dialog = (
        AppShellTestCase.case_history_budget_preflight_can_open_cleanup_dialog
    )
    test_track_editor_save_succeeds_without_album_propagation = (
        AppShellTestCase.case_track_editor_save_succeeds_without_album_propagation
    )
    test_prepared_database_open_skips_schema_work = (
        AppShellTestCase.case_prepared_database_open_skips_schema_work
    )


del AppShellTestCase
