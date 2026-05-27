from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from PySide6.QtWidgets import QDialog

from isrc_manager.exchange import ExchangeImportOptions, ExchangeImportReport, ExchangeInspection
from isrc_manager.exchange import controller as exchange_controller


def _report(**overrides):
    values = {
        "format_name": "CSV",
        "mode": "dry_run",
        "passed": 2,
        "failed": 1,
        "skipped": 3,
        "warnings": ["missing album"],
        "duplicates": ["ISRC duplicate"],
        "unknown_fields": ["unexpected_column"],
    }
    values.update(overrides)
    return ExchangeImportReport(**values)


def test_exchange_import_review_summary_includes_identifier_and_duplicate_details():
    report = _report(
        evaluated_mode="update",
        would_create_tracks=4,
        would_update_tracks=5,
        identifier_totals={
            "catalog_number": {"internal": 2, "external": 1, "mismatch": 3},
            "contract_number": {"merged": 6, "skipped": 7, "conflicted": 8},
            "ignored_identifier": {"internal": 99},
        },
    )

    summary = exchange_controller._exchange_import_review_summary(report)

    assert "Planned mode: update" in summary
    assert "Rows ready: 2" in summary
    assert "Rows blocked: 1" in summary
    assert "Rows skipped: 3" in summary
    assert "Would create tracks: 4" in summary
    assert "Would update tracks: 5" in summary
    assert "Catalog Number: internal 2, external 1, mismatch 3" in summary
    assert "Contract Number: merged/skipped 6, skipped 7, conflicted 8" in summary
    assert "ignored_identifier" not in summary
    assert "Duplicate-safe skips: 1" in summary
    assert "Unknown fields: unexpected_column" in summary


def test_open_import_review_dialog_uses_resolved_dialog_and_returns_acceptance(monkeypatch):
    captured = {}

    class FakeDialog:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def exec(self):
            return QDialog.Accepted

    def fake_root_attr(name, fallback):
        assert name == "ImportReviewDialog"
        return FakeDialog

    monkeypatch.setattr(exchange_controller, "_root_attr", fake_root_attr)

    accepted = exchange_controller._open_import_review_dialog(
        SimpleNamespace(),
        title="Review exchange import",
        subtitle="Preview details",
        summary_lines=["Rows ready: 2"],
        warnings=["warning"],
        preview_rows=[{"ISRC": "AA6Q72000001"}],
        preview_headers=["ISRC"],
        preview_title="Rows",
        confirm_label="Apply import",
    )

    assert accepted is True
    assert captured["kwargs"]["title"] == "Review exchange import"
    assert captured["kwargs"]["subtitle"] == "Preview details"
    assert captured["kwargs"]["summary_lines"] == ["Rows ready: 2"]
    assert captured["kwargs"]["warnings"] == ["warning"]
    assert captured["kwargs"]["preview_rows"] == [{"ISRC": "AA6Q72000001"}]
    assert captured["kwargs"]["preview_headers"] == ["ISRC"]
    assert captured["kwargs"]["preview_title"] == "Rows"
    assert captured["kwargs"]["confirm_label"] == "Apply import"


