from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from PySide6.QtWidgets import QDialog

from isrc_manager.parties import (
    PartyExchangeInspection,
    PartyImportOptions,
    PartyImportReport,
    PartyRecord,
)
from isrc_manager.parties import controller as party_controller
from isrc_manager.services import OwnerPartySettings


def _party_record(
    party_id: int = 1,
    *,
    legal_name: str = "Legal Name B.V.",
    display_name: str | None = "Display Name",
    artist_name: str | None = "Artist Name",
    company_name: str | None = "Company Name",
    first_name: str | None = "",
    artist_aliases: tuple[str, ...] = (),
) -> PartyRecord:
    return PartyRecord(
        id=party_id,
        legal_name=legal_name,
        display_name=display_name,
        artist_name=artist_name,
        company_name=company_name,
        first_name=first_name,
        middle_name="",
        last_name="",
        party_type="organization",
        contact_person=None,
        email=None,
        alternative_email=None,
        phone=None,
        website=None,
        street_name=None,
        street_number=None,
        address_line1=None,
        address_line2=None,
        city=None,
        region=None,
        postal_code=None,
        country=None,
        bank_account_number=None,
        chamber_of_commerce_number=None,
        tax_id=None,
        vat_number=None,
        pro_affiliation=None,
        pro_number=None,
        ipi_cae=None,
        notes=None,
        profile_name=None,
        created_at=None,
        updated_at=None,
        artist_aliases=artist_aliases,
    )


def _inspection(path, *, format_name: str = "csv") -> PartyExchangeInspection:
    return PartyExchangeInspection(
        file_path=str(path),
        format_name=format_name,
        headers=["legal_name", "email"],
        preview_rows=[{"legal_name": "Lumen Rights", "email": "rights@example.test"}],
        suggested_mapping={"legal_name": "legal_name", "email": "email"},
    )


def _report(
    *,
    format_name: str = "csv",
    mode: str = "dry_run",
    evaluated_mode: str | None = None,
    created_parties: list[int] | None = None,
    updated_parties: list[int] | None = None,
    warnings: list[str] | None = None,
    would_create_parties: int = 0,
) -> PartyImportReport:
    return PartyImportReport(
        format_name=format_name,
        mode=mode,
        evaluated_mode=evaluated_mode,
        passed=2,
        failed=0,
        skipped=1,
        warnings=list(warnings or []),
        duplicates=[],
        unknown_fields=[],
        would_create_parties=would_create_parties,
        created_parties=list(created_parties or []),
        updated_parties=list(updated_parties or []),
        owner_party_id=(created_parties or [None])[0],
    )


class _FakeConn:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.statements: list[str] = []
        self.commit = mock.Mock(side_effect=commit_error)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement: str):
        self.statements.append(statement)


