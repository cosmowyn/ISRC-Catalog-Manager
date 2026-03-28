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
    test_export_catalog_audio_copies_exports_managed_and_database_wav_sources = (
        AppShellTestCase.case_export_catalog_audio_copies_exports_managed_and_database_wav_sources
    )
    test_export_standard_audio_file_embeds_catalog_metadata_on_export = (
        AppShellTestCase.case_export_standard_audio_file_embeds_catalog_metadata_on_export
    )
    test_bulk_audio_column_export_uses_background_task_and_embeds_catalog_metadata = (
        AppShellTestCase.case_bulk_audio_column_export_uses_background_task_and_embeds_catalog_metadata
    )
    test_album_entry_track_sections_use_internal_tabs = (
        AppShellTestCase.case_album_entry_track_sections_use_internal_tabs
    )
    test_album_entry_can_create_tracks_under_selected_work = (
        AppShellTestCase.case_album_entry_can_create_tracks_under_selected_work
    )
    test_album_entry_creates_parent_work_per_track_when_no_work_selected = (
        AppShellTestCase.case_album_entry_creates_parent_work_per_track_when_no_work_selected
    )
    test_add_track_requires_work_when_link_mode_selected = (
        AppShellTestCase.case_save_recording_without_work_context_redirects_to_governed_creation
    )
    test_add_track_creates_new_work_from_track_with_seeded_work_metadata_and_party_artist = (
        AppShellTestCase.case_add_track_creates_new_work_from_track_with_seeded_work_metadata_and_party_artist
    )
    test_album_entry_can_mix_existing_and_new_work_governance_per_row = (
        AppShellTestCase.case_album_entry_can_mix_existing_and_new_work_governance_per_row
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
    test_table_context_menu_keeps_multi_selection_when_right_clicking_selected_row = (
        AppShellTestCase.case_table_context_menu_keeps_multi_selection_when_right_clicking_selected_row
    )
    test_audioless_row_context_menu_omits_audio_submenu = (
        AppShellTestCase.case_audioless_row_context_menu_omits_audio_submenu
    )
    test_standard_media_context_menu_groups_file_and_storage_actions = (
        AppShellTestCase.case_standard_media_context_menu_groups_file_and_storage_actions
    )
    test_custom_blob_context_menu_groups_file_and_storage_actions = (
        AppShellTestCase.case_custom_blob_context_menu_groups_file_and_storage_actions
    )
    test_verify_audio_authenticity_can_choose_external_file_when_track_is_selected = (
        AppShellTestCase.case_verify_audio_authenticity_can_choose_external_file_when_track_is_selected
    )
    test_verify_audio_authenticity_can_use_selected_database_audio = (
        AppShellTestCase.case_verify_audio_authenticity_can_use_selected_database_audio
    )
    test_audio_preview_media_layout_uses_now_playing_header_and_artwork = (
        AppShellTestCase.case_audio_preview_media_layout_uses_now_playing_header_and_artwork
    )
    test_audio_preview_layout_groups_and_theme_surfaces_are_exposed = (
        AppShellTestCase.case_audio_preview_layout_groups_and_theme_surfaces_are_exposed
    )
    test_audio_preview_navigation_follows_visible_catalog_order_and_auto_advance = (
        AppShellTestCase.case_audio_preview_navigation_follows_visible_catalog_order_and_auto_advance
    )
    test_audio_preview_waveform_wheel_scrub_and_shortcuts_are_wired = (
        AppShellTestCase.case_audio_preview_waveform_wheel_scrub_and_shortcuts_are_wired
    )
    test_audio_preview_export_controls_route_to_existing_methods = (
        AppShellTestCase.case_audio_preview_export_controls_route_to_existing_methods
    )
    test_media_preview_windows_are_singleton_top_level_windows = (
        AppShellTestCase.case_media_preview_windows_are_singleton_top_level_windows
    )


del AppShellTestCase
