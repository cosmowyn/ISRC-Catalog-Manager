from tests.app._app_shell_support import AppShellTestCase


class AppShellCatalogControllerTests(AppShellTestCase):
    test_table_context_menu_keeps_multi_selection_when_right_clicking_selected_row = (
        AppShellTestCase.case_table_context_menu_keeps_multi_selection_when_right_clicking_selected_row
    )
    test_selected_or_visible_track_ids_prefer_visible_scope_when_filter_active = (
        AppShellTestCase.case_selected_or_visible_track_ids_prefer_visible_scope_when_filter_active
    )
    test_default_conversion_track_ids_prefer_selection_before_filtered_scope = (
        AppShellTestCase.case_default_conversion_track_ids_prefer_selection_before_filtered_scope
    )
    test_standard_table_double_click_opens_selected_editor = (
        AppShellTestCase.case_standard_table_double_click_opens_selected_editor
    )
    test_standard_media_table_double_click_routes_to_attach = (
        AppShellTestCase.case_standard_media_table_double_click_routes_to_attach
    )
    test_text_custom_field_table_edit_saves_without_attachment_state = (
        AppShellTestCase.case_text_custom_field_table_edit_saves_without_attachment_state
    )
    test_space_key_previews_current_standard_media_cell = (
        AppShellTestCase.case_space_key_previews_current_standard_media_cell
    )


del AppShellTestCase
