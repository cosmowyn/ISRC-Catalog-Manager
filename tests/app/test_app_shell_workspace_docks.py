from tests.app._app_shell_support import AppShellTestCase


class AppShellWorkspaceDockTests(AppShellTestCase):
    test_catalog_release_browser_opens_as_tabified_dock = (
        AppShellTestCase.case_catalog_release_browser_opens_as_tabified_dock
    )
    test_release_browser_filter_replaces_active_search_filter = (
        AppShellTestCase.case_release_browser_filter_replaces_active_search_filter
    )
    test_release_browser_selection_scope_tracks_catalog_selection_and_override = (
        AppShellTestCase.case_release_browser_selection_scope_tracks_catalog_selection_and_override
    )
    test_work_manager_dock_uses_live_track_selection = (
        AppShellTestCase.case_work_manager_dock_uses_live_track_selection
    )
    test_work_manager_creates_governed_child_track_in_add_panel = (
        AppShellTestCase.case_work_manager_creates_governed_child_track_in_add_panel
    )
    test_create_work_offers_first_track_creation_context = (
        AppShellTestCase.case_create_work_offers_first_track_creation_context
    )
    test_work_manager_opens_album_dialog_for_selected_work = (
        AppShellTestCase.case_work_manager_opens_album_dialog_for_selected_work
    )
    test_global_search_opens_as_dock_and_keeps_entity_navigation_live = (
        AppShellTestCase.case_global_search_opens_as_dock_and_keeps_entity_navigation_live
    )
    test_workspace_panels_keep_actions_and_saved_search_controls_inside_scroll_safe_surfaces = (
        AppShellTestCase.case_workspace_panels_keep_actions_and_saved_search_controls_inside_scroll_safe_surfaces
    )
    test_catalog_managers_open_as_tabified_dock_and_focus_requested_tab = (
        AppShellTestCase.case_catalog_managers_open_as_tabified_dock_and_focus_requested_tab
    )
    test_catalog_managers_dialog_uses_compact_size_and_consistent_tabs = (
        AppShellTestCase.case_catalog_managers_dialog_uses_compact_size_and_consistent_tabs
    )
    test_catalog_managers_tabs_keep_bottom_actions_inside_themed_scroll_surfaces = (
        AppShellTestCase.case_catalog_managers_tabs_keep_bottom_actions_inside_themed_scroll_surfaces
    )
    test_hidden_catalog_table_does_not_block_workspace_dock_access_or_peer_tabifying = (
        AppShellTestCase.case_hidden_catalog_table_does_not_block_workspace_dock_access_or_peer_tabifying
    )
    test_license_browser_opens_as_tabified_dock_and_applies_track_filter = (
        AppShellTestCase.case_license_browser_opens_as_tabified_dock_and_applies_track_filter
    )
    test_party_contract_rights_and_asset_windows_open_as_tabified_docks = (
        AppShellTestCase.case_party_contract_rights_and_asset_windows_open_as_tabified_docks
    )
    test_contract_template_workspace_opens_as_tabified_dock = (
        AppShellTestCase.case_contract_template_workspace_opens_as_tabified_dock
    )
    test_contract_template_workspace_opens_fill_tab_as_tabified_dock = (
        AppShellTestCase.case_contract_template_workspace_opens_fill_tab_as_tabified_dock
    )
    test_contract_template_workspace_fill_tab_can_save_and_resume_drafts = (
        AppShellTestCase.case_contract_template_workspace_fill_tab_can_save_and_resume_drafts
    )
    test_contract_template_workspace_fill_tab_can_export_pdf = (
        AppShellTestCase.case_contract_template_workspace_fill_tab_can_export_pdf
    )
    test_asset_workspace_rejoins_tabbed_dock_strip_when_reopened = (
        AppShellTestCase.case_asset_workspace_rejoins_tabbed_dock_strip_when_reopened
    )


del AppShellTestCase
