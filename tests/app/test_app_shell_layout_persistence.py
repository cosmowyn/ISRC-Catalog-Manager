from tests.app._app_shell_support import AppShellTestCase


class AppShellLayoutPersistenceTests(AppShellTestCase):
    test_workspace_docks_use_north_tabs_and_remain_tabified_across_fullscreen_cycle = (
        AppShellTestCase.case_workspace_docks_use_north_tabs_and_remain_tabified_across_fullscreen_cycle
    )
    test_top_chrome_boundary_persists_across_ribbon_visibility_and_window_state_changes = (
        AppShellTestCase.case_top_chrome_boundary_persists_across_ribbon_visibility_and_window_state_changes
    )
    test_workspace_layout_round_trip_restores_tabified_non_floating_docks = (
        AppShellTestCase.case_workspace_layout_round_trip_restores_tabified_non_floating_docks
    )
    test_layout_change_persists_latest_arrangement_not_default_arrangement = (
        AppShellTestCase.case_layout_change_persists_latest_arrangement_not_default_arrangement
    )
    test_hidden_catalog_table_round_trip_preserves_peer_tab_group = (
        AppShellTestCase.case_hidden_catalog_table_round_trip_preserves_peer_tab_group
    )
    test_startup_restore_is_not_overwritten_by_post_init_visibility_sync = (
        AppShellTestCase.case_startup_restore_is_not_overwritten_by_post_init_visibility_sync
    )
    test_close_reopen_round_trip_preserves_core_panel_visibility_without_shutdown_corruption = (
        AppShellTestCase.case_close_reopen_round_trip_preserves_core_panel_visibility_without_shutdown_corruption
    )
    test_main_window_geometry_round_trip_restores_non_default_outer_state = (
        AppShellTestCase.case_main_window_geometry_round_trip_restores_non_default_outer_state
    )
    test_named_main_window_layouts_can_be_saved_applied_deleted_and_shared_between_menu_and_ribbon = (
        AppShellTestCase.case_named_main_window_layouts_can_be_saved_applied_deleted_and_shared_between_menu_and_ribbon
    )
    test_saved_layout_switch_uses_background_task_from_selector_and_menu = (
        AppShellTestCase.case_saved_layout_switch_uses_background_task_from_selector_and_menu
    )
    test_saved_layout_switch_progress_reaches_100_only_after_final_restore = (
        AppShellTestCase.case_saved_layout_switch_progress_reaches_100_only_after_final_restore
    )
    test_saved_layout_switch_suspends_visible_updates_during_apply = (
        AppShellTestCase.case_saved_layout_switch_suspends_visible_updates_during_apply
    )
    test_contract_template_workspace_nested_layout_round_trip_restores_live_inner_state = (
        AppShellTestCase.case_contract_template_workspace_nested_layout_round_trip_restores_live_inner_state
    )
    test_contract_template_workspace_legacy_layout_without_nested_state_uses_default_inner_layout = (
        AppShellTestCase.case_contract_template_workspace_legacy_layout_without_nested_state_uses_default_inner_layout
    )
    test_contract_template_workspace_named_layout_restore_keeps_import_and_fill_controls_visible = (
        AppShellTestCase.case_contract_template_workspace_named_layout_restore_keeps_import_and_fill_controls_visible
    )
    test_contract_template_workspace_named_layout_restore_can_reopen_hidden_fill_dock_while_locked = (
        AppShellTestCase.case_contract_template_workspace_named_layout_restore_can_reopen_hidden_fill_dock_while_locked
    )


del AppShellTestCase