def test_import_exchange_file_inspects_csv_and_runs_dry_run_then_preflight_apply(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "tracks.csv"
    source.write_text("ISRC,Title\nAA6Q72000001,Song\n")
    inspection = ExchangeInspection(
        file_path=str(source),
        format_name="csv",
        headers=["ISRC", "Title"],
        preview_rows=[{"ISRC": "AA6Q72000001", "Title": "Song"}],
        suggested_mapping={"ISRC": "isrc"},
    )
    dry_run_report = _report(mode="dry_run", passed=1, failed=0, skipped=0)
    apply_report = _report(mode="update", passed=1, failed=0, skipped=0, updated_tracks=[9])
    submitted: list[dict[str, object]] = []
    errors = []

    class _Dialog:
        next_options = ExchangeImportOptions(mode="dry_run")

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return QDialog.Accepted

        def mapping(self):
            return {"ISRC": "isrc"}

        def import_options(self):
            return self.next_options

        def resolved_csv_delimiter(self):
            return ";"

    def root_attr(name, fallback):
        if name == "ExchangeImportDialog":
            return _Dialog
        if name == "run_snapshot_history_action":
            return lambda **kwargs: kwargs["mutation"]()
        return fallback

    service = mock.Mock()
    service.supported_import_targets.return_value = ["isrc"]
    service.inspect_csv.return_value = inspection
    service.import_csv.side_effect = [dry_run_report, dry_run_report, apply_report]
    app = SimpleNamespace(
        exchange_service=service,
        settings=mock.Mock(),
        logger=mock.Mock(),
        conn=SimpleNamespace(commit=mock.Mock()),
        _scaled_progress_callback=lambda callback, **_kwargs: callback,
        _submit_background_bundle_task=lambda **kwargs: submitted.append(kwargs),
        _advance_task_ui_progress=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        populate_all_comboboxes=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_exchange_import_report=mock.Mock(),
        _show_background_task_error=lambda title, failure, **kwargs: errors.append(
            (title, failure, kwargs)
        ),
        _open_import_review_dialog=mock.Mock(return_value=True),
        _exchange_import_review_summary=exchange_controller._exchange_import_review_summary,
    )
    file_dialog = mock.Mock()
    file_dialog.getOpenFileName.return_value = (str(source), "")
    monkeypatch.setattr(exchange_controller, "_file_dialog", lambda: file_dialog)
    monkeypatch.setattr(exchange_controller, "_root_attr", root_attr)

    ctx = SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock())
    bundle = SimpleNamespace(exchange_service=service, history_manager=object())
    exchange_controller.import_exchange_file(app, "csv")
    assert submitted[-1]["title"] == "Inspect CSV"
    assert submitted[-1]["task_fn"](bundle, ctx) is inspection
    submitted[-1]["on_success_after_cleanup"](inspection)

    dry_task = submitted[-1]
    assert dry_task["title"] == "Import CSV"
    assert dry_task["task_fn"](bundle, ctx) is dry_run_report
    dry_task["on_success_before_cleanup"](dry_run_report, object())
    dry_task["on_success_after_cleanup"](dry_run_report)
    app._show_exchange_import_report.assert_called_once_with(str(source), dry_run_report)
    app.conn.commit.assert_not_called()

    _Dialog.next_options = ExchangeImportOptions(mode="update")
    exchange_controller.import_exchange_file(app, "csv")
    submitted[-1]["on_success_after_cleanup"](inspection)
    review_task = submitted[-1]
    assert review_task["title"] == "Review CSV"
    assert review_task["task_fn"](bundle, ctx) is dry_run_report
    review_task["on_success_after_cleanup"](dry_run_report)

    apply_task = submitted[-1]
    assert apply_task["title"] == "Import CSV"
    assert apply_task["task_fn"](bundle, ctx) is apply_report
    apply_task["on_success_before_cleanup"](apply_report, object())
    apply_task["on_success_after_cleanup"](apply_report)
    app.conn.commit.assert_called_once()
    app.refresh_table_preserve_view.assert_called_once_with(focus_id=9)
    assert errors == []


@pytest.mark.parametrize("answer, should_clear", [("no", False), ("yes", True)])
def test_reset_saved_exchange_import_choices_handles_confirmation(
    monkeypatch, answer, should_clear
):
    removed = []

    class FakeSettings:
        def remove(self, key):
            removed.append(key)

        def sync(self):
            removed.append("synced")

    class FakeMessageBox:
        Yes = 1
        No = 2

        @classmethod
        def question(cls, *args):
            return cls.Yes if answer == "yes" else cls.No

        @classmethod
        def information(cls, *args):
            removed.append("info")

    app = SimpleNamespace(settings=FakeSettings())
    monkeypatch.setattr(exchange_controller, "_message_box", lambda: FakeMessageBox)

    exchange_controller.reset_saved_exchange_import_choices(app)

    if should_clear:
        assert removed == ["exchange/import_preferences", "synced", "info"]
    else:
        assert removed == []


