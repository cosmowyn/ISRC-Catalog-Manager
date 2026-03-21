from tests.history._support import HistoryManagerTestCase


class HistoryRecoveryTests(HistoryManagerTestCase):
    test_repair_recovery_state_relinks_missing_snapshot_and_registers_orphan_backup = (
        HistoryManagerTestCase.case_repair_recovery_state_relinks_missing_snapshot_and_registers_orphan_backup
    )
    test_repair_recovery_state_rebuilds_missing_backup_history_artifacts = (
        HistoryManagerTestCase.case_repair_recovery_state_rebuilds_missing_backup_history_artifacts
    )
    test_repair_recovery_state_quarantines_referenced_missing_snapshot = (
        HistoryManagerTestCase.case_repair_recovery_state_quarantines_referenced_missing_snapshot
    )


del HistoryManagerTestCase
