from tests.app._app_shell_support import AppShellTestCase


class AppShellEditorSurfaceTests(AppShellTestCase):
    test_add_data_panel_uses_tabbed_sections = (
        AppShellTestCase.case_add_data_panel_uses_tabbed_sections
    )
    test_track_editor_uses_tabbed_sections = AppShellTestCase.case_track_editor_uses_tabbed_sections
    test_album_entry_track_sections_use_internal_tabs = (
        AppShellTestCase.case_album_entry_track_sections_use_internal_tabs
    )
    test_gs1_dialog_uses_top_level_workflow_tabs = (
        AppShellTestCase.case_gs1_dialog_uses_top_level_workflow_tabs
    )


del AppShellTestCase