def test_show_exchange_import_report_opens_first_repair_queue_entry(monkeypatch, tmp_path):
    opened = []
    instances = []

    class FakeMessageBox:
        Information = 1
        ActionRole = 2
        Ok = 3

        def __init__(self, parent=None):
            self.parent = parent
            self.buttons = []
            self.details = ""
            instances.append(self)

        def setIcon(self, icon):
            self.icon = icon

        def setWindowTitle(self, title):
            self.title = title

        def setText(self, text):
            self.text = text

        def setInformativeText(self, text):
            self.informative_text = text

        def setDetailedText(self, text):
            self.details = text

        def setStandardButtons(self, buttons):
            self.standard_buttons = buttons

        def addButton(self, label, role=None):
            button = object()
            self.buttons.append((button, label, role))
            return button

        def exec(self):
            return None

        def clickedButton(self):
            return self.buttons[0][0]

    app = SimpleNamespace(
        open_track_import_repair_queue=lambda **kwargs: opened.append(kwargs),
    )
    monkeypatch.setattr(exchange_controller, "QMessageBox", FakeMessageBox)

    exchange_controller._show_exchange_import_report(
        app,
        tmp_path / "tracks.csv",
        _report(repair_queue_entry_ids=[42, 43], warnings=["warning one", "warning two"]),
    )

    assert opened == [{"focus_entry_id": 42}]
    assert instances[0].title == "Import CSV"
    assert "Warnings:" in instances[0].text
    assert "- warning one" in instances[0].text


def test_export_exchange_file_dispatches_selected_json_through_history(monkeypatch, tmp_path):
    submitted = {}
    messages = []
    service = mock.Mock()
    service.export_json.return_value = 7
    progress_callback = object()
    resolved_path = tmp_path / "catalog.json"

    class CatalogController:
        def selected_or_visible_track_ids(self):
            return [10, 11]

    def fake_root_attr(name, fallback):
        if name == "run_file_history_action":

            def run_file_history_action(**kwargs):
                return kwargs["mutation"]()

            return run_file_history_action
        return fallback

    app = SimpleNamespace(
        exchange_service=service,
        exports_dir=tmp_path,
        history_manager=object(),
        _catalog_table_controller=lambda: CatalogController(),
        _resolve_file_export_target=lambda path, **kwargs: Path(path),
        _scaled_progress_callback=lambda callback, **kwargs: progress_callback,
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        logger=mock.Mock(),
    )

    file_dialog = mock.Mock()
    file_dialog.getSaveFileName.return_value = (str(resolved_path), "")

    class FakeMessageBox:
        @classmethod
        def information(cls, *args):
            messages.append(args)

    monkeypatch.setattr(exchange_controller, "_root_attr", fake_root_attr)
    monkeypatch.setattr(exchange_controller, "_file_dialog", lambda: file_dialog)
    monkeypatch.setattr(exchange_controller, "_message_box", lambda: FakeMessageBox)

    def submit_background_task(**kwargs):
        submitted.update(kwargs)

    app._submit_background_bundle_task = submit_background_task

    exchange_controller.export_exchange_file(app, "json", selected_only=True)

    bundle = SimpleNamespace(exchange_service=service, history_manager=app.history_manager)
    ctx = SimpleNamespace(report_progress=mock.Mock())
    assert submitted["task_fn"](bundle, ctx) == 7
    service.export_json.assert_called_once_with(
        resolved_path,
        [10, 11],
        progress_callback=progress_callback,
    )

    submitted["on_success_after_cleanup"](7)

    app._refresh_history_actions.assert_called_once()
    app._log_event.assert_called_once()
    app._audit.assert_called_once()
    app._audit_commit.assert_called_once()
    assert messages


def test_export_exchange_file_handles_missing_service_and_empty_selected_export(
    monkeypatch, tmp_path
):
    messages = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            messages.append(("warning", args))

        @classmethod
        def information(cls, *args):
            messages.append(("information", args))

    monkeypatch.setattr(exchange_controller, "_message_box", lambda: FakeMessageBox)

    missing_service_app = SimpleNamespace(exchange_service=None)
    exchange_controller.export_exchange_file(missing_service_app, "csv", selected_only=False)
    assert messages[-1][0] == "warning"

    class EmptyCatalogController:
        def selected_or_visible_track_ids(self):
            return []

    empty_selection_app = SimpleNamespace(
        exchange_service=mock.Mock(),
        exports_dir=tmp_path,
        _catalog_table_controller=lambda: EmptyCatalogController(),
    )
    exchange_controller.export_exchange_file(empty_selection_app, "csv", selected_only=True)
    assert messages[-1][0] == "information"


