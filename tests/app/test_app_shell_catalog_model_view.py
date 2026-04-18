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


del AppShellTestCase
