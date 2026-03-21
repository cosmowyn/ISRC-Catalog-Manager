from tests.app._app_shell_support import AppShellTestCase


class AppShellStorageRootTransitionTests(AppShellTestCase):
    test_startup_adopts_valid_preferred_root_when_settings_still_pin_legacy = (
        AppShellTestCase.case_startup_adopts_valid_preferred_root_when_settings_still_pin_legacy
    )
    test_storage_migration_reopens_active_managed_profile_in_new_root = (
        AppShellTestCase.case_storage_migration_reopens_active_managed_profile_in_new_root
    )
    test_manual_legacy_cleanup_after_adoption_does_not_recreate_legacy_root = (
        AppShellTestCase.case_manual_legacy_cleanup_after_adoption_does_not_recreate_legacy_root
    )


del AppShellTestCase