def test_owner_bootstrap_schedule_and_dialog_loop_branches(monkeypatch) -> None:
    callbacks: list[tuple[int, Any]] = []

    class FakeTimer:
        @staticmethod
        def singleShot(delay_ms, callback):
            callbacks.append((delay_ms, callback))

    monkeypatch.setattr(party_controller, "_timer", lambda: FakeTimer)
    scheduled_app = SimpleNamespace(
        _owner_party_bootstrap_scheduled=False,
        _ensure_owner_party_bootstrap=mock.Mock(),
    )

    party_controller._schedule_owner_party_bootstrap(scheduled_app)
    party_controller._schedule_owner_party_bootstrap(scheduled_app)

    assert scheduled_app._owner_party_bootstrap_scheduled is True
    assert len(callbacks) == 1
    assert callbacks[0][0] == 0
    callbacks[0][1]()
    scheduled_app._ensure_owner_party_bootstrap.assert_called_once_with()

    no_service_required_app = SimpleNamespace(
        party_service=None,
        _current_owner_party_record=mock.Mock(side_effect=AssertionError("should not read")),
    )
    assert party_controller._owner_bootstrap_required(no_service_required_app) is False

    not_required_app = SimpleNamespace(
        _owner_party_bootstrap_scheduled=True,
        party_service=object(),
        _owner_bootstrap_required=mock.Mock(return_value=False),
    )
    party_controller._ensure_owner_party_bootstrap(not_required_app)
    assert not_required_app._owner_party_bootstrap_scheduled is False

    no_service_app = SimpleNamespace(
        _owner_party_bootstrap_scheduled=True,
        party_service=None,
        _owner_bootstrap_required=mock.Mock(return_value=True),
    )
    party_controller._ensure_owner_party_bootstrap(no_service_app)
    assert no_service_app._owner_party_bootstrap_scheduled is False

    decisions = [
        (QDialog.Rejected, None),
        (QDialog.Accepted, None),
        (QDialog.Accepted, 77),
    ]
    dialog_owner_ids: list[int | None] = []

    class FakeOwnerBootstrapDialog:
        def __init__(self, *, current_owner_party_id, **kwargs):
            del kwargs
            dialog_owner_ids.append(current_owner_party_id)
            self._result, self._selected_party_id = decisions.pop(0)

        def exec(self):
            return self._result

        def selected_party_id(self):
            return self._selected_party_id

    state = {"assigned": False}
    assigned: list[tuple[int, bool]] = []

    def current_owner_record():
        return _party_record(77) if state["assigned"] else None

    def assign_owner_party(party_id, *, record_history=True):
        state["assigned"] = True
        assigned.append((party_id, record_history))
        return party_id

    monkeypatch.setattr(
        party_controller,
        "_owner_bootstrap_dialog_class",
        lambda: FakeOwnerBootstrapDialog,
    )
    bootstrap_app = SimpleNamespace(
        _owner_party_bootstrap_scheduled=True,
        party_service=object(),
        _owner_bootstrap_required=mock.Mock(return_value=True),
        _current_owner_party_record=current_owner_record,
        _current_owner_party_id=mock.Mock(return_value=None),
        _assign_owner_party=assign_owner_party,
    )

    party_controller._ensure_owner_party_bootstrap(bootstrap_app)

    assert bootstrap_app._owner_party_bootstrap_scheduled is False
    assert dialog_owner_ids == [None, None, None]
    assert assigned == [(77, False)]
    assert decisions == []


