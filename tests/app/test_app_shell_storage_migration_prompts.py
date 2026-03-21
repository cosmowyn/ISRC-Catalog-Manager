from tests.app._app_shell_support import AppShellTestCase


class AppShellStorageMigrationPromptTests(AppShellTestCase):
    test_startup_can_defer_legacy_storage_migration_and_keep_current_folder = (
        AppShellTestCase.case_startup_can_defer_legacy_storage_migration_and_keep_current_folder
    )
    test_startup_migrate_now_bootstraps_logging_and_uses_preferred_root = (
        AppShellTestCase.case_startup_migrate_now_bootstraps_logging_and_uses_preferred_root
    )
    test_schema_migration_error_dialog_suspends_splash_during_startup = (
        AppShellTestCase.case_schema_migration_error_dialog_suspends_splash_during_startup
    )
    test_portable_mode_skips_storage_migration_and_legacy_adoption = (
        AppShellTestCase.case_portable_mode_skips_storage_migration_and_legacy_adoption
    )


del AppShellTestCase
