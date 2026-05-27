from types import SimpleNamespace
from unittest import mock

from isrc_manager.exchange import master_transfer_controller as controller


class _Box:
    Yes = 1
    No = 2

    def __init__(self):
        self.warning = mock.Mock()
        self.information = mock.Mock()
        self.question = mock.Mock(return_value=self.Yes)


def test_master_transfer_service_and_preview_dialog_helpers(monkeypatch):
    created = []

    class FakeService:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(controller, "MasterTransferService", FakeService)
    missing_app = SimpleNamespace(exchange_service=None, repertoire_exchange_service=object())
    assert controller._create_master_transfer_service_for_ui(missing_app) is None

    app = SimpleNamespace(
        exchange_service=object(),
        repertoire_exchange_service=object(),
        license_service=object(),
        contract_template_service=object(),
    )
    assert isinstance(controller._create_master_transfer_service_for_ui(app), FakeService)
    assert created[-1]["exchange_service"] is app.exchange_service

    selected_dialog = mock.Mock(
        exec=mock.Mock(return_value=controller.QDialog.Accepted),
        selected_section_ids=mock.Mock(return_value=["catalog"]),
    )
    empty_dialog = mock.Mock(
        exec=mock.Mock(return_value=controller.QDialog.Accepted),
        selected_section_ids=mock.Mock(return_value=[]),
    )
    rejected_dialog = mock.Mock(exec=mock.Mock(return_value=controller.QDialog.Rejected))
    dialogs = iter((selected_dialog, empty_dialog, rejected_dialog))
    monkeypatch.setattr(
        controller,
        "_root_attr",
        lambda _name, _fallback: mock.Mock(side_effect=lambda *_args, **_kwargs: next(dialogs)),
    )
    preview = SimpleNamespace(sections=[SimpleNamespace(section_id="catalog")])

    assert controller._open_master_transfer_export_preview_dialog(app, preview) == ["catalog"]
    assert controller._open_master_transfer_export_preview_dialog(app, preview) is None
    assert controller._open_master_transfer_export_preview_dialog(app, preview) is None


def test_master_transfer_prompt_manifest_summary_and_report_helpers(monkeypatch, tmp_path):
    issues = [
        SimpleNamespace(section_label="Section", label=f"Item {idx}", reason="missing")
        for idx in range(12)
    ]
    lines = controller._master_transfer_export_issue_prompt_lines(issues)
    assert "- ...and 2 more" in lines
    assert "export_omissions.log" in lines[-1]

    manifest = {
        "export_selection": {
            "included_section_ids": ["catalog", "", "catalog", "licenses", "contract_templates"],
            "omitted_sections": [{"label": "Templates"}, {"section_id": "Assets"}, {}],
        },
        "sections": [{"section_id": "fallback"}],
    }
    assert controller._master_transfer_manifest_included_section_ids(manifest) == [
        "catalog",
        "licenses",
        "contract_templates",
    ]
    assert controller._master_transfer_manifest_included_section_ids(
        {"sections": [{"section_id": "catalog"}, {"section_id": ""}]}
    ) == ["catalog"]
    assert controller._master_transfer_manifest_included_section_ids("bad") == []
    assert controller._master_transfer_manifest_omitted_section_labels(manifest) == [
        "Templates",
        "Assets",
    ]
    assert controller._master_transfer_manifest_omitted_section_labels({}) == []

    summary = controller._master_transfer_review_summary(
        SimpleNamespace(
            summary_lines=["Package ready"],
            catalog_dry_run=SimpleNamespace(would_create_tracks=2, would_update_tracks=1, failed=0),
            repertoire_inspection=SimpleNamespace(existing_parties=3, new_parties=4),
        )
    )
    assert summary == [
        "Package ready",
        "Catalog dry run: would create 2, would update 1, blocked 0",
        "Repertoire preview: would reuse 3 existing Parties and would create 4.",
    ]

    box = _Box()
    monkeypatch.setattr(controller, "_message_box", lambda: box)
    app = SimpleNamespace(
        _master_transfer_manifest_included_section_ids=controller._master_transfer_manifest_included_section_ids,
        _master_transfer_manifest_omitted_section_labels=controller._master_transfer_manifest_omitted_section_labels,
    )
    result = SimpleNamespace(
        manifest=manifest,
        app_version="1.2.3",
        exported_at="2026-05-27T12:00:00",
        catalog_report=SimpleNamespace(created_tracks=[1], updated_tracks=[2, 3]),
        repertoire_party_phase=SimpleNamespace(imported_parties=4, reused_existing_parties=5),
        repertoire_report=SimpleNamespace(
            imported_works=6,
            imported_contracts=7,
            imported_rights=8,
            imported_assets=9,
        ),
        imported_licenses=10,
        imported_contract_templates=11,
        imported_template_revisions=12,
        warnings=[f"warning {idx}" for idx in range(14)],
    )

    controller._show_master_transfer_import_report(app, str(tmp_path / "package.zip"), result)

    message = box.information.call_args.args[2]
    assert "Catalog: created 1, updated 2" in message
    assert "License Archive: imported 10" in message
    assert "Contract Templates: templates 11, revisions 12" in message
    assert "- Templates" in message
    assert "warning 11" in message
    assert "warning 12" not in message