def test_legacy_owner_migration_early_returns_name_match_and_cleanup_noops() -> None:
    settings_reads = mock.Mock()
    party_controller._migrate_legacy_owner_party_if_needed(
        SimpleNamespace(
            party_service=None,
            settings_reads=settings_reads,
            settings_mutations=object(),
        )
    )
    settings_reads.load_legacy_owner_party_snapshot.assert_not_called()

    current_owner = _party_record(3, legal_name="Current Owner", display_name="Current")
    blank_snapshot = OwnerPartySettings()
    cleanup_conn = _FakeConn()
    cleanup_service = mock.Mock()
    settings_mutations = mock.Mock()
    cleanup_app = SimpleNamespace(
        party_service=cleanup_service,
        settings_reads=mock.Mock(
            load_legacy_owner_party_snapshot=mock.Mock(return_value=blank_snapshot)
        ),
        settings_mutations=settings_mutations,
        conn=cleanup_conn,
        _current_owner_party_record=mock.Mock(return_value=current_owner),
        _legacy_owner_snapshot_has_data=party_controller._legacy_owner_snapshot_has_data,
        _merge_owner_snapshot_into_party=party_controller._merge_owner_snapshot_into_party,
    )

    party_controller._migrate_legacy_owner_party_if_needed(cleanup_app)

    cleanup_service.update_party.assert_not_called()
    settings_mutations.set_owner_party_id.assert_called_once_with(3)
    assert cleanup_conn.statements == [
        "DELETE FROM BTW WHERE id=1",
        "DELETE FROM BUMA_STEMRA WHERE id=1",
    ]

    no_data_service = mock.Mock()
    no_data_app = SimpleNamespace(
        party_service=no_data_service,
        settings_reads=mock.Mock(
            load_legacy_owner_party_snapshot=mock.Mock(return_value=blank_snapshot)
        ),
        settings_mutations=mock.Mock(),
        conn=_FakeConn(),
        _current_owner_party_record=mock.Mock(return_value=None),
        _legacy_owner_snapshot_has_data=party_controller._legacy_owner_snapshot_has_data,
    )

    party_controller._migrate_legacy_owner_party_if_needed(no_data_app)

    no_data_service.create_party.assert_not_called()
    assert no_data_app.conn.statements == []

    snapshot = OwnerPartySettings(
        party_id=55,
        legal_name="Legacy Owner Legal",
        display_name="Legacy Owner",
        email="legacy@example.test",
    )
    matched_record = _party_record(
        8,
        legal_name="",
        display_name=None,
        artist_name=None,
        company_name=None,
    )
    fetches: list[int] = []

    def fetch_party(party_id: int):
        fetches.append(int(party_id))
        return matched_record if int(party_id) == 8 else None

    name_match_service = mock.Mock(
        fetch_party=mock.Mock(side_effect=fetch_party),
        find_party_id_by_name=mock.Mock(return_value=8),
    )
    name_match_conn = _FakeConn()
    name_match_app = SimpleNamespace(
        party_service=name_match_service,
        settings_reads=mock.Mock(load_legacy_owner_party_snapshot=mock.Mock(return_value=snapshot)),
        settings_mutations=mock.Mock(),
        conn=name_match_conn,
        _current_owner_party_record=mock.Mock(return_value=None),
        _legacy_owner_snapshot_has_data=party_controller._legacy_owner_snapshot_has_data,
        _merge_owner_snapshot_into_party=party_controller._merge_owner_snapshot_into_party,
        _owner_snapshot_name_candidates=party_controller._owner_snapshot_name_candidates,
        _owner_snapshot_to_party_payload=party_controller._owner_snapshot_to_party_payload,
        _assign_owner_party=mock.Mock(),
        _current_profile_name=mock.Mock(return_value="Profile.db"),
    )

    party_controller._migrate_legacy_owner_party_if_needed(name_match_app)

    assert fetches == [55, 8]
    name_match_service.find_party_id_by_name.assert_called_once_with("Legacy Owner Legal")
    name_match_service.update_party.assert_called_once()
    payload = name_match_service.update_party.call_args.args[1]
    assert payload.legal_name == "Legacy Owner Legal"
    assert payload.email == "legacy@example.test"
    name_match_app._assign_owner_party.assert_called_once_with(8, record_history=False)
    assert name_match_conn.statements == [
        "DELETE FROM BTW WHERE id=1",
        "DELETE FROM BUMA_STEMRA WHERE id=1",
    ]


def test_artist_authority_handles_service_failure_and_non_combo_refresh_fields() -> None:
    failing_service = mock.Mock(
        list_artist_parties=mock.Mock(side_effect=RuntimeError("registry unavailable"))
    )
    assert (
        party_controller._artist_party_records(SimpleNamespace(party_service=failing_service)) == []
    )

    refresh_app = SimpleNamespace(
        artist_field=object(),
        additional_artist_field="not a combo",
        _resolve_artist_party_choice=mock.Mock(),
        _configure_artist_party_combo=mock.Mock(),
    )
    party_controller._refresh_add_track_artist_party_choices(refresh_app)
    refresh_app._resolve_artist_party_choice.assert_not_called()
    refresh_app._configure_artist_party_combo.assert_not_called()

    early_return_app = SimpleNamespace(
        conn=None,
        populate_all_comboboxes=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
    )
    party_controller._on_party_authority_changed(early_return_app)
    early_return_app.populate_all_comboboxes.assert_not_called()
    early_return_app.refresh_table_preserve_view.assert_not_called()


