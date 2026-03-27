from tests.history._support import HistoryManagerTestCase


class HistoryActionHelperTests(HistoryManagerTestCase):
    test_run_snapshot_history_action_rolls_back_when_history_recording_fails = (
        HistoryManagerTestCase.case_run_snapshot_history_action_rolls_back_when_history_recording_fails
    )
    test_snapshot_helper_rolls_back_when_history_recording_fails = (
        HistoryManagerTestCase.case_snapshot_helper_rolls_back_when_history_recording_fails
    )
    test_file_helper_rolls_back_when_history_recording_fails = (
        HistoryManagerTestCase.case_file_helper_rolls_back_when_history_recording_fails
    )
    test_file_helper_rejects_directory_target_before_mutation = (
        HistoryManagerTestCase.case_file_helper_rejects_directory_target_before_mutation
    )


del HistoryManagerTestCase
