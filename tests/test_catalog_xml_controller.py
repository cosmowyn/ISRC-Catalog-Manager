from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isrc_manager.exchange import catalog_xml_controller as xml_controller


class _Box:
    Yes = 1
    No = 2

    def __init__(self):
        self.information = mock.Mock()
        self.warning = mock.Mock()
        self.question = mock.Mock(return_value=self.Yes)


def _app(tmp_path: Path, *, track_ids=(7, 9)):
    return SimpleNamespace(
        exports_dir=tmp_path,
        current_db_path=tmp_path / "profile.db",
        logger=mock.Mock(),
        _resolve_file_export_target=mock.Mock(side_effect=lambda path, **_kwargs: Path(path)),
        _scaled_progress_callback=mock.Mock(side_effect=lambda callback, **_kwargs: callback),
        _submit_background_bundle_task=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        _catalog_table_controller=lambda: SimpleNamespace(
            selected_or_visible_track_ids=lambda: list(track_ids)
        ),
        import_exchange_file=mock.Mock(),
    )


def test_export_full_to_xml_handles_cancel_invalid_target_and_overwrite_reject(
    monkeypatch, tmp_path
):
    app = _app(tmp_path)
    box = _Box()
    dialog = SimpleNamespace(getSaveFileName=mock.Mock(return_value=("", "")))
    monkeypatch.setattr(xml_controller, "_file_dialog", lambda: dialog)
    monkeypatch.setattr(xml_controller, "_message_box", lambda: box)

    xml_controller.export_full_to_xml(app)
    app._submit_background_bundle_task.assert_not_called()

    dialog.getSaveFileName.return_value = (str(tmp_path / "bad.xml"), "")
    app._resolve_file_export_target.side_effect = ValueError("outside export root")
    xml_controller.export_full_to_xml(app)
    box.warning.assert_called_once_with(app, "Export", "outside export root")

    existing = tmp_path / "existing.xml"
    existing.write_text("<old/>", encoding="utf-8")
    app._resolve_file_export_target.side_effect = lambda path, **_kwargs: Path(path)
    box.question.return_value = box.No
    dialog.getSaveFileName.return_value = (str(existing), "")
    xml_controller.export_full_to_xml(app)
    app._submit_background_bundle_task.assert_not_called()


def test_export_full_to_xml_submits_history_worker_and_success_callback(monkeypatch, tmp_path):
    app = _app(tmp_path)
    target = tmp_path / "catalog.xml"
    box = _Box()
    dialog = SimpleNamespace(getSaveFileName=mock.Mock(return_value=(str(target), "")))
    history_calls = []

    def fake_history_action(**kwargs):
        exported = kwargs["mutation"]()
        history_calls.append((kwargs, kwargs["payload"](exported)))
        return exported

    monkeypatch.setattr(xml_controller, "_file_dialog", lambda: dialog)
    monkeypatch.setattr(xml_controller, "_message_box", lambda: box)
    monkeypatch.setattr(
        xml_controller,
        "_root_attr",
        lambda name, fallback: (
            fake_history_action if name == "run_file_history_action" else fallback
        ),
    )

    xml_controller.export_full_to_xml(app)

    app._submit_background_bundle_task.assert_called_once()
    kwargs = app._submit_background_bundle_task.call_args.kwargs
    bundle = SimpleNamespace(
        history_manager=mock.Mock(),
        xml_export_service=mock.Mock(export_all=mock.Mock(return_value=12)),
    )
    ctx = SimpleNamespace(report_progress=mock.Mock())

    assert kwargs["task_fn"](bundle, ctx) == 12
    assert history_calls[0][0]["action_type"] == "file.export_xml_all"
    assert history_calls[0][1] == {"path": str(target), "count": 12}
    bundle.xml_export_service.export_all.assert_called_once()

    kwargs["on_success_after_cleanup"](12)
    app._refresh_history_actions.assert_called_once()
    box.information.assert_called_once_with(app, "Export", f"All data exported:\n{target}")
    app._audit.assert_called_once()
    app._audit_commit.assert_called_once()


def test_export_selected_to_xml_empty_cancel_invalid_and_worker_paths(monkeypatch, tmp_path):
    empty_app = _app(tmp_path, track_ids=())
    box = _Box()
    dialog = SimpleNamespace(getSaveFileName=mock.Mock(return_value=("", "")))
    monkeypatch.setattr(xml_controller, "_file_dialog", lambda: dialog)
    monkeypatch.setattr(xml_controller, "_message_box", lambda: box)

    xml_controller.export_selected_to_xml(empty_app)
    box.information.assert_called_once()

    app = _app(tmp_path, track_ids=(3, 5))
    xml_controller.export_selected_to_xml(app)
    app._submit_background_bundle_task.assert_not_called()

    dialog.getSaveFileName.return_value = (str(tmp_path / "selected.xml"), "")
    app._resolve_file_export_target.side_effect = ValueError("not writable")
    xml_controller.export_selected_to_xml(app)
    box.warning.assert_called_once_with(app, "Export Selected", "not writable")

    target = tmp_path / "selected.xml"
    app._resolve_file_export_target.side_effect = lambda path, **_kwargs: Path(path)
    history_calls = []

    def fake_history_action(**kwargs):
        exported = kwargs["mutation"]()
        history_calls.append((kwargs, kwargs["payload"](exported)))
        return exported

    monkeypatch.setattr(
        xml_controller,
        "_root_attr",
        lambda name, fallback: (
            fake_history_action if name == "run_file_history_action" else fallback
        ),
    )
    xml_controller.export_selected_to_xml(app)

    kwargs = app._submit_background_bundle_task.call_args.kwargs
    bundle = SimpleNamespace(
        history_manager=mock.Mock(),
        xml_export_service=mock.Mock(export_selected=mock.Mock(return_value=2)),
    )
    ctx = SimpleNamespace(report_progress=mock.Mock())

    assert kwargs["task_fn"](bundle, ctx) == 2
    bundle.xml_export_service.export_selected.assert_called_once()
    assert bundle.xml_export_service.export_selected.call_args.args[:2] == (target, [3, 5])
    assert history_calls[0][1] == {"path": str(target), "count": 2, "track_ids": [3, 5]}

    kwargs["on_success_after_cleanup"](2)
    app._refresh_history_actions.assert_called_once()
    app._log_event.assert_called_once()
    assert box.information.call_args.args == (app, "Export Complete", f"Saved:\n{target}")


def test_import_from_xml_routes_to_exchange_importer(tmp_path):
    app = _app(tmp_path)

    xml_controller.import_from_xml(app)

    app.import_exchange_file.assert_called_once_with("xml")