def test_import_party_exchange_apply_review_and_success_callbacks(monkeypatch, tmp_path) -> None:
    source = tmp_path / "parties.csv"
    file_dialog = mock.Mock(getOpenFileName=mock.Mock(return_value=(str(source), "")))
    monkeypatch.setattr(party_controller, "_file_dialog", lambda: file_dialog)

    initial_inspection = _inspection(source)
    reinspection = _inspection(source)
    preview_report = _report(
        evaluated_mode="upsert",
        warnings=["preview warning"],
        would_create_parties=1,
    )
    apply_report = _report(
        mode="upsert",
        created_parties=[44],
        updated_parties=[45],
        warnings=["applied warning"],
    )
    exchange_service = mock.Mock(
        inspect_csv=mock.Mock(side_effect=[initial_inspection, reinspection]),
        supported_import_targets=mock.Mock(return_value=["legal_name", "email"]),
        import_csv=mock.Mock(side_effect=[preview_report, apply_report]),
    )
    submissions: list[dict[str, Any]] = []
    history_calls: list[dict[str, Any]] = []

    class FocusPanel:
        def __init__(self) -> None:
            self.focused_party_ids: list[int] = []

        def focus_party(self, party_id: int) -> None:
            self.focused_party_ids.append(int(party_id))

    panel = FocusPanel()

    class AcceptedApplyDialog:
        def __init__(self, *, csv_reinspect_callback, **kwargs):
            del kwargs
            self.reinspection = csv_reinspect_callback("|")

        def exec(self):
            return QDialog.Accepted

        def mapping(self):
            return {"legal_name": "legal_name", "email": "email"}

        def import_options(self):
            return PartyImportOptions(mode="upsert")

        def resolved_csv_delimiter(self):
            return ";"

    def fake_snapshot_history_action(**kwargs):
        history_calls.append(kwargs)
        return kwargs["mutation"]()

    monkeypatch.setattr(
        party_controller,
        "_party_import_dialog_class",
        lambda: AcceptedApplyDialog,
    )
    monkeypatch.setattr(party_controller, "_party_manager_panel_class", lambda: FocusPanel)
    monkeypatch.setattr(
        party_controller,
        "_run_snapshot_history_action",
        fake_snapshot_history_action,
    )
    app = SimpleNamespace(
        party_exchange_service=exchange_service,
        settings=object(),
        logger=mock.Mock(),
        _scaled_progress_callback=mock.Mock(side_effect=lambda callback, start, end: callback),
        _submit_background_bundle_task=mock.Mock(
            side_effect=lambda **kwargs: submissions.append(kwargs)
        ),
        _show_background_task_error=mock.Mock(),
        _open_import_review_dialog=mock.Mock(side_effect=[False, True]),
        _party_import_review_summary=party_controller._party_import_review_summary,
        _advance_task_ui_progress=mock.Mock(),
        populate_all_comboboxes=mock.Mock(),
        _refresh_catalog_workspace_docks=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_party_import_report=mock.Mock(),
        conn=_FakeConn(commit_error=RuntimeError("commit failed")),
        party_manager_panel=panel,
    )

    party_controller.import_party_exchange_file(app, "csv")

    assert submissions[0]["title"] == "Inspect Parties CSV"
    ctx = SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock())
    bundle = SimpleNamespace(party_exchange_service=exchange_service, history_manager=object())
    assert submissions[0]["task_fn"](bundle, ctx) is initial_inspection

    submissions[0]["on_success_after_cleanup"](initial_inspection)

    assert len(submissions) == 2
    assert submissions[1]["title"] == "Review Parties CSV"
    assert any(
        call.kwargs.get("delimiter") == "|" for call in exchange_service.inspect_csv.call_args_list
    )
    assert submissions[1]["task_fn"](bundle, ctx) is preview_report
    preview_options = exchange_service.import_csv.call_args_list[0].kwargs["options"]
    assert preview_options.mode == "dry_run"
    assert preview_options.preview_apply_mode == "upsert"

    submissions[1]["on_success_after_cleanup"](preview_report)
    assert len(submissions) == 2
    review_kwargs = app._open_import_review_dialog.call_args.kwargs
    assert review_kwargs["confirm_label"] == "Apply Party Import"
    assert "Would create Parties: 1" in review_kwargs["summary_lines"]

    submissions[1]["on_success_after_cleanup"](preview_report)

    assert len(submissions) == 3
    import_task = submissions[2]
    assert import_task["kind"] == "write"
    assert import_task["task_fn"](bundle, ctx) is apply_report
    assert history_calls[0]["action_type"] == "party.import.csv"
    apply_options = exchange_service.import_csv.call_args_list[-1].kwargs["options"]
    assert apply_options.mode == "upsert"
    assert exchange_service.import_csv.call_args_list[-1].kwargs["delimiter"] == ";"

    ui_progress = mock.Mock()
    import_task["on_success_before_cleanup"](apply_report, ui_progress)

    app.conn.commit.assert_called_once_with()
    app.populate_all_comboboxes.assert_called_once_with()
    app._refresh_catalog_workspace_docks.assert_called_once_with()
    app._refresh_history_actions.assert_called_once_with()
    assert panel.focused_party_ids == [44]
    progress_messages = [
        call.kwargs["message"] for call in app._advance_task_ui_progress.call_args_list
    ]
    assert progress_messages == [
        "Applying imported Party changes...",
        "Refreshing Party views and history...",
        "Party import complete.",
    ]

    import_task["on_success_after_cleanup"](apply_report)

    app._log_event.assert_called_once()
    assert app._log_event.call_args.args[:2] == (
        "party.import.csv",
        "Imported CSV Party data",
    )
    assert app._log_event.call_args.kwargs["created"] == 1
    assert app._log_event.call_args.kwargs["updated"] == 1
    app._audit.assert_called_once()
    assert "format=csv; mode=upsert" in app._audit.call_args.kwargs["details"]
    app._audit_commit.assert_called_once_with()
    app._show_party_import_report.assert_called_once_with(str(source), apply_report)