def test_import_exchange_file_handles_missing_service_cancel_unsupported_and_xml_conflicts(
    monkeypatch,
    tmp_path,
):
    messages = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            messages.append(("warning", args))

        @classmethod
        def critical(cls, *args):
            messages.append(("critical", args))

    file_dialog = mock.Mock()
    monkeypatch.setattr(exchange_controller, "_message_box", lambda: FakeMessageBox)
    monkeypatch.setattr(exchange_controller, "_file_dialog", lambda: file_dialog)

    exchange_controller.import_exchange_file(SimpleNamespace(exchange_service=None), "csv")
    assert messages[-1][0] == "warning"

    app = SimpleNamespace(
        exchange_service=mock.Mock(),
        submitted=[],
        _submit_background_bundle_task=lambda **kwargs: app.submitted.append(kwargs),
        _scaled_progress_callback=lambda callback, **_kwargs: callback,
        _show_background_task_error=mock.Mock(),
    )
    file_dialog.getOpenFileName.return_value = ("", "")
    exchange_controller.import_exchange_file(app, "csv")
    assert app.submitted == []

    source = tmp_path / "unsupported.bin"
    source.write_text("bad", encoding="utf-8")
    file_dialog.getOpenFileName.return_value = (str(source), "")
    exchange_controller.import_exchange_file(app, "bogus")
    unsupported_task = app.submitted[-1]
    with pytest.raises(ValueError, match="Unsupported exchange format"):
        unsupported_task["task_fn"](
            SimpleNamespace(exchange_service=mock.Mock()),
            SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock()),
        )

    xml_path = tmp_path / "catalog.xml"
    xml_path.write_text("<catalog />", encoding="utf-8")
    file_dialog.getOpenFileName.return_value = (str(xml_path), "")
    xml_inspection = SimpleNamespace(
        conflicting_custom_fields=[("Mood", "dropdown", "text")],
        missing_custom_fields=[],
    )
    bundle = SimpleNamespace(
        exchange_service=mock.Mock(),
        xml_import_service=SimpleNamespace(
            build_exchange_inspection=mock.Mock(
                return_value=(
                    xml_inspection,
                    ExchangeInspection(
                        file_path=str(xml_path),
                        format_name="xml",
                        headers=["ISRC"],
                        preview_rows=[],
                        suggested_mapping={},
                    ),
                )
            )
        ),
    )
    app.exchange_service.supported_import_targets.return_value = []
    exchange_controller.import_exchange_file(app, "xml")
    xml_task = app.submitted[-1]
    inspection_payload = xml_task["task_fn"](
        bundle,
        SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock()),
    )
    xml_task["on_success_after_cleanup"](inspection_payload)
    assert messages[-1][0] == "critical"
    assert "Custom columns already exist" in messages[-1][1][2]

    with pytest.raises(ValueError, match="XML inspection"):
        xml_task["on_success_after_cleanup"]({})


