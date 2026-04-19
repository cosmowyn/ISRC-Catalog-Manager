from tests.app._app_shell_support import AppShellTestCase


class AppShellCatalogModelViewTests(AppShellTestCase):
    test_catalog_table_uses_qtableview_model_proxy_live_path = (
        AppShellTestCase.case_catalog_table_uses_qtableview_model_proxy_live_path
    )
    test_catalog_model_view_restore_preserves_proxy_selection_and_filter = (
        AppShellTestCase.case_catalog_model_view_restore_preserves_proxy_selection_and_filter
    )
    test_catalog_background_refresh_progress_completes_after_model_proxy_apply = (
        AppShellTestCase.case_catalog_background_refresh_progress_completes_after_model_proxy_apply
    )
    test_catalog_badge_icons_are_served_from_model_roles_without_live_render_lookup = (
        AppShellTestCase.case_catalog_badge_icons_are_served_from_model_roles_without_live_render_lookup
    )
    test_audio_preview_navigation_uses_proxy_order_and_model_media_roles = (
        AppShellTestCase.case_audio_preview_navigation_uses_proxy_order_and_model_media_roles
    )
    test_focused_audio_export_uses_proxy_ordered_track_ids = (
        AppShellTestCase.case_focused_audio_export_uses_proxy_ordered_track_ids
    )
    test_proxy_source_mapping_stays_correct_under_sort_filter_selection_for_media_roles = (
        AppShellTestCase.case_proxy_source_mapping_stays_correct_under_sort_filter_selection_for_media_roles
    )
    test_catalog_zoom_slider_wheel_and_pinch_sync_without_data_refresh = (
        AppShellTestCase.case_catalog_zoom_slider_wheel_and_pinch_sync_without_data_refresh
    )
    test_catalog_table_top_controls_are_grouped_and_shortcut_filters_current_cell = (
        AppShellTestCase.case_catalog_table_top_controls_are_grouped_and_shortcut_filters_current_cell
    )
    test_catalog_zoom_persists_in_layout_and_resets_on_profile_change = (
        AppShellTestCase.case_catalog_zoom_persists_in_layout_and_resets_on_profile_change
    )


del AppShellTestCase
