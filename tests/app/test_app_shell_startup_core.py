from tests.app._app_shell_support import AppShellTestCase


class AppShellStartupCoreTests(AppShellTestCase):
    test_startup_builds_main_window_with_core_actions = (
        AppShellTestCase.case_startup_builds_main_window_with_core_actions
    )
    test_startup_status_messages_cover_real_bootstrap_phases_and_ready_boundary = (
        AppShellTestCase.case_startup_status_messages_cover_real_bootstrap_phases_and_ready_boundary
    )
    test_file_menu_groups_xml_import_under_import_exchange_and_preserves_wiring = (
        AppShellTestCase.case_file_menu_groups_xml_import_under_import_exchange_and_preserves_wiring
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