def test_import_party_exchange_rejected_dialog_and_unsupported_format(
    monkeypatch,
    tmp_path,
) -> None:
    source = tmp_path / "parties.json"
    file_dialog = mock.Mock(getOpenFileName=mock.Mock(return_value=(str(source), "")))
    monkeypatch.setattr(party_controller, "_file_dialog", lambda: file_dialog)

    inspection = _inspection(source, format_name="json")
    exchange_service = mock.Mock(
        inspect_json=mock.Mock(return_value=inspection),
        supported_import_targets=mock.Mock(return_value=["legal_name"]),
    )
    submissions: list[dict[str, Any]] = []

    class RejectedImportDialog:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(
        party_controller,
        "_party_import_dialog_class",
        lambda: RejectedImportDialog,
    )
    app = SimpleNamespace(
        party_exchange_service=exchange_service,
        settings=object(),
        _scaled_progress_callback=mock.Mock(side_effect=lambda callback, start, end: callback),
        _submit_background_bundle_task=mock.Mock(
            side_effect=lambda **kwargs: submissions.append(kwargs)
        ),
        _show_background_task_error=mock.Mock(),
    )

    party_controller.import_party_exchange_file(app, "json")

    ctx = SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock())
    bundle = SimpleNamespace(party_exchange_service=exchange_service, history_manager=object())
    assert submissions[0]["task_fn"](bundle, ctx) is inspection
    submissions[0]["on_success_after_cleanup"](inspection)
    assert len(submissions) == 1

    source_xml = tmp_path / "parties.xml"
    file_dialog.getOpenFileName.return_value = (str(source_xml), "")
    submissions.clear()
    party_controller.import_party_exchange_file(app, "xml")

    assert submissions[0]["title"] == "Inspect Parties XML"
    with pytest.raises(ValueError, match="Unsupported Party exchange format: xml"):
        submissions[0]["task_fn"](bundle, ctx)


