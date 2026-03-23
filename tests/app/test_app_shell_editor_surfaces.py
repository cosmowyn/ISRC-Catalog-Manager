from tests.app._app_shell_support import AppShellTestCase


class AppShellEditorSurfaceTests(AppShellTestCase):
    test_add_data_panel_uses_tabbed_sections = (
        AppShellTestCase.case_add_data_panel_uses_tabbed_sections
    )
    test_track_editor_uses_tabbed_sections = AppShellTestCase.case_track_editor_uses_tabbed_sections
    test_track_editor_disables_album_art_upload_for_shared_art_slave = (
        AppShellTestCase.case_track_editor_disables_album_art_upload_for_shared_art_slave
    )
    test_track_editor_keeps_album_art_upload_enabled_for_shared_art_master = (
        AppShellTestCase.case_track_editor_keeps_album_art_upload_enabled_for_shared_art_master
    )
    test_bulk_track_editor_disables_album_art_upload_when_selection_includes_slave = (
        AppShellTestCase.case_bulk_track_editor_disables_album_art_upload_when_selection_includes_slave
    )
    test_track_editor_open_master_action_opens_owner_editor = (
        AppShellTestCase.case_track_editor_open_master_action_opens_owner_editor
    )
    test_write_tags_to_exported_audio_exports_managed_and_database_wav_sources = (
        AppShellTestCase.case_write_tags_to_exported_audio_exports_managed_and_database_wav_sources
    )
    test_album_entry_track_sections_use_internal_tabs = (
        AppShellTestCase.case_album_entry_track_sections_use_internal_tabs
    )
    test_gs1_dialog_uses_top_level_workflow_tabs = (
        AppShellTestCase.case_gs1_dialog_uses_top_level_workflow_tabs
    )
    test_authenticity_actions_are_present_in_catalog_and_settings_menus = (
        AppShellTestCase.case_authenticity_actions_are_present_in_catalog_and_settings_menus
    )
    test_authenticity_table_context_menu_exposes_export_actions = (
        AppShellTestCase.case_authenticity_table_context_menu_exposes_export_actions
    )
    test_verify_audio_authenticity_can_choose_external_file_when_track_is_selected = (
        AppShellTestCase.case_verify_audio_authenticity_can_choose_external_file_when_track_is_selected
    )
    test_verify_audio_authenticity_can_use_selected_database_audio = (
        AppShellTestCase.case_verify_audio_authenticity_can_use_selected_database_audio
    )


del AppShellTestCase