def test_import_master_transfer_package_inspects_then_submits_import(monkeypatch, tmp_path):
    package_path = tmp_path / "transfer.zip"
    app = SimpleNamespace(
        exchange_service=object(),
        repertoire_exchange_service=object(),
        logger=mock.Mock(),
        conn=mock.Mock(commit=mock.Mock()),
        _scaled_progress_callback=mock.Mock(side_effect=lambda callback, **_kwargs: callback),
        _submit_background_bundle_task=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        _open_import_review_dialog=mock.Mock(return_value=True),
        _master_transfer_review_summary=mock.Mock(return_value=["ready"]),
        _advance_task_ui_progress=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        populate_all_comboboxes=mock.Mock(),
        _refresh_catalog_workspace_docks=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        _master_transfer_manifest_included_section_ids=controller._master_transfer_manifest_included_section_ids,
        _show_master_transfer_import_report=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
    )
    dialog = SimpleNamespace(getOpenFileName=mock.Mock(return_value=(str(package_path), "")))
    snapshot_calls = []

    def fake_snapshot_action(**kwargs):
        result = kwargs["mutation"]()
        snapshot_calls.append(kwargs)
        return result

    monkeypatch.setattr(controller, "_file_dialog", lambda: dialog)
    monkeypatch.setattr(
        controller,
        "_root_attr",
        lambda name, fallback: (
            fake_snapshot_action if name == "run_snapshot_history_action" else fallback
        ),
    )

    controller.import_master_transfer_package(app)

    inspect_kwargs = app._submit_background_bundle_task.call_args.kwargs
    inspection = SimpleNamespace(
        warnings=["note"],
        preview_rows=[("catalog", "track", "create", "Song", "")],
        summary_lines=["Package summary"],
        catalog_dry_run=None,
        repertoire_inspection=None,
    )
    bundle = SimpleNamespace(
        history_manager=mock.Mock(),
        master_transfer_service=mock.Mock(
            inspect_package=mock.Mock(return_value=inspection),
            import_package=mock.Mock(),
        ),
    )
    ctx = SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock())

    assert inspect_kwargs["task_fn"](bundle, ctx) is inspection
    bundle.master_transfer_service.inspect_package.assert_called_once()
    inspect_kwargs["on_success_after_cleanup"](inspection)
    assert app._submit_background_bundle_task.call_count == 2
    app._open_import_review_dialog.assert_called_once()

    import_kwargs = app._submit_background_bundle_task.call_args.kwargs
    import_result = SimpleNamespace(
        manifest={"export_selection": {"included_section_ids": ["catalog"]}},
        exported_at="2026-05-27",
        app_version="9.9.9",
        catalog_report=SimpleNamespace(created_tracks=[44], updated_tracks=[]),
        repertoire_party_phase=None,
        repertoire_report=None,
        imported_licenses=0,
        imported_contract_templates=0,
        imported_template_revisions=0,
        warnings=[],
    )
    bundle.master_transfer_service.import_package.return_value = import_result

    assert import_kwargs["task_fn"](bundle, ctx) is import_result
    assert snapshot_calls[-1]["action_type"] == "master_transfer.import"
    progress = object()
    import_kwargs["on_success_before_cleanup"](import_result, progress)
    app.conn.commit.assert_called_once()
    app.refresh_table_preserve_view.assert_called_once_with(focus_id=44)
    app._advance_task_ui_progress.assert_any_call(
        progress,
        value=100,
        message="Master transfer import complete.",
    )

    import_kwargs["on_success_after_cleanup"](import_result)
    app._audit.assert_called_once()
    app._audit_commit.assert_called_once()
    app._show_master_transfer_import_report.assert_called_once_with(
        str(package_path),
        import_result,
    )


