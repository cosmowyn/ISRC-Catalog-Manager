from tests.history._support import HistoryManagerTestCase


class HistorySettingsTests(HistoryManagerTestCase):
    test_setting_change_undo_and_redo_are_persistent = (
        HistoryManagerTestCase.case_setting_change_undo_and_redo_are_persistent
    )
    test_auto_snapshot_setting_changes_undo_and_redo = (
        HistoryManagerTestCase.case_auto_snapshot_setting_changes_undo_and_redo
    )
    test_expanded_theme_settings_undo_and_redo_restore_new_fields = (
        HistoryManagerTestCase.case_expanded_theme_settings_undo_and_redo_restore_new_fields
    )
    test_setting_bundle_change_restores_qpoint_and_coalesces = (
        HistoryManagerTestCase.case_setting_bundle_change_restores_qpoint_and_coalesces
    )
    test_hidden_internal_entries_are_skipped_by_visible_history_and_boundary_undo = (
        HistoryManagerTestCase.case_hidden_internal_entries_are_skipped_by_visible_history_and_boundary_undo
    )
    test_branching_after_undo_supersedes_old_redo = (
        HistoryManagerTestCase.case_branching_after_undo_supersedes_old_redo
    )


del HistoryManagerTestCase