def test_xml_import_adds_missing_custom_fields_and_honors_review_rejection(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "catalog.xml"
    source.write_text("<catalog />", encoding="utf-8")
    submitted = []
    captured_dialogs = []

    class FakeDialog:
        def __init__(self, **kwargs):
            captured_dialogs.append(kwargs)

        def exec(self):
            return QDialog.Accepted

        def mapping(self):
            return {"ISRC": "isrc"}

        def import_options(self):
            return ExchangeImportOptions(mode="update", skip_targets=["lyrics"])

        def resolved_csv_delimiter(self):
            return None

    app = SimpleNamespace(
        exchange_service=mock.Mock(),
        settings=mock.Mock(),
        logger=mock.Mock(),
        conn=SimpleNamespace(commit=mock.Mock()),
        _scaled_progress_callback=lambda callback, **_kwargs: callback,
        _submit_background_bundle_task=lambda **kwargs: submitted.append(kwargs),
        _advance_task_ui_progress=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        populate_all_comboboxes=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_exchange_import_report=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        _open_import_review_dialog=mock.Mock(return_value=False),
        _exchange_import_review_summary=exchange_controller._exchange_import_review_summary,
    )
    app.exchange_service.supported_import_targets.return_value = ["isrc"]
    file_dialog = mock.Mock()
    file_dialog.getOpenFileName.return_value = (str(source), "")
    monkeypatch.setattr(exchange_controller, "_file_dialog", lambda: file_dialog)
    monkeypatch.setattr(
        exchange_controller,
        "_root_attr",
        lambda name, fallback: FakeDialog if name == "ExchangeImportDialog" else fallback,
    )

    xml_inspection = SimpleNamespace(
        conflicting_custom_fields=[],
        missing_custom_fields=[("Mood", "dropdown"), ("Known", "text")],
    )
    exchange_inspection = ExchangeInspection(
        file_path=str(source),
        format_name="xml",
        headers=["ISRC"],
        preview_rows=[{"ISRC": "AA6Q72000001"}],
        suggested_mapping={},
    )
    bundle = SimpleNamespace(
        exchange_service=app.exchange_service,
        xml_import_service=SimpleNamespace(
            build_exchange_inspection=mock.Mock(return_value=(xml_inspection, exchange_inspection))
        ),
        history_manager=object(),
    )
    app.exchange_service.import_xml.return_value = _report(
        format_name="xml",
        mode="dry_run",
        passed=1,
        failed=0,
        skipped=0,
    )

    exchange_controller.import_exchange_file(app, "xml")
    inspect_task = submitted[-1]
    inspection_payload = inspect_task["task_fn"](
        bundle,
        SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock()),
    )
    inspect_task["on_success_after_cleanup"](inspection_payload)

    assert "custom::Mood" in captured_dialogs[-1]["supported_headers"]
    review_task = submitted[-1]
    assert review_task["title"] == "Review XML"
    report = review_task["task_fn"](
        bundle,
        SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock()),
    )
    review_task["on_success_after_cleanup"](report)

    assert app._open_import_review_dialog.called
    assert submitted[-1] is review_task


@pytest.mark.parametrize(
    ("format_name", "inspect_method", "import_method"),
    [
        ("xlsx", "inspect_xlsx", "import_xlsx"),
        ("json", "inspect_json", "import_json"),
        ("package", "inspect_package", "import_package"),
    ],
)
def test_import_exchange_file_dispatches_non_csv_formats(
    monkeypatch,
    tmp_path,
    format_name,
    inspect_method,
    import_method,
):
    source = tmp_path / f"catalog.{format_name}"
    source.write_text("payload", encoding="utf-8")
    inspection = ExchangeInspection(
        file_path=str(source),
        format_name=format_name,
        headers=["ISRC"],
        preview_rows=[],
        suggested_mapping={},
    )
    report = _report(format_name=format_name, mode="dry_run", passed=1, failed=0, skipped=0)
    submitted = []

    class FakeDialog:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return QDialog.Accepted

        def mapping(self):
            return {"ISRC": "isrc"}

        def import_options(self):
            return ExchangeImportOptions(mode="dry_run")

        def resolved_csv_delimiter(self):
            return None

    service = mock.Mock()
    service.supported_import_targets.return_value = ["isrc"]
    getattr(service, inspect_method).return_value = inspection
    getattr(service, import_method).return_value = report
    app = SimpleNamespace(
        exchange_service=service,
        settings=mock.Mock(),
        logger=mock.Mock(),
        _scaled_progress_callback=lambda callback, **_kwargs: callback,
        _submit_background_bundle_task=lambda **kwargs: submitted.append(kwargs),
        _advance_task_ui_progress=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_exchange_import_report=mock.Mock(),
        _show_background_task_error=mock.Mock(),
    )
    file_dialog = mock.Mock()
    file_dialog.getOpenFileName.return_value = (str(source), "")
    monkeypatch.setattr(exchange_controller, "_file_dialog", lambda: file_dialog)
    monkeypatch.setattr(
        exchange_controller,
        "_root_attr",
        lambda name, fallback: FakeDialog if name == "ExchangeImportDialog" else fallback,
    )

    bundle = SimpleNamespace(exchange_service=service, history_manager=object())
    ctx = SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock())
    exchange_controller.import_exchange_file(app, format_name)
    inspect_task = submitted[-1]
    assert inspect_task["task_fn"](bundle, ctx) is inspection
    inspect_task["on_success_after_cleanup"](inspection)
    import_task = submitted[-1]
    assert import_task["task_fn"](bundle, ctx) is report
    import_task["on_success_before_cleanup"](report, object())
    import_task["on_success_after_cleanup"](report)

    getattr(service, inspect_method).assert_called_once()
    getattr(service, import_method).assert_called_once()
    app._show_exchange_import_report.assert_called_once_with(str(source), report)


