from tests.history._support import HistoryManagerTestCase


class HistoryFileEffectTests(HistoryManagerTestCase):
    test_snapshot_actions_restore_external_file_side_effects = (
        HistoryManagerTestCase.case_snapshot_actions_restore_external_file_side_effects
    )
    test_snapshot_side_effect_failure_rolls_back_database_and_files = (
        HistoryManagerTestCase.case_snapshot_side_effect_failure_rolls_back_database_and_files
    )
    test_snapshot_actions_restore_legacy_license_migration_state = (
        HistoryManagerTestCase.case_snapshot_actions_restore_legacy_license_migration_state
    )


del HistoryManagerTestCase