def test_export_party_exchange_selected_panel_ids_and_success_audit(monkeypatch, tmp_path) -> None:
    target = tmp_path / "selected_parties.csv"
    resolved_target = tmp_path / "resolved" / "selected_parties.csv"
    file_dialog = mock.Mock(getSaveFileName=mock.Mock(return_value=(str(target), "")))
    message_box = mock.Mock()
    monkeypatch.setattr(party_controller, "_file_dialog", lambda: file_dialog)
    monkeypatch.setattr(party_controller, "_message_box", lambda: message_box)

    history_payloads: list[dict[str, Any]] = []

    def fake_file_history_action(**kwargs):
        count = kwargs["mutation"]()
        history_payloads.append(
            {
                "action_label": kwargs["action_label"](count),
                "action_type": kwargs["action_type"],
                "payload": kwargs["payload"](count),
                "target_path": kwargs["target_path"],
            }
        )
        return count

    monkeypatch.setattr(
        party_controller,
        "_run_file_history_action",
        fake_file_history_action,
    )
    exchange_service = mock.Mock(export_csv=mock.Mock(return_value=2))
    submissions: list[dict[str, Any]] = []
    app = SimpleNamespace(
        party_exchange_service=exchange_service,
        exports_dir=tmp_path,
        _selected_party_manager_ids=mock.Mock(return_value=[5, 6]),
        _resolve_file_export_target=mock.Mock(return_value=resolved_target),
        _scaled_progress_callback=mock.Mock(side_effect=lambda callback, start, end: callback),
        _submit_background_bundle_task=mock.Mock(
            side_effect=lambda **kwargs: submissions.append(kwargs)
        ),
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        logger=mock.Mock(),
    )

    party_controller.export_party_exchange_file(app, "csv", selected_only=True)

    default_filename = app._resolve_file_export_target.call_args.kwargs["default_filename"]
    assert default_filename.startswith("selected_parties_csv_")
    assert default_filename.endswith(".csv")
    assert submissions[0]["title"] == "Export Parties CSV"

    ctx = SimpleNamespace(report_progress=mock.Mock())
    bundle = SimpleNamespace(party_exchange_service=exchange_service, history_manager=object())
    assert submissions[0]["task_fn"](bundle, ctx) == 2
    exchange_service.export_csv.assert_called_once_with(
        resolved_target,
        [5, 6],
        progress_callback=ctx.report_progress,
    )
    assert history_payloads == [
        {
            "action_label": "Export Parties CSV: 2 rows",
            "action_type": "file.party_export_csv",
            "payload": {
                "path": str(resolved_target),
                "format": "csv",
                "selected_only": True,
                "count": 2,
            },
            "target_path": resolved_target,
        }
    ]

    submissions[0]["on_success_after_cleanup"](2)

    app._refresh_history_actions.assert_called_once_with()
    assert app._log_event.call_args.kwargs["selected_party_count"] == 2
    assert app._log_event.call_args.kwargs["selected_only"] is True
    assert "selected_only=1" in app._audit.call_args.kwargs["details"]
    app._audit_commit.assert_called_once_with()
    assert "Exported 2 Parties" in message_box.information.call_args.args[2]


def test_panel_refresh_and_owner_registration_redirect_branches(monkeypatch) -> None:
    class RefreshPanel:
        def __init__(self, *, visible: bool = True) -> None:
            self._visible = visible
            self.refresh = mock.Mock()

        def isVisible(self):
            return self._visible

    visible_panel = RefreshPanel()
    refresh_app = SimpleNamespace(
        party_manager_panel=visible_panel,
        party_manager_dialog=visible_panel,
    )

    party_controller._refresh_party_manager_panel(refresh_app)

    visible_panel.refresh.assert_called_once_with()

    hidden_panel = RefreshPanel(visible=False)
    no_refresh_panel = SimpleNamespace(isVisible=mock.Mock(return_value=True))
    refresh_app = SimpleNamespace(
        party_manager_panel=hidden_panel,
        party_manager_dialog=no_refresh_panel,
    )

    party_controller._refresh_party_manager_panel(refresh_app)

    hidden_panel.refresh.assert_not_called()
    no_refresh_panel.isVisible.assert_called_once_with()

    message_box = mock.Mock()
    monkeypatch.setattr(party_controller, "_message_box", lambda: message_box)
    redirect_app = SimpleNamespace(
        _current_owner_party_id=mock.Mock(return_value=None),
        open_party_manager=mock.Mock(),
    )

    party_controller._redirect_owner_registration_edit_to_party_manager(
        redirect_app,
        "VAT number",
    )

    redirect_app.open_party_manager.assert_called_once_with()
    assert message_box.information.call_args.args[1] == "VAT number"

    redirect_app._current_owner_party_id.return_value = 123
    redirect_app.open_party_manager.reset_mock()
    message_box.reset_mock()

    party_controller._redirect_owner_registration_edit_to_party_manager(
        redirect_app,
        "IPI number",
    )

    redirect_app.open_party_manager.assert_called_once_with(123)
    assert message_box.information.call_args.args[1] == "IPI number"


