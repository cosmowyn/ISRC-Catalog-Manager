from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import isrc_manager.exchange.master_transfer_controller as controller


class _MessageBox:
    Yes = 1
    No = 2

    def __init__(self, question_answer=Yes):
        self.question_answer = question_answer
        self.warning = mock.Mock()
        self.information = mock.Mock()
        self.question = mock.Mock(return_value=question_answer)


class _FileDialog:
    def __init__(self, *, save_path: str = "", open_path: str = ""):
        self.getSaveFileName = mock.Mock(return_value=(save_path, "ZIP"))
        self.getOpenFileName = mock.Mock(return_value=(open_path, "ZIP"))


def _app(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        exchange_service=mock.Mock(),
        repertoire_exchange_service=mock.Mock(),
        license_service=mock.Mock(),
        contract_template_service=mock.Mock(),
        exports_dir=tmp_path,
        logger=mock.Mock(),
        conn=mock.Mock(),
        _resolve_file_export_target=mock.Mock(side_effect=lambda path, **_kwargs: Path(path)),
        _create_master_transfer_service_for_ui=mock.Mock(),
        _open_master_transfer_export_preview_dialog=mock.Mock(),
        _master_transfer_export_issue_prompt_lines=controller._master_transfer_export_issue_prompt_lines,
        _scaled_progress_callback=mock.Mock(side_effect=lambda callback, **_kwargs: callback),
        _submit_background_bundle_task=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _master_transfer_manifest_included_section_ids=(
            controller._master_transfer_manifest_included_section_ids
        ),
        _master_transfer_manifest_omitted_section_labels=(
            controller._master_transfer_manifest_omitted_section_labels
        ),
        _master_transfer_review_summary=controller._master_transfer_review_summary,
        _show_master_transfer_import_report=mock.Mock(),
        _open_import_review_dialog=mock.Mock(return_value=True),
        _advance_task_ui_progress=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        populate_all_comboboxes=mock.Mock(),
        _refresh_catalog_workspace_docks=mock.Mock(),
    )


def test_root_attr_uses_main_window_override_and_fallback(monkeypatch) -> None:
    fallback = object()
    monkeypatch.setitem(
        sys.modules,
        "isrc_manager.main_window",
        SimpleNamespace(QMessageBox="override"),
    )

    assert controller._root_attr("QMessageBox", fallback) == "override"
    assert controller._root_attr("Missing", fallback) is fallback

    monkeypatch.delitem(sys.modules, "isrc_manager.main_window")
    assert controller._root_attr("QMessageBox", fallback) is fallback


def test_create_master_transfer_service_requires_exchange_services(monkeypatch, tmp_path: Path):
    app = _app(tmp_path)
    app.exchange_service = None
    assert controller._create_master_transfer_service_for_ui(app) is None

    app.exchange_service = "exchange"
    created = object()
    service_factory = mock.Mock(return_value=created)
    monkeypatch.setattr(controller, "MasterTransferService", service_factory)

    assert controller._create_master_transfer_service_for_ui(app) is created
    service_factory.assert_called_once_with(
        exchange_service="exchange",
        repertoire_exchange_service=app.repertoire_exchange_service,
        license_service=app.license_service,
        contract_template_service=app.contract_template_service,
    )


def test_preview_dialog_returns_selected_sections_or_none(monkeypatch, tmp_path: Path) -> None:
    app = _app(tmp_path)

    class _AcceptedDialog:
        def __init__(self, sections, parent):
            self.sections = sections
            self.parent = parent

        def exec(self):
            return controller.QDialog.Accepted

        def selected_section_ids(self):
            return ["catalog", "licenses"]

    monkeypatch.setattr(
        controller,
        "_root_attr",
        lambda name, fallback: (
            _AcceptedDialog if name == "MasterTransferExportDialog" else fallback
        ),
    )
    preview = SimpleNamespace(sections=("section",))
    assert controller._open_master_transfer_export_preview_dialog(app, preview) == [
        "catalog",
        "licenses",
    ]

    class _EmptyDialog(_AcceptedDialog):
        def selected_section_ids(self):
            return []

    monkeypatch.setattr(
        controller,
        "_root_attr",
        lambda name, fallback: _EmptyDialog if name == "MasterTransferExportDialog" else fallback,
    )
    assert controller._open_master_transfer_export_preview_dialog(app, preview) is None


def test_master_transfer_prompt_and_manifest_helpers() -> None:
    issues = [
        SimpleNamespace(section_label=f"Section {index}", label=f"Item {index}", reason="missing")
        for index in range(12)
    ]
    lines = controller._master_transfer_export_issue_prompt_lines(issues)
    manifest = {
        "export_selection": {
            "included_section_ids": [" catalog ", "catalog", "", "licenses"],
            "omitted_sections": [{"label": "Repertoire"}, {"section_id": "Templates"}, {}],
        },
        "sections": [{"section_id": "fallback"}],
    }
    inspection = SimpleNamespace(
        summary_lines=["Base summary"],
        catalog_dry_run=SimpleNamespace(would_create_tracks=2, would_update_tracks=3, failed=1),
        repertoire_inspection=SimpleNamespace(existing_parties=4, new_parties=5),
    )

    assert "- ...and 2 more" in lines
    assert "export_omissions.log" in lines[-1]
    assert controller._master_transfer_manifest_included_section_ids(manifest) == [
        "catalog",
        "licenses",
    ]
    assert controller._master_transfer_manifest_included_section_ids(
        {"sections": manifest["sections"]}
    ) == ["fallback"]
    assert controller._master_transfer_manifest_included_section_ids("bad") == []
    assert controller._master_transfer_manifest_omitted_section_labels(manifest) == [
        "Repertoire",
        "Templates",
    ]
    assert controller._master_transfer_manifest_omitted_section_labels("bad") == []
    summary = controller._master_transfer_review_summary(inspection)
    assert summary[0] == "Base summary"
    assert any("would create 2" in line for line in summary)
    assert any("would reuse 4" in line for line in summary)