def test_import_master_transfer_package_warns_or_returns_without_profile_or_file(
    monkeypatch, tmp_path
):
    box = _Box()
    monkeypatch.setattr(controller, "_message_box", lambda: box)
    missing_profile = SimpleNamespace(exchange_service=None, repertoire_exchange_service=object())

    controller.import_master_transfer_package(missing_profile)
    box.warning.assert_called_once()

    app = SimpleNamespace(
        exchange_service=object(),
        repertoire_exchange_service=object(),
        _submit_background_bundle_task=mock.Mock(),
        _master_transfer_export_issue_prompt_lines=controller._master_transfer_export_issue_prompt_lines,
    )
    monkeypatch.setattr(
        controller,
        "_file_dialog",
        lambda: SimpleNamespace(getOpenFileName=mock.Mock(return_value=("", ""))),
    )

    controller.import_master_transfer_package(app)
    app._submit_background_bundle_task.assert_not_called()


def test_export_master_transfer_package_submits_history_worker_and_reports_success(
    monkeypatch,
    tmp_path,
):
    target = tmp_path / "transfer.zip"
    box = _Box()
    dialog = SimpleNamespace(getSaveFileName=mock.Mock(return_value=(str(target), "")))
    issue = SimpleNamespace(
        section_label="Contracts",
        label="missing.pdf",
        reason="not readable",
        to_dict=lambda: {"label": "missing.pdf"},
    )
    preview_service = mock.Mock(
        preview_export=mock.Mock(return_value=SimpleNamespace(sections=[])),
        validate_export_section_selection=mock.Mock(return_value=["catalog", "licenses"]),
        preflight_export=mock.Mock(return_value=[issue]),
    )
    app = SimpleNamespace(
        exchange_service=object(),
        repertoire_exchange_service=object(),
        exports_dir=tmp_path,
        logger=mock.Mock(),
        _resolve_file_export_target=mock.Mock(return_value=target),
        _create_master_transfer_service_for_ui=mock.Mock(return_value=preview_service),
        _open_master_transfer_export_preview_dialog=mock.Mock(return_value=["catalog"]),
        _master_transfer_export_issue_prompt_lines=controller._master_transfer_export_issue_prompt_lines,
        _scaled_progress_callback=mock.Mock(side_effect=lambda callback, **_kwargs: callback),
        _submit_background_bundle_task=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_background_task_error=mock.Mock(),
    )
    history_calls = []

    def fake_history_action(**kwargs):
        result = kwargs["mutation"]()
        history_calls.append((kwargs, kwargs["payload"](result)))
        return result

    monkeypatch.setattr(controller, "_file_dialog", lambda: dialog)
    monkeypatch.setattr(controller, "_message_box", lambda: box)
    monkeypatch.setattr(
        controller,
        "_root_attr",
        lambda name, fallback: (
            fake_history_action if name == "run_file_history_action" else fallback
        ),
    )

    controller.export_master_transfer_package(app)

    box.question.assert_called_once()
    preview_service.preflight_export.assert_called_once_with(
        include_sections=["catalog", "licenses"]
    )
    app._submit_background_bundle_task.assert_called_once()
    kwargs = app._submit_background_bundle_task.call_args.kwargs
    result = SimpleNamespace(
        app_version="1.2.3",
        exported_at="2026-05-27",
        warnings=["minor warning"],
        omitted_items=[issue],
        manifest={
            "export_selection": {
                "omitted_sections": [{"label": "Templates"}],
            }
        },
        sections=[
            SimpleNamespace(
                section_id="catalog",
                label="Catalog",
                entity_counts={"tracks": 2},
            )
        ],
    )
    bundle = SimpleNamespace(
        history_manager=mock.Mock(),
        master_transfer_service=mock.Mock(export_package=mock.Mock(return_value=result)),
    )
    ctx = SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock())

    assert kwargs["task_fn"](bundle, ctx) is result
    bundle.master_transfer_service.export_package.assert_called_once()
    export_kwargs = bundle.master_transfer_service.export_package.call_args.kwargs
    assert export_kwargs["include_sections"] == ["catalog", "licenses"]
    assert export_kwargs["continue_on_item_errors"] is True
    assert history_calls[0][0]["action_type"] == "file.master_transfer_export"
    assert history_calls[0][1]["omitted_items"] == [{"label": "missing.pdf"}]

    kwargs["on_success_after_cleanup"](result)
    app._refresh_history_actions.assert_called_once()
    app._audit.assert_called_once()
    app._audit_commit.assert_called_once()
    message = box.information.call_args.args[2]
    assert "Included sections:" in message
    assert "- Catalog: tracks=2" in message
    assert "Omitted sections:" in message
    assert "minor warning" in message


