from tests.history._support import HistoryManagerTestCase


class HistorySnapshotTests(HistoryManagerTestCase):
    test_snapshot_actions_restore_managed_license_files = (
        HistoryManagerTestCase.case_snapshot_actions_restore_managed_license_files
    )
    test_snapshot_actions_restore_custom_field_media_and_gs1_templates = (
        HistoryManagerTestCase.case_snapshot_actions_restore_custom_field_media_and_gs1_templates
    )
    test_snapshot_actions_restore_contract_template_roots = (
        HistoryManagerTestCase.case_snapshot_actions_restore_contract_template_roots
    )
    test_registered_snapshot_can_be_restored = (
        HistoryManagerTestCase.case_registered_snapshot_can_be_restored
    )
    test_manual_snapshot_create_and_delete_can_be_undone = (
        HistoryManagerTestCase.case_manual_snapshot_create_and_delete_can_be_undone
    )
    test_snapshot_restore_preserves_audit_log_and_supports_undo_redo = (
        HistoryManagerTestCase.case_snapshot_restore_preserves_audit_log_and_supports_undo_redo
    )
    test_snapshot_history_undo_redo_does_not_duplicate_entries = (
        HistoryManagerTestCase.case_snapshot_history_undo_redo_does_not_duplicate_entries
    )
    test_missing_snapshot_file_raises_clear_error_without_creating_pre_restore_snapshot = (
        HistoryManagerTestCase.case_missing_snapshot_file_raises_clear_error_without_creating_pre_restore_snapshot
    )
    test_snapshot_restore_rolls_back_database_when_external_restore_fails = (
        HistoryManagerTestCase.case_snapshot_restore_rolls_back_database_when_external_restore_fails
    )
    test_restore_snapshot_missing_file_does_not_create_extra_restore_point = (
        HistoryManagerTestCase.case_restore_snapshot_missing_file_does_not_create_extra_restore_point
    )


del HistoryManagerTestCase