def test_show_master_transfer_import_report_lists_sections_warnings_and_omissions(
    monkeypatch, tmp_path: Path
) -> None:
    app = _app(tmp_path)
    message_box = _MessageBox()
    monkeypatch.setattr(controller, "_message_box", lambda: message_box)
    result = SimpleNamespace(
        app_version="3.14.5",
        exported_at="2026-05-25",
        manifest={
            "export_selection": {
                "included_section_ids": [
                    "catalog",
                    "repertoire",
                    "licenses",
                    "contract_templates",
                ],
                "omitted_sections": [{"label": "Excluded"}],
            }
        },
        catalog_report=SimpleNamespace(created_tracks=[1], updated_tracks=[2, 3]),
        repertoire_party_phase=SimpleNamespace(imported_parties=2, reused_existing_parties=1),
        repertoire_report=SimpleNamespace(
            imported_works=4,
            imported_contracts=5,
            imported_rights=6,
            imported_assets=7,
        ),
        imported_licenses=8,
        imported_contract_templates=9,
        imported_template_revisions=10,
        warnings=["warning"],
    )

    controller._show_master_transfer_import_report(app, str(tmp_path / "transfer.zip"), result)

    message = message_box.information.call_args.args[2]
    assert "Catalog: created 1, updated 2" in message
    assert "Intentionally omitted sections" in message
    assert "- warning" in message


def test_export_master_transfer_package_handles_early_exit_paths(
    monkeypatch, tmp_path: Path
) -> None:
    app = _app(tmp_path)
    message_box = _MessageBox()
    file_dialog = _FileDialog(save_path=str(tmp_path / "transfer.zip"))
    monkeypatch.setattr(controller, "_message_box", lambda: message_box)
    monkeypatch.setattr(controller, "_file_dialog", lambda: file_dialog)

    app.exchange_service = None
    controller.export_master_transfer_package(app)
    message_box.warning.assert_called_once()

    app = _app(tmp_path)
    file_dialog = _FileDialog(save_path="")
    monkeypatch.setattr(controller, "_file_dialog", lambda: file_dialog)
    controller.export_master_transfer_package(app)
    app._resolve_file_export_target.assert_not_called()

    app = _app(tmp_path)
    file_dialog = _FileDialog(save_path=str(tmp_path / "transfer.zip"))
    monkeypatch.setattr(controller, "_file_dialog", lambda: file_dialog)
    app._resolve_file_export_target.side_effect = ValueError("bad target")
    controller.export_master_transfer_package(app)
    app._create_master_transfer_service_for_ui.assert_not_called()

    app = _app(tmp_path)
    app._create_master_transfer_service_for_ui.return_value = SimpleNamespace(
        preview_export=mock.Mock(return_value=SimpleNamespace(sections=[]))
    )
    app._open_master_transfer_export_preview_dialog.return_value = None
    controller.export_master_transfer_package(app)
    app._submit_background_bundle_task.assert_not_called()


def test_import_master_transfer_package_submits_inspection_and_apply_task(
    monkeypatch, tmp_path: Path
):
    app = _app(tmp_path)
    file_dialog = _FileDialog(open_path=str(tmp_path / "transfer.zip"))
    monkeypatch.setattr(controller, "_file_dialog", lambda: file_dialog)
    submitted: list[dict[str, object]] = []

    def submit_task(**kwargs):
        submitted.append(kwargs)
        if kwargs["unique_key"] == "master_transfer.inspect":
            kwargs["on_success_after_cleanup"](
                SimpleNamespace(
                    warnings=[],
                    preview_rows=[],
                    summary_lines=[],
                    catalog_dry_run=None,
                    repertoire_inspection=None,
                )
            )

    app._submit_background_bundle_task.side_effect = submit_task

    controller.import_master_transfer_package(app)

    assert [task["unique_key"] for task in submitted] == [
        "master_transfer.inspect",
        "master_transfer.import",
    ]


def test_import_master_transfer_package_handles_no_profile_and_cancel(monkeypatch, tmp_path: Path):
    app = _app(tmp_path)
    message_box = _MessageBox()
    monkeypatch.setattr(controller, "_message_box", lambda: message_box)
    app.exchange_service = None
    controller.import_master_transfer_package(app)
    message_box.warning.assert_called_once()

    app = _app(tmp_path)
    monkeypatch.setattr(controller, "_file_dialog", lambda: _FileDialog(open_path=""))
    controller.import_master_transfer_package(app)
    app._submit_background_bundle_task.assert_not_called()