@pytest.mark.parametrize(
    ("format_name", "method_name", "exported"),
    [
        ("csv", "export_csv", 2),
        ("xlsx", "export_xlsx", 3),
        ("package", "export_package", 1),
    ],
)
def test_export_exchange_file_dispatches_remaining_formats_and_messages(
    monkeypatch,
    tmp_path,
    format_name,
    method_name,
    exported,
):
    messages = []
    submitted = []
    output = tmp_path / f"catalog.{format_name}"
    service = mock.Mock()
    getattr(service, method_name).return_value = exported

    class FakeMessageBox:
        @classmethod
        def information(cls, *args):
            messages.append(args)

    def fake_root_attr(name, fallback):
        if name == "run_file_history_action":
            return lambda **kwargs: kwargs["mutation"]()
        return fallback

    app = SimpleNamespace(
        exchange_service=service,
        exports_dir=tmp_path,
        history_manager=object(),
        _resolve_file_export_target=lambda path, **_kwargs: Path(path),
        _scaled_progress_callback=lambda callback, **_kwargs: callback,
        _submit_background_bundle_task=lambda **kwargs: submitted.append(kwargs),
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        logger=mock.Mock(),
    )
    file_dialog = mock.Mock()
    file_dialog.getSaveFileName.return_value = (str(output), "")
    monkeypatch.setattr(exchange_controller, "_root_attr", fake_root_attr)
    monkeypatch.setattr(exchange_controller, "_file_dialog", lambda: file_dialog)
    monkeypatch.setattr(exchange_controller, "_message_box", lambda: FakeMessageBox)

    exchange_controller.export_exchange_file(app, format_name, selected_only=False)
    task = submitted[-1]
    bundle = SimpleNamespace(exchange_service=service, history_manager=object())
    result = task["task_fn"](bundle, SimpleNamespace(report_progress=mock.Mock()))
    task["on_success_after_cleanup"](result)

    assert result == exported
    getattr(service, method_name).assert_called_once_with(
        output,
        None,
        progress_callback=mock.ANY,
    )
    assert f"Exported {exported} row" in messages[-1][2]


def test_export_exchange_file_handles_cancel_bad_target_and_unsupported_worker(
    monkeypatch,
    tmp_path,
):
    messages = []
    submitted = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            messages.append(args)

    def fake_root_attr(name, fallback):
        if name == "run_file_history_action":
            return lambda **kwargs: kwargs["mutation"]()
        return fallback

    service = mock.Mock()
    app = SimpleNamespace(
        exchange_service=service,
        exports_dir=tmp_path,
        history_manager=object(),
        _resolve_file_export_target=mock.Mock(side_effect=ValueError("bad target")),
        _scaled_progress_callback=lambda callback, **_kwargs: callback,
        _submit_background_bundle_task=lambda **kwargs: submitted.append(kwargs),
        _show_background_task_error=mock.Mock(),
        logger=mock.Mock(),
    )
    file_dialog = mock.Mock()
    monkeypatch.setattr(exchange_controller, "_root_attr", fake_root_attr)
    monkeypatch.setattr(exchange_controller, "_file_dialog", lambda: file_dialog)
    monkeypatch.setattr(exchange_controller, "_message_box", lambda: FakeMessageBox)

    file_dialog.getSaveFileName.return_value = ("", "")
    exchange_controller.export_exchange_file(app, "csv", selected_only=False)
    assert submitted == []

    file_dialog.getSaveFileName.return_value = (str(tmp_path / "bad.csv"), "")
    exchange_controller.export_exchange_file(app, "csv", selected_only=False)
    assert messages[-1][2] == "bad target"

    app._resolve_file_export_target = lambda path, **_kwargs: Path(path)
    exchange_controller.export_exchange_file(app, "unknown", selected_only=False)
    task = submitted[-1]
    with pytest.raises(ValueError, match="Unsupported exchange format"):
        task["task_fn"](
            SimpleNamespace(exchange_service=service, history_manager=object()),
            SimpleNamespace(report_progress=mock.Mock()),
        )
