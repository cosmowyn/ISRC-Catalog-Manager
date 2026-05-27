from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from isrc_manager.exchange import repertoire_controller
from isrc_manager.exchange.repertoire_service import RepertoireImportInspection


class _Messages:
    def __init__(self) -> None:
        self.warnings: list[tuple[object, str, str]] = []

    def warning(self, *args):
        self.warnings.append(args)


class _StatusBar:
    def __init__(self) -> None:
        self.messages: list[tuple[str, int]] = []

    def showMessage(self, message: str, timeout: int) -> None:
        self.messages.append((message, timeout))


class _Progress:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    def report_progress(self, **kwargs) -> None:
        self.updates.append(kwargs)

    def raise_if_cancelled(self) -> None:
        return None


def _inspection(format_name: str, path: Path) -> RepertoireImportInspection:
    return RepertoireImportInspection(
        file_path=str(path),
        format_name=format_name,
        entity_counts={
            "parties": 1,
            "works": 2,
            "contracts": 3,
            "rights": 4,
            "assets": 5,
        },
        preview_rows=[{"Entity": "Party", "Action": "Create", "Label": "Lumen"}],
        warnings=["review warning"],
        existing_parties=6,
        new_parties=7,
    )


def _app(tmp_path: Path, service: mock.Mock | None = None) -> SimpleNamespace:
    status_bar = _StatusBar()
    app = SimpleNamespace(
        repertoire_exchange_service=service if service is not None else mock.Mock(),
        exports_dir=tmp_path,
        logger=mock.Mock(),
        submitted=[],
        ui_progress=[],
        conn=SimpleNamespace(commit=mock.Mock(side_effect=RuntimeError("commit failed"))),
        _resolve_file_export_target=lambda path, **_kwargs: Path(path),
        _resolve_directory_export_target=lambda path, **_kwargs: Path(path),
        _scaled_progress_callback=lambda callback, **_kwargs: callback,
        _submit_background_bundle_task=lambda **kwargs: app.submitted.append(kwargs),
        _advance_task_ui_progress=lambda _ui_progress, **kwargs: app.ui_progress.append(kwargs),
        _refresh_catalog_workspace_docks=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        populate_all_comboboxes=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        _open_import_review_dialog=mock.Mock(return_value=True),
        _repertoire_import_review_summary=repertoire_controller._repertoire_import_review_summary,
        statusBar=lambda: status_bar,
    )
    app.status_bar = status_bar
    return app


def test_repertoire_controller_wrappers_and_review_summary(monkeypatch, tmp_path) -> None:
    message_box = object()
    file_dialog = object()

    monkeypatch.setattr(
        repertoire_controller,
        "_root_attr",
        lambda name, fallback: {
            "QMessageBox": message_box,
            "QFileDialog": file_dialog,
        }.get(name, fallback),
    )

    assert repertoire_controller._message_box() is message_box
    assert repertoire_controller._file_dialog() is file_dialog

    summary = repertoire_controller._repertoire_import_review_summary(
        _inspection("json", tmp_path / "catalog.json")
    )

    assert "Parties found: 1" in summary
    assert "Works found: 2" in summary
    assert "Contracts found: 3" in summary
    assert "Rights found: 4" in summary
    assert "Assets found: 5" in summary
    assert "Would create Parties: 7" in summary
    assert "Would reuse existing Parties: 6" in summary


def test_export_repertoire_exchange_missing_profile_cancel_bad_target_and_unsupported(
    monkeypatch,
    tmp_path,
) -> None:
    messages = _Messages()
    file_dialog = mock.Mock()
    monkeypatch.setattr(repertoire_controller, "_message_box", lambda: messages)
    monkeypatch.setattr(repertoire_controller, "_file_dialog", lambda: file_dialog)

    repertoire_controller.export_repertoire_exchange(
        SimpleNamespace(repertoire_exchange_service=None),
        "json",
    )
    assert messages.warnings[-1][2] == "Open a profile first."

    app = _app(tmp_path)
    file_dialog.getSaveFileName.return_value = ("", "")
    file_dialog.getExistingDirectory.return_value = ""
    for format_name in ("json", "xlsx", "csv", "package"):
        repertoire_controller.export_repertoire_exchange(app, format_name)
    assert app.submitted == []

    app._resolve_file_export_target = mock.Mock(side_effect=ValueError("bad file target"))
    file_dialog.getSaveFileName.return_value = (str(tmp_path / "bad.json"), "")
    repertoire_controller.export_repertoire_exchange(app, "json")
    assert messages.warnings[-1][2] == "bad file target"

    app._resolve_directory_export_target = mock.Mock(side_effect=ValueError("bad dir target"))
    file_dialog.getExistingDirectory.return_value = str(tmp_path / "bundle")
    repertoire_controller.export_repertoire_exchange(app, "csv")
    assert messages.warnings[-1][2] == "bad dir target"

    before = len(app.submitted)
    repertoire_controller.export_repertoire_exchange(app, "unsupported")
    assert len(app.submitted) == before


