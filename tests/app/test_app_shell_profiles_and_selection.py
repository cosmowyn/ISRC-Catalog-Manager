from tests.app._app_shell_support import AppShellTestCase


class AppShellProfileAndSelectionTests(AppShellTestCase):
    test_create_new_profile_and_browse_profile_switch_workspace = (
        AppShellTestCase.case_create_new_profile_and_browse_profile_switch_workspace
    )
    test_profile_switch_loading_feedback_waits_for_catalog_refresh_completion = (
        AppShellTestCase.case_profile_switch_loading_feedback_waits_for_catalog_refresh_completion
    )
    test_profile_switch_reuses_prepared_database_activation_path = (
        AppShellTestCase.case_profile_switch_reuses_prepared_database_activation_path
    )
    test_cancelled_profile_creation_and_restore_leave_shell_idle = (
        AppShellTestCase.case_cancelled_profile_creation_and_restore_leave_shell_idle
    )
    test_filtered_select_all_counts_only_visible_tracks = (
        AppShellTestCase.case_filtered_select_all_counts_only_visible_tracks
    )
    test_reset_button_clears_filters_without_refreshing_catalog = (
        AppShellTestCase.case_reset_button_clears_filters_without_refreshing_catalog
    )
    test_reset_filter_action_keeps_form_state_and_skips_catalog_refresh = (
        AppShellTestCase.case_reset_filter_action_keeps_form_state_and_skips_catalog_refresh
    )
    test_escape_resets_filter_without_rebuilding_catalog_or_form = (
        AppShellTestCase.case_escape_resets_filter_without_rebuilding_catalog_or_form
    )
    test_delete_entry_history_stays_a_single_visible_user_action = (
        AppShellTestCase.case_delete_entry_history_stays_a_single_visible_user_action
    )
    test_track_delete_progress_reaches_100_only_after_final_ui_refresh = (
        AppShellTestCase.case_track_delete_progress_reaches_100_only_after_final_ui_refresh
    )
    test_programmatic_header_resize_does_not_record_history = (
        AppShellTestCase.case_programmatic_header_resize_does_not_record_history
    )
    test_interactive_header_resize_records_a_single_visible_history_entry = (
        AppShellTestCase.case_interactive_header_resize_records_a_single_visible_history_entry
    )
    test_add_data_comboboxes_include_release_level_catalog_values = (
        AppShellTestCase.case_add_data_comboboxes_include_release_level_catalog_values
    )


del AppShellTestCase
