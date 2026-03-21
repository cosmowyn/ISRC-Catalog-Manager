from tests.app._app_shell_support import AppShellTestCase


class AppShellStartupAndStorageTests(AppShellTestCase):
    test_startup_builds_main_window_with_core_actions = (
        AppShellTestCase.case_startup_builds_main_window_with_core_actions
    )
    test_startup_status_messages_cover_real_bootstrap_phases_and_ready_boundary = (
        AppShellTestCase.case_startup_status_messages_cover_real_bootstrap_phases_and_ready_boundary
    )
    test_file_menu_groups_xml_import_under_import_exchange_and_preserves_wiring = (
        AppShellTestCase.case_file_menu_groups_xml_import_under_import_exchange_and_preserves_wiring
    )
    test_startup_can_defer_legacy_storage_migration_and_keep_current_folder = (
        AppShellTestCase.case_startup_can_defer_legacy_storage_migration_and_keep_current_folder
    )
    test_startup_migrate_now_bootstraps_logging_and_uses_preferred_root = (
        AppShellTestCase.case_startup_migrate_now_bootstraps_logging_and_uses_preferred_root
    )
    test_schema_migration_error_dialog_suspends_splash_during_startup = (
        AppShellTestCase.case_schema_migration_error_dialog_suspends_splash_during_startup
    )
    test_startup_adopts_valid_preferred_root_when_settings_still_pin_legacy = (
        AppShellTestCase.case_startup_adopts_valid_preferred_root_when_settings_still_pin_legacy
    )
    test_storage_migration_reopens_active_managed_profile_in_new_root = (
        AppShellTestCase.case_storage_migration_reopens_active_managed_profile_in_new_root
    )
    test_manual_legacy_cleanup_after_adoption_does_not_recreate_legacy_root = (
        AppShellTestCase.case_manual_legacy_cleanup_after_adoption_does_not_recreate_legacy_root
    )
    test_portable_mode_skips_storage_migration_and_legacy_adoption = (
        AppShellTestCase.case_portable_mode_skips_storage_migration_and_legacy_adoption
    )
    test_bundled_themes_are_available_and_not_persisted_as_user_library_entries = (
        AppShellTestCase.case_bundled_themes_are_available_and_not_persisted_as_user_library_entries
    )
    test_catalog_menu_hides_top_level_release_creation_and_groups_legacy_tools = (
        AppShellTestCase.case_catalog_menu_hides_top_level_release_creation_and_groups_legacy_tools
    )
    test_catalog_menu_hosts_panel_toggle_actions_and_preserves_existing_behavior = (
        AppShellTestCase.case_catalog_menu_hosts_panel_toggle_actions_and_preserves_existing_behavior
    )


del AppShellTestCase
