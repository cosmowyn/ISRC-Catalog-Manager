from tests.history._support import HistoryManagerTestCase


class HistoryTrackActionTests(HistoryManagerTestCase):
    test_track_create_delete_and_redo_work_through_history = (
        HistoryManagerTestCase.case_track_create_delete_and_redo_work_through_history
    )
    test_record_event_and_missing_track_recording_errors_are_explicit = (
        HistoryManagerTestCase.case_record_event_and_missing_track_recording_errors_are_explicit
    )
    test_track_update_and_snapshot_restore_round_trip = (
        HistoryManagerTestCase.case_track_update_and_snapshot_restore_round_trip
    )


del HistoryManagerTestCase