def test_party_controller_root_wrappers_owner_id_and_selected_panel_fallbacks(
    monkeypatch,
) -> None:
    sentinels = {
        "QMessageBox": object(),
        "QFileDialog": object(),
        "QTimer": object(),
    }
    history_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def fake_root_attr(name, fallback):
        if name in sentinels:
            return sentinels[name]
        if name in {"run_snapshot_history_action", "run_file_history_action"}:
            return lambda *args, **kwargs: history_calls.append((name, args, kwargs)) or name
        return fallback

    monkeypatch.setattr(party_controller, "_root_attr", fake_root_attr)

    assert party_controller._message_box() is sentinels["QMessageBox"]
    assert party_controller._file_dialog() is sentinels["QFileDialog"]
    assert party_controller._timer() is sentinels["QTimer"]
    assert party_controller._run_snapshot_history_action(entity_id=1) == (
        "run_snapshot_history_action"
    )
    assert party_controller._run_file_history_action(entity_id=2) == ("run_file_history_action")
    assert history_calls == [
        ("run_snapshot_history_action", (), {"entity_id": 1}),
        ("run_file_history_action", (), {"entity_id": 2}),
    ]
    assert party_controller._current_owner_party_id(SimpleNamespace()) is None

    class FakePanel:
        def __init__(self, *, visible: bool, ids: list[int]) -> None:
            self._visible = visible
            self._ids = ids

        def isVisible(self):
            return self._visible

        def selected_party_ids(self):
            return list(self._ids)

    monkeypatch.setattr(party_controller, "_party_manager_panel_class", lambda: FakePanel)
    hidden_selected = FakePanel(visible=False, ids=[7])
    visible_empty = FakePanel(visible=True, ids=[])
    app = SimpleNamespace(
        party_manager_panel=hidden_selected,
        party_manager_dialog=SimpleNamespace(panel=visible_empty),
        party_manager_dock=SimpleNamespace(widget=lambda: hidden_selected),
    )

    assert party_controller._selected_party_manager_ids(app) == [7]
    assert party_controller._selected_party_manager_ids(SimpleNamespace()) == []


def test_party_import_report_copy_includes_dry_run_mutation_and_warning_details(
    monkeypatch,
) -> None:
    message_box = mock.Mock()
    monkeypatch.setattr(party_controller, "_message_box", lambda: message_box)
    report = PartyImportReport(
        format_name="csv",
        mode="dry_run",
        passed=4,
        failed=1,
        skipped=2,
        warnings=[f"warning {index}" for index in range(14)],
        duplicates=["duplicate legal name"],
        unknown_fields=[f"field_{index}" for index in range(10)],
        evaluated_mode="upsert",
        would_create_parties=3,
        would_update_parties=2,
        would_set_owner=True,
        created_parties=[21],
        updated_parties=[22],
        owner_party_id=21,
    )

    party_controller._show_party_import_report(SimpleNamespace(), "/tmp/parties.csv", report)

    body = message_box.information.call_args.args[2]
    assert "No database changes were made" in body
    assert "Would create: 3" in body
    assert "Would update: 2" in body
    assert "Would update the current Owner Party binding." in body
    assert "Created: 1" in body
    assert "Updated: 1" in body
    assert "Owner Party: 21" in body
    assert "Duplicates: 1" in body
    assert "Unmapped fields: field_0, field_1" in body
    assert "- warning 11" in body
    assert "warning 12" not in body


