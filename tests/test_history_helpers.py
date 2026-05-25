import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isrc_manager.tasks.history_helpers import (
    _emit_progress,
    run_file_history_action,
    run_snapshot_history_action,
)


@dataclass
class _Snapshot:
    snapshot_id: str


class HistoryHelpersTests(unittest.TestCase):
    def test_emit_progress_is_noop_for_missing_callback_or_update(self):
        _emit_progress(None, (1, "ignored"))
        _emit_progress(mock.Mock(), None)

    def test_emit_progress_calls_callback_with_normalized_args(self):
        progress = mock.Mock()
        update = (42, "  ready   ")

        _emit_progress(progress, update)

        progress.assert_called_once_with(42, 100, "  ready   ")

    def test_run_snapshot_history_action_bypasses_history_when_manager_missing(self):
        mutation = mock.Mock(return_value="ok")

        result = run_snapshot_history_action(
            history_manager=None,
            action_label="noop",
            action_type="noop.action",
            mutation=mutation,
        )

        self.assertEqual(result, "ok")
        mutation.assert_called_once_with()

    def test_run_snapshot_history_action_records_when_history_manager_present(self):
        before = _Snapshot("before")
        after = _Snapshot("after")
        manager = SimpleNamespace(
            capture_snapshot=mock.Mock(side_effect=[before, after]),
            record_snapshot_action=mock.Mock(return_value=mock.Mock()),
            restore_snapshot=mock.Mock(),
            delete_snapshot=mock.Mock(),
        )
        progress = mock.Mock()
        mutation = mock.Mock(return_value="done")

        result = run_snapshot_history_action(
            history_manager=manager,
            action_label="Create Track",
            action_type="track.create",
            mutation=mutation,
            entity_type="Track",
            entity_id=99,
            payload={"title": "X"},
            post_mutation_progress=(10, "after mutation"),
            record_progress=(50, "recorded"),
            logger=mock.Mock(),
            progress_callback=progress,
        )

        self.assertEqual(result, "done")
        self.assertEqual(progress.call_count, 2)
        progress.assert_any_call(10, 100, "after mutation")
        progress.assert_any_call(50, 100, "recorded")
        mutation.assert_called_once_with()
        manager.record_snapshot_action.assert_called_once_with(
            label="Create Track",
            action_type="track.create",
            entity_type="Track",
            entity_id="99",
            payload={"title": "X"},
            snapshot_before_id="before",
            snapshot_after_id="after",
        )

    def test_run_snapshot_history_action_rollback_restores_state_on_error(self):
        before = _Snapshot("before")
        manager = SimpleNamespace(
            capture_snapshot=mock.Mock(return_value=before),
            record_snapshot_action=mock.Mock(side_effect=RuntimeError("boom")),
            restore_snapshot=mock.Mock(),
            delete_snapshot=mock.Mock(),
        )

        with self.assertRaises(RuntimeError):
            run_snapshot_history_action(
                history_manager=manager,
                action_label="rollback",
                action_type="track.rollback",
                mutation=mock.Mock(return_value="never"),
            )

        manager.restore_snapshot.assert_called_once_with("before")
        manager.delete_snapshot.assert_has_calls([mock.call("before"), mock.call("before")])

    def test_run_file_history_action_bypasses_history_when_manager_missing(self):
        mutation = mock.Mock(return_value="/tmp/out.txt")

        result = run_file_history_action(
            history_manager=None,
            action_label="write",
            action_type="file.write",
            target_path=Path("/tmp/out.txt"),
            mutation=mutation,
        )

        self.assertEqual(result, "/tmp/out.txt")
        mutation.assert_called_once_with()

    def test_run_file_history_action_rejects_directory_target(self):
        app_dir = Path("/tmp")

        result = run_file_history_action(
            history_manager=SimpleNamespace(capture_file_state=mock.Mock()),
            action_label="write",
            action_type="file.write",
            target_path=app_dir,
            mutation=mock.Mock(return_value="directory"),
        )

        self.assertEqual(result, "directory")

    def test_run_file_history_action_records_only_when_state_changes(self):
        manager = SimpleNamespace(
            capture_file_state=mock.Mock(side_effect=[{"size": 1}, {"size": 2}]),
            record_file_write_action=mock.Mock(),
            restore_file_state=mock.Mock(),
        )
        mutation = mock.Mock(return_value="/tmp/out.bin")

        result = run_file_history_action(
            history_manager=manager,
            action_label=lambda result: "Write file",
            action_type="file.write",
            target_path=Path("/tmp/out.bin"),
            mutation=mutation,
            entity_type="File",
            payload=lambda value: {"result": value},
            progress_callback=mock.Mock(),
            post_mutation_progress=(12, "before"),
            record_progress=(88, "after"),
        )

        self.assertEqual(result, "/tmp/out.bin")
        manager.record_file_write_action.assert_called_once()
        call_kwargs = manager.record_file_write_action.call_args.kwargs
        self.assertEqual(call_kwargs["label"], "Write file")
        self.assertEqual(call_kwargs["action_type"], "file.write")
        self.assertEqual(call_kwargs["entity_type"], "File")
        self.assertEqual(call_kwargs["target_path"], Path("/tmp/out.bin"))
        self.assertEqual(call_kwargs["payload"], {"result": "/tmp/out.bin"})

    def test_run_file_history_action_rolls_back_file_state_when_mutation_fails(self):
        manager = SimpleNamespace(
            capture_file_state=mock.Mock(return_value={"size": 10}),
            restore_file_state=mock.Mock(),
            record_file_write_action=mock.Mock(),
        )

        with self.assertRaises(RuntimeError):
            run_file_history_action(
                history_manager=manager,
                action_label="write",
                action_type="file.write",
                target_path=Path("/tmp/out.bin"),
                mutation=mock.Mock(side_effect=RuntimeError("write failed")),
                progress_callback=mock.Mock(),
            )

        manager.restore_file_state.assert_called_once_with(Path("/tmp/out.bin"), {"size": 10})