@pytest.mark.parametrize(
    ("format_name", "service_method", "uses_directory"),
    [
        ("json", "export_json", False),
        ("xlsx", "export_xlsx", False),
        ("csv", "export_csv_bundle", True),
        ("package", "export_package", False),
    ],
)
def test_export_repertoire_exchange_dispatches_formats_through_history(
    monkeypatch,
    tmp_path,
    format_name,
    service_method,
    uses_directory,
) -> None:
    service = mock.Mock()
    app = _app(tmp_path, service=service)
    output = tmp_path / ("bundle" if uses_directory else f"repertoire.{format_name}")
    file_dialog = mock.Mock()
    file_dialog.getSaveFileName.return_value = (str(output), "")
    file_dialog.getExistingDirectory.return_value = str(output)
    monkeypatch.setattr(repertoire_controller, "_file_dialog", lambda: file_dialog)
    monkeypatch.setattr(
        repertoire_controller,
        "_root_attr",
        lambda name, fallback: (
            (lambda **kwargs: kwargs["mutation"]())
            if name in {"run_file_history_action", "run_snapshot_history_action"}
            else fallback
        ),
    )

    repertoire_controller.export_repertoire_exchange(app, format_name)

    task = app.submitted[-1]
    bundle = SimpleNamespace(repertoire_exchange_service=service, history_manager=object())
    result = task["task_fn"](bundle, _Progress())
    task["on_success_after_cleanup"](result)

    assert result == str(output)
    getattr(service, service_method).assert_called_once_with(output, progress_callback=mock.ANY)
    assert app.status_bar.messages == [("Repertoire export complete.", 5000)]


def test_import_repertoire_exchange_missing_profile_cancel_and_rejected_review(
    monkeypatch,
    tmp_path,
) -> None:
    messages = _Messages()
    file_dialog = mock.Mock()
    monkeypatch.setattr(repertoire_controller, "_message_box", lambda: messages)
    monkeypatch.setattr(repertoire_controller, "_file_dialog", lambda: file_dialog)

    repertoire_controller.import_repertoire_exchange(
        SimpleNamespace(repertoire_exchange_service=None),
        "json",
    )
    assert messages.warnings[-1][2] == "Open a profile first."

    app = _app(tmp_path)
    file_dialog.getOpenFileName.return_value = ("", "")
    file_dialog.getExistingDirectory.return_value = ""
    for format_name in ("json", "xlsx", "csv", "package"):
        repertoire_controller.import_repertoire_exchange(app, format_name)
    assert app.submitted == []

    file_dialog.getOpenFileName.return_value = (str(tmp_path / "catalog.json"), "")
    app._open_import_review_dialog.return_value = False
    service = mock.Mock()
    service.inspect_json.return_value = _inspection("json", tmp_path / "catalog.json")
    app.repertoire_exchange_service = service
    repertoire_controller.import_repertoire_exchange(app, "json")
    inspect_task = app.submitted[-1]
    inspection = inspect_task["task_fn"](
        SimpleNamespace(repertoire_exchange_service=service),
        _Progress(),
    )
    inspect_task["on_success_after_cleanup"](inspection)
    assert len(app.submitted) == 1


@pytest.mark.parametrize(
    ("format_name", "inspect_method", "import_method", "uses_directory"),
    [
        ("json", "inspect_json", "import_json", False),
        ("xlsx", "inspect_xlsx", "import_xlsx", False),
        ("csv", "inspect_csv_bundle", "import_csv_bundle", True),
        ("package", "inspect_package", "import_package", False),
    ],
)
def test_import_repertoire_exchange_dispatches_formats_and_refreshes_views(
    monkeypatch,
    tmp_path,
    format_name,
    inspect_method,
    import_method,
    uses_directory,
) -> None:
    source = tmp_path / ("bundle" if uses_directory else f"catalog.{format_name}")
    service = mock.Mock()
    inspection = _inspection(format_name, source)
    getattr(service, inspect_method).return_value = inspection
    getattr(service, import_method).return_value = {"imported": format_name}
    app = _app(tmp_path, service=service)
    file_dialog = mock.Mock()
    file_dialog.getOpenFileName.return_value = (str(source), "")
    file_dialog.getExistingDirectory.return_value = str(source)
    monkeypatch.setattr(repertoire_controller, "_file_dialog", lambda: file_dialog)
    monkeypatch.setattr(
        repertoire_controller,
        "_root_attr",
        lambda name, fallback: (
            (lambda **kwargs: kwargs["mutation"]())
            if name == "run_snapshot_history_action"
            else fallback
        ),
    )

    repertoire_controller.import_repertoire_exchange(app, format_name)

    bundle = SimpleNamespace(repertoire_exchange_service=service, history_manager=object())
    inspect_task = app.submitted[-1]
    assert inspect_task["task_fn"](bundle, _Progress()) is inspection
    inspect_task["on_success_after_cleanup"](inspection)

    import_task = app.submitted[-1]
    result = import_task["task_fn"](bundle, _Progress())
    assert result == {"imported": format_name}

    ui_progress = object()
    import_task["on_success_before_cleanup"](result, ui_progress)
    import_task["on_success_after_cleanup"](result)

    getattr(service, inspect_method).assert_called_once_with(
        str(source),
        progress_callback=mock.ANY,
        cancel_callback=mock.ANY,
    )
    getattr(service, import_method).assert_called_once_with(
        str(source),
        progress_callback=mock.ANY,
        cancel_callback=mock.ANY,
    )
    app.refresh_table_preserve_view.assert_called_once_with()
    app.populate_all_comboboxes.assert_called_once_with()
    app._refresh_catalog_workspace_docks.assert_called_once_with()
    app._refresh_history_actions.assert_called_once_with()
    assert app.status_bar.messages == [("Repertoire import complete.", 5000)]