def test_import_party_exchange_xlsx_preflight_and_apply_paths(
    monkeypatch,
    tmp_path,
) -> None:
    source = tmp_path / "parties.xlsx"
    file_dialog = mock.Mock(getOpenFileName=mock.Mock(return_value=(str(source), "")))
    monkeypatch.setattr(party_controller, "_file_dialog", lambda: file_dialog)
    monkeypatch.setattr(
        party_controller,
        "_run_snapshot_history_action",
        lambda **kwargs: kwargs["mutation"](),
    )

    inspection = _inspection(source, format_name="xlsx")
    preview_report = _report(
        format_name="xlsx",
        evaluated_mode="upsert",
        would_create_parties=1,
    )
    apply_report = _report(
        format_name="xlsx",
        mode="upsert",
        created_parties=[61],
        updated_parties=[],
    )
    exchange_service = mock.Mock(
        inspect_xlsx=mock.Mock(return_value=inspection),
        supported_import_targets=mock.Mock(return_value=["legal_name", "email"]),
        import_xlsx=mock.Mock(side_effect=[preview_report, apply_report]),
    )
    submissions: list[dict[str, Any]] = []

    class AcceptedImportDialog:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return QDialog.Accepted

        def mapping(self):
            return {"legal_name": "legal_name", "email": "email"}

        def import_options(self):
            return PartyImportOptions(mode="upsert")

        def resolved_csv_delimiter(self):
            return None

    monkeypatch.setattr(
        party_controller,
        "_party_import_dialog_class",
        lambda: AcceptedImportDialog,
    )
    app = SimpleNamespace(
        party_exchange_service=exchange_service,
        settings=object(),
        logger=mock.Mock(),
        _scaled_progress_callback=mock.Mock(side_effect=lambda callback, start, end: callback),
        _submit_background_bundle_task=mock.Mock(
            side_effect=lambda **kwargs: submissions.append(kwargs)
        ),
        _show_background_task_error=mock.Mock(),
        _open_import_review_dialog=mock.Mock(return_value=True),
        _party_import_review_summary=party_controller._party_import_review_summary,
        _advance_task_ui_progress=mock.Mock(),
        populate_all_comboboxes=mock.Mock(),
        _refresh_catalog_workspace_docks=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_party_import_report=mock.Mock(),
        conn=_FakeConn(commit_error=RuntimeError("commit failed")),
        party_manager_panel=object(),
    )

    party_controller.import_party_exchange_file(app, "xlsx")

    ctx = SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock())
    bundle = SimpleNamespace(party_exchange_service=exchange_service, history_manager=object())
    assert submissions[0]["task_fn"](bundle, ctx) is inspection
    exchange_service.inspect_xlsx.assert_called_once()

    submissions[0]["on_success_after_cleanup"](inspection)
    assert submissions[1]["title"] == "Review Parties XLSX"
    assert submissions[1]["task_fn"](bundle, ctx) is preview_report
    preview_options = exchange_service.import_xlsx.call_args_list[0].kwargs["options"]
    assert preview_options.mode == "dry_run"
    assert preview_options.preview_apply_mode == "upsert"

    submissions[1]["on_success_after_cleanup"](preview_report)
    assert submissions[2]["title"] == "Import Parties XLSX"
    assert submissions[2]["task_fn"](bundle, ctx) is apply_report
    apply_options = exchange_service.import_xlsx.call_args_list[-1].kwargs["options"]
    assert apply_options.mode == "upsert"

    ui_progress = mock.Mock()
    submissions[2]["on_success_before_cleanup"](apply_report, ui_progress)
    app.populate_all_comboboxes.assert_called_once_with()
    app._refresh_catalog_workspace_docks.assert_called_once_with()
    app._refresh_history_actions.assert_called_once_with()
    submissions[2]["on_success_after_cleanup"](apply_report)
    app._show_party_import_report.assert_called_once_with(str(source), apply_report)