def test_export_master_transfer_package_handles_preflight_cancel_and_error_edges(
    monkeypatch,
    tmp_path,
):
    box = _Box()
    monkeypatch.setattr(controller, "_message_box", lambda: box)
    controller.export_master_transfer_package(
        SimpleNamespace(exchange_service=None, repertoire_exchange_service=object())
    )
    box.warning.assert_called_once()

    dialog = SimpleNamespace(getSaveFileName=mock.Mock(return_value=("", "")))
    monkeypatch.setattr(controller, "_file_dialog", lambda: dialog)
    app = SimpleNamespace(
        exchange_service=object(),
        repertoire_exchange_service=object(),
        exports_dir=tmp_path,
        _submit_background_bundle_task=mock.Mock(),
        _master_transfer_export_issue_prompt_lines=controller._master_transfer_export_issue_prompt_lines,
    )
    controller.export_master_transfer_package(app)
    app._submit_background_bundle_task.assert_not_called()

    dialog.getSaveFileName.return_value = (str(tmp_path / "bad.zip"), "")
    app._resolve_file_export_target = mock.Mock(side_effect=ValueError("outside exports"))
    controller.export_master_transfer_package(app)
    assert box.warning.call_args.args == (app, "Master Catalog Transfer", "outside exports")

    preview_service = mock.Mock(preview_export=mock.Mock(side_effect=RuntimeError("boom")))
    app._resolve_file_export_target = mock.Mock(return_value=tmp_path / "ok.zip")
    app._create_master_transfer_service_for_ui = mock.Mock(return_value=preview_service)
    controller.export_master_transfer_package(app)
    assert "Could not prepare the export preflight" in box.warning.call_args.args[2]

    preview_service.preview_export.side_effect = None
    preview_service.preview_export.return_value = SimpleNamespace(sections=[])
    app._open_master_transfer_export_preview_dialog = mock.Mock(return_value=[])
    controller.export_master_transfer_package(app)
    app._submit_background_bundle_task.assert_not_called()

    app._open_master_transfer_export_preview_dialog = mock.Mock(return_value=["catalog"])
    preview_service.validate_export_section_selection.side_effect = ValueError("bad section")
    controller.export_master_transfer_package(app)
    assert box.warning.call_args.args == (app, "Master Catalog Transfer", "bad section")

    preview_service.validate_export_section_selection.side_effect = None
    preview_service.validate_export_section_selection.return_value = ["catalog"]
    preview_service.preflight_export.return_value = [SimpleNamespace(section_id="catalog")]
    box.question.return_value = box.No
    controller.export_master_transfer_package(app)
    app._submit_background_bundle_task.assert_not_called()


def test_master_transfer_helpers_cover_empty_review_and_repertoire_report(monkeypatch, tmp_path):
    box = _Box()
    monkeypatch.setattr(controller, "_message_box", lambda: box)

    assert controller._message_box() is box
    assert controller._master_transfer_manifest_omitted_section_labels("bad") == []
    assert controller._master_transfer_review_summary(SimpleNamespace()) == []

    app = SimpleNamespace(
        _master_transfer_manifest_included_section_ids=controller._master_transfer_manifest_included_section_ids,
        _master_transfer_manifest_omitted_section_labels=controller._master_transfer_manifest_omitted_section_labels,
    )
    result = SimpleNamespace(
        manifest={"export_selection": {"included_section_ids": ["repertoire"]}},
        app_version="",
        exported_at="",
        catalog_report=None,
        repertoire_party_phase=SimpleNamespace(imported_parties=0, reused_existing_parties=2),
        repertoire_report=SimpleNamespace(
            imported_works=1,
            imported_contracts=2,
            imported_rights=3,
            imported_assets=4,
        ),
        imported_licenses=0,
        imported_contract_templates=0,
        imported_template_revisions=0,
        warnings=[],
    )

    controller._show_master_transfer_import_report(app, str(tmp_path / "repertoire.zip"), result)

    message = box.information.call_args.args[2]
    assert "Source app version: Unknown" in message
    assert "Contracts and Rights Party phase: created 0, reused 2" in message
    assert "Contracts and Rights: works 1, contracts 2, rights 3, assets 4" in message
