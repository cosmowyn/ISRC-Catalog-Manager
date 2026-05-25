from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from PySide6.QtWidgets import QDialog

from isrc_manager.exchange import ExchangeImportReport
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
