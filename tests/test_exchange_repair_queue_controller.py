import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import QDialog

from isrc_manager.exchange import ExchangeImportReport
from isrc_manager.exchange.repair_queue_controller import (
    _delete_track_import_repair_entries,
    _refresh_track_import_repair_queue_dialog,
    _repair_track_import_queue_entry,
    _track_import_repair_entries,
    _track_import_repair_work_choices,
    open_track_import_repair_queue,
)
from isrc_manager.services.import_repair_queue import TrackImportRepairEntry


def _entry(entry_id: int, **overrides) -> TrackImportRepairEntry:
    values = {
        "id": entry_id,
        "source_format": "csv",
        "source_path": "/tmp/source.csv",
        "row_index": 2,
        "import_mode": "create",
        "normalized_row": {"track_title": "Demo"},
        "mapping": {"track_title": "track_title"},
        "options": {"mode": "dry_run", "create_missing_custom_fields": True},
        "failure_category": "validation",
        "failure_message": "invalid row",
        "status": "pending",
        "created_at": None,
        "updated_at": None,
        "resolved_at": None,
        "resolved_track_id": None,
        "resolved_work_id": None,
    }
    values.update(overrides)
    return TrackImportRepairEntry(**values)


class ExchangeRepairQueueControllerTests(unittest.TestCase):
    def test_track_import_repair_entries_uses_service_status_default_and_none(self):
        service = mock.Mock()
        service.list_entries.return_value = ["pending"]

        app = SimpleNamespace(track_import_repair_queue_service=service)
        self.assertEqual(_track_import_repair_entries(app), ["pending"])
        self.assertEqual(_track_import_repair_entries(app, include_resolved=True), ["pending"])

        app.track_import_repair_queue_service = None
        self.assertEqual(_track_import_repair_entries(app), [])

    def test_track_import_repair_work_choices_formats_iswc_and_falls_back_to_default_title(self):
        app = SimpleNamespace(
            work_service=SimpleNamespace(
                list_works=lambda: [
                    SimpleNamespace(id=7, title="Work One", iswc="ABCD"),
                    SimpleNamespace(id=8, title="", iswc=""),
                ]
            )
        )

        self.assertEqual(
            _track_import_repair_work_choices(app),
            [(7, "Work One (ABCD)"), (8, "Work #8")],
        )

        app.work_service = None
        self.assertEqual(_track_import_repair_work_choices(app), [])

    def test_delete_track_import_repair_entries_handles_cancel_and_commit_paths(self):
        app = SimpleNamespace(
            track_import_repair_queue_service=mock.Mock(delete_entries=mock.Mock(return_value=2)),
            conn=mock.Mock(commit=mock.Mock()),
            _refresh_track_import_repair_queue_dialog=mock.Mock(),
        )
        status_bar = mock.Mock()
        app.statusBar = mock.Mock(return_value=status_bar)

        with mock.patch(
            "isrc_manager.exchange.repair_queue_controller._message_box"
        ) as message_box:
            message_box.return_value = box = mock.Mock(
                Yes=1,
                No=2,
                question=mock.Mock(return_value=2),
            )
            _delete_track_import_repair_entries(app, [1, 2])
            app.track_import_repair_queue_service.delete_entries.assert_not_called()
            box.question.assert_called_once()

            box.question.return_value = 1
            _delete_track_import_repair_entries(app, [1, 2, 1])
            app.track_import_repair_queue_service.delete_entries.assert_called_once_with([1, 2])
            app.conn.commit.assert_called_once()
            app._refresh_track_import_repair_queue_dialog.assert_called_once()
            status_bar.showMessage.assert_called_once_with("Deleted 2 import repair row(s).", 5000)

            app.conn.commit.side_effect = RuntimeError("closed")
            app.statusBar = mock.Mock(return_value=None)
            _delete_track_import_repair_entries(app, [3])
            app.track_import_repair_queue_service.delete_entries.assert_called_with([3])

        no_service_app = SimpleNamespace(track_import_repair_queue_service=None)
        _delete_track_import_repair_entries(no_service_app, [1])
        service_app = SimpleNamespace(track_import_repair_queue_service=mock.Mock())
        _delete_track_import_repair_entries(service_app, [0, -1])
        service_app.track_import_repair_queue_service.delete_entries.assert_not_called()

    def test_refresh_track_import_repair_queue_dialog_only_refreshes_visible_dialog(self):
        class FakeQueueDialog:
            def __init__(self, visible):
                self._visible = visible
                self.refresh_entries = mock.Mock()

            def isVisible(self):
                return self._visible

        with mock.patch(
            "isrc_manager.exchange.repair_queue_controller.TrackImportRepairQueueDialog",
            FakeQueueDialog,
        ):
            visible_dialog = FakeQueueDialog(True)
            _refresh_track_import_repair_queue_dialog(
                SimpleNamespace(track_import_repair_queue_dialog=visible_dialog)
            )
            visible_dialog.refresh_entries.assert_called_once()

            hidden_dialog = FakeQueueDialog(False)
            _refresh_track_import_repair_queue_dialog(
                SimpleNamespace(track_import_repair_queue_dialog=hidden_dialog)
            )
            hidden_dialog.refresh_entries.assert_not_called()

            _refresh_track_import_repair_queue_dialog(SimpleNamespace())

    def test_repair_entry_requires_services_and_warns_when_missing(self):
        with mock.patch(
            "isrc_manager.exchange.repair_queue_controller._message_box"
        ) as message_box:
            message_box.return_value = mock.Mock(warning=mock.Mock())

            app = SimpleNamespace(
                track_import_repair_queue_service=None,
                exchange_service=mock.Mock(),
            )
            _repair_track_import_queue_entry(app, 7)
            message_box.return_value.warning.assert_called_once()

    def test_repair_entry_rejects_when_entry_missing(self):
        with mock.patch(
            "isrc_manager.exchange.repair_queue_controller._message_box"
        ) as message_box:
            message_box.return_value = mock.Mock(
                question=mock.Mock(),
                information=mock.Mock(),
                warning=mock.Mock(),
            )
            app = SimpleNamespace(
                track_import_repair_queue_service=mock.Mock(
                    fetch_entry=mock.Mock(return_value=None)
                ),
                exchange_service=mock.Mock(),
                _track_import_repair_work_choices=lambda: [],
                _refresh_track_import_repair_queue_dialog=mock.Mock(),
                statusBar=lambda: None,
            )
            _repair_track_import_queue_entry(app, 99)

            message_box.return_value.information.assert_called_once()
            app._refresh_track_import_repair_queue_dialog.assert_called_once()

    def test_repair_entry_launches_background_task_with_normalized_options(self):
        app = SimpleNamespace(
            track_import_repair_queue_service=mock.Mock(
                fetch_entry=mock.Mock(return_value=_entry(17)),
            ),
            exchange_service=mock.Mock(import_prepared_rows=mock.Mock()),
            _track_import_repair_work_choices=lambda: [],
            statusBar=lambda: None,
            _scaled_progress_callback=lambda callback, **_kwargs: callback,
            _submit_background_bundle_task=mock.Mock(),
            _advance_task_ui_progress=mock.Mock(),
            _show_background_task_error=mock.Mock(),
            refresh_table_preserve_view=mock.Mock(),
            populate_all_comboboxes=mock.Mock(),
            _refresh_track_import_repair_queue_dialog=mock.Mock(),
            conn=mock.Mock(),
        )

        dialog = mock.Mock(
            exec=mock.Mock(return_value=QDialog.Accepted),
            edited_row=mock.Mock(return_value={"track_title": "Demo"}),
            repair_override=mock.Mock(
                return_value={"governance_mode": "create_new_work", "work_id": None}
            ),
        )
        app.conn.commit = mock.Mock()

        with (
            mock.patch("isrc_manager.exchange.repair_queue_controller._root_attr") as root_attr,
            mock.patch("isrc_manager.exchange.repair_queue_controller._message_box") as message_box,
        ):
            message_box.return_value = mock.Mock()
            root_attr.side_effect = lambda _name, _fallback: mock.Mock(return_value=dialog)

            _repair_track_import_queue_entry(app, 17)

            app._submit_background_bundle_task.assert_called_once()
            arguments = app._submit_background_bundle_task.call_args
            captured_task = arguments.kwargs["task_fn"]
            captured_before = arguments.kwargs["on_success_before_cleanup"]
            captured_after = arguments.kwargs["on_success_after_cleanup"]

            worker_bundle = mock.Mock(exchange_service=app.exchange_service)
            worker_ctx = mock.Mock(
                raise_if_cancelled=mock.Mock(),
                report_progress=mock.Mock(),
            )
            app.exchange_service.import_prepared_rows.return_value = ExchangeImportReport(
                format_name="csv",
                mode="dry_run",
                passed=False,
                failed=0,
                skipped=0,
                warnings=[],
                duplicates=[],
                unknown_fields=[],
            )

            captured_task(worker_bundle, worker_ctx)
            app.exchange_service.import_prepared_rows.assert_called_once()
            call_kwargs = app.exchange_service.import_prepared_rows.call_args.kwargs
            self.assertEqual(call_kwargs["options"].mode, "create")
            self.assertEqual(call_kwargs["format_name"], "csv")
            self.assertEqual(call_kwargs["repair_entry_id"], 17)

            progress_handle = object()
            refresh_report = ExchangeImportReport(
                format_name="csv",
                mode="create",
                passed=1,
                failed=0,
                skipped=0,
                warnings=[],
                duplicates=[],
                unknown_fields=[],
                created_tracks=[101],
            )
            captured_before(refresh_report, progress_handle)
            app.conn.commit.assert_called_once()
            app.refresh_table_preserve_view.assert_called_once_with(focus_id=101)
            app.populate_all_comboboxes.assert_called_once()
            app._advance_task_ui_progress.assert_any_call(
                progress_handle,
                value=100,
                message="Import repair row complete.",
            )

            report = ExchangeImportReport(
                format_name="csv",
                mode="create",
                passed=1,
                failed=0,
                skipped=0,
                warnings=[],
                duplicates=[],
                unknown_fields=[],
            )
            captured_after(report)

            message_box.return_value.warning.assert_not_called()
            status_bar = mock.Mock()
            app.statusBar = mock.Mock(return_value=status_bar)
            captured_after(report)
            status_bar.showMessage.assert_called_once_with("Import repair row applied.", 5000)

            failed_report = ExchangeImportReport(
                format_name="csv",
                mode="create",
                passed=False,
                failed=1,
                skipped=0,
                warnings=["still invalid"],
                duplicates=[],
                unknown_fields=[],
            )
            captured_after(failed_report)
            message_box.return_value.warning.assert_called_once()

    def test_repair_entry_defaults_options_when_saved_options_are_empty(self):
        app = SimpleNamespace(
            track_import_repair_queue_service=mock.Mock(
                fetch_entry=mock.Mock(return_value=_entry(33, options={})),
            ),
            exchange_service=mock.Mock(import_prepared_rows=mock.Mock()),
            _track_import_repair_work_choices=lambda: [],
            statusBar=lambda: None,
            _scaled_progress_callback=lambda callback, **_kwargs: callback,
            _submit_background_bundle_task=mock.Mock(),
            _advance_task_ui_progress=mock.Mock(),
            _show_background_task_error=mock.Mock(),
            refresh_table_preserve_view=mock.Mock(),
            populate_all_comboboxes=mock.Mock(),
            _refresh_track_import_repair_queue_dialog=mock.Mock(),
            conn=mock.Mock(commit=mock.Mock()),
        )
        dialog = mock.Mock(
            exec=mock.Mock(return_value=QDialog.Accepted),
            edited_row=mock.Mock(return_value={"track_title": "Demo"}),
            repair_override=mock.Mock(return_value={}),
        )

        with mock.patch(
            "isrc_manager.exchange.repair_queue_controller._root_attr",
            side_effect=lambda _name, _fallback: mock.Mock(return_value=dialog),
        ):
            _repair_track_import_queue_entry(app, 33)

        task = app._submit_background_bundle_task.call_args.kwargs["task_fn"]
        task(
            SimpleNamespace(exchange_service=app.exchange_service),
            SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock()),
        )
        options = app.exchange_service.import_prepared_rows.call_args.kwargs["options"]
        self.assertEqual(options.mode, "create")

    def test_repair_entry_rejects_dialog_without_submitting_task(self):
        app = SimpleNamespace(
            track_import_repair_queue_service=mock.Mock(
                fetch_entry=mock.Mock(return_value=_entry(22))
            ),
            exchange_service=mock.Mock(),
            _track_import_repair_work_choices=lambda: [],
            _submit_background_bundle_task=mock.Mock(),
        )
        dialog = mock.Mock(exec=mock.Mock(return_value=QDialog.Rejected))

        with mock.patch(
            "isrc_manager.exchange.repair_queue_controller._root_attr",
            side_effect=lambda _name, _fallback: mock.Mock(return_value=dialog),
        ):
            _repair_track_import_queue_entry(app, 22)

        app._submit_background_bundle_task.assert_not_called()

    def test_open_track_import_repair_queue_focuses_matching_row_and_warns_without_service(self):
        with mock.patch(
            "isrc_manager.exchange.repair_queue_controller._message_box"
        ) as message_box:
            message_box.return_value = mock.Mock(warning=mock.Mock())
            open_track_import_repair_queue(
                SimpleNamespace(track_import_repair_queue_service=None),
            )
            message_box.return_value.warning.assert_called_once()

        class _Item:
            def __init__(self, text):
                self._text = text

            def text(self):
                return self._text

        table = SimpleNamespace(
            rowCount=mock.Mock(return_value=4),
            item=mock.Mock(side_effect=[None, _Item("not-int"), _Item("42"), _Item("43")]),
            selectRow=mock.Mock(),
        )
        dialog = mock.Mock(table=table, refresh_entries=mock.Mock(), exec=mock.Mock())
        app = SimpleNamespace(
            track_import_repair_queue_service=mock.Mock(),
            _track_import_repair_entries=mock.Mock(return_value=[]),
            _repair_track_import_queue_entry=mock.Mock(),
            _delete_track_import_repair_entries=mock.Mock(),
        )

        with mock.patch(
            "isrc_manager.exchange.repair_queue_controller._root_attr",
            side_effect=lambda _name, _fallback: mock.Mock(return_value=dialog),
        ):
            open_track_import_repair_queue(app, focus_entry_id=42)

        self.assertIs(app.track_import_repair_queue_dialog, dialog)
        dialog.refresh_entries.assert_called_once()
        table.selectRow.assert_called_once_with(2)
        dialog.exec.assert_called_once()


if __name__ == "__main__":
    unittest.main()
