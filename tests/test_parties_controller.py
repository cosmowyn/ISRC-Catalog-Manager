from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest
from PySide6.QtWidgets import QComboBox, QDialog

from isrc_manager.parties import (
    PartyExchangeInspection,
    PartyImportOptions,
    PartyImportReport,
    PartyRecord,
)
from isrc_manager.parties import controller as party_controller
from isrc_manager.services import OwnerPartySettings
from tests.qt_test_helpers import require_qapplication


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


def test_owner_party_identity_snapshot_payload_and_merge_helpers() -> None:
    record = _party_record(display_name="Display", legal_name="Legal")
    assert party_controller._party_identity_primary_label(record) == "Display"
    assert party_controller._owner_party_choice_label(record) == "Display (Legal)"
    assert (
        party_controller._owner_party_choice_label(
            _party_record(display_name="Same", legal_name="same")
        )
        == "Same"
    )
    assert (
        party_controller._party_identity_primary_label(
            _party_record(
                party_id=9,
                legal_name="",
                display_name="",
                artist_name="",
                company_name="",
            )
        )
        == "Party #9"
    )

    blank_snapshot = OwnerPartySettings()
    assert party_controller._legacy_owner_snapshot_has_data(blank_snapshot) is False
    snapshot = OwnerPartySettings(
        legal_name="Owner Legal",
        display_name="Owner Display",
        artist_name="Owner Artist",
        company_name="Owner Co",
        first_name="Lyra",
        middle_name="Cosmo",
        last_name="Wyn",
        email="owner@example.test",
        vat_number="VAT-123",
    )
    assert party_controller._legacy_owner_snapshot_has_data(snapshot) is True
    assert party_controller._owner_snapshot_name_candidates(snapshot) == [
        "Owner Legal",
        "Owner Display",
        "Owner Artist",
        "Owner Co",
        "Lyra Cosmo Wyn",
    ]

    payload = party_controller._owner_snapshot_to_party_payload(
        snapshot,
        profile_name="Profile.db",
    )
    assert payload.legal_name == "Owner Legal"
    assert payload.party_type == "person"
    assert payload.profile_name == "Profile.db"
    assert payload.email == "owner@example.test"

    merged = party_controller._merge_owner_snapshot_into_party(
        _party_record(
            legal_name="Existing Legal",
            display_name=None,
            artist_name=None,
            company_name="Existing Co",
            artist_aliases=("Alias",),
        ),
        snapshot,
    )
    assert merged.legal_name == "Existing Legal"
    assert merged.display_name == "Owner Display"
    assert merged.company_name == "Existing Co"
    assert merged.artist_aliases == ["Alias"]


def test_assign_owner_party_records_history_refreshes_and_status() -> None:
    status_bar = mock.Mock()
    owner = _party_record(display_name="Owner Display", legal_name="Owner Legal")
    app = SimpleNamespace(
        settings_mutations=mock.Mock(set_owner_party_id=mock.Mock(return_value=7)),
        history_manager=mock.Mock(),
        _current_owner_party_id=mock.Mock(return_value=2),
        _refresh_catalog_workspace_docks=mock.Mock(),
        _current_owner_party_record=mock.Mock(return_value=owner),
        _owner_party_choice_label=party_controller._owner_party_choice_label,
        statusBar=mock.Mock(return_value=status_bar),
    )

    assert party_controller._assign_owner_party(app, 7) == 7

    app.settings_mutations.set_owner_party_id.assert_called_once_with(7)
    app.history_manager.record_setting_change.assert_called_once_with(
        key="owner_party_id",
        label="Set Current Owner Party",
        before_value=2,
        after_value=7,
    )
    app._refresh_catalog_workspace_docks.assert_called_once_with()
    status_bar.showMessage.assert_called_once()

    app.settings_mutations = None
    assert party_controller._assign_owner_party(app, 9) is None


def test_legacy_owner_party_migration_updates_matches_and_creates_new_owner() -> None:
    class FakeConn:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement):
            self.statements.append(statement)

    snapshot = OwnerPartySettings(
        party_id=9,
        legal_name="Legacy Legal",
        display_name="Legacy Display",
        first_name="Lyra",
        email="legacy@example.test",
    )
    current_owner = _party_record(3, legal_name="Current Legal", display_name="Current Owner")
    linked_owner = _party_record(9, legal_name="Linked Legal", display_name="Linked Owner")

    party_service = mock.Mock()
    settings_reads = mock.Mock(load_legacy_owner_party_snapshot=mock.Mock(return_value=snapshot))
    settings_mutations = mock.Mock()
    app = SimpleNamespace(
        party_service=party_service,
        settings_reads=settings_reads,
        settings_mutations=settings_mutations,
        conn=FakeConn(),
        _current_owner_party_record=mock.Mock(return_value=current_owner),
        _legacy_owner_snapshot_has_data=party_controller._legacy_owner_snapshot_has_data,
        _merge_owner_snapshot_into_party=party_controller._merge_owner_snapshot_into_party,
        _owner_snapshot_name_candidates=party_controller._owner_snapshot_name_candidates,
        _owner_snapshot_to_party_payload=party_controller._owner_snapshot_to_party_payload,
        _assign_owner_party=mock.Mock(),
        _current_profile_name=mock.Mock(return_value="Profile.db"),
    )

    party_controller._migrate_legacy_owner_party_if_needed(app)

    party_service.update_party.assert_called_once()
    settings_mutations.set_owner_party_id.assert_called_once_with(3)
    assert app.conn.statements == [
        "DELETE FROM BTW WHERE id=1",
        "DELETE FROM BUMA_STEMRA WHERE id=1",
    ]

    party_service.reset_mock()
    party_service.update_party.side_effect = RuntimeError("update ignored")
    app.conn = FakeConn()
    party_controller._migrate_legacy_owner_party_if_needed(app)
    settings_mutations.set_owner_party_id.assert_called_with(3)
    assert app.conn.statements == [
        "DELETE FROM BTW WHERE id=1",
        "DELETE FROM BUMA_STEMRA WHERE id=1",
    ]

    party_service = mock.Mock(fetch_party=mock.Mock(return_value=linked_owner))
    app = SimpleNamespace(
        party_service=party_service,
        settings_reads=settings_reads,
        settings_mutations=settings_mutations,
        conn=FakeConn(),
        _current_owner_party_record=mock.Mock(return_value=None),
        _legacy_owner_snapshot_has_data=party_controller._legacy_owner_snapshot_has_data,
        _merge_owner_snapshot_into_party=party_controller._merge_owner_snapshot_into_party,
        _owner_snapshot_name_candidates=party_controller._owner_snapshot_name_candidates,
        _owner_snapshot_to_party_payload=party_controller._owner_snapshot_to_party_payload,
        _assign_owner_party=mock.Mock(),
        _current_profile_name=mock.Mock(return_value="Profile.db"),
    )
    party_controller._migrate_legacy_owner_party_if_needed(app)
    party_service.update_party.assert_called_once()
    app._assign_owner_party.assert_called_once_with(9, record_history=False)

    create_service = mock.Mock(
        fetch_party=mock.Mock(return_value=None),
        find_party_id_by_name=mock.Mock(return_value=None),
        create_party=mock.Mock(return_value=42),
    )
    app.party_service = create_service
    app.conn = FakeConn()
    app._assign_owner_party = mock.Mock()
    party_controller._migrate_legacy_owner_party_if_needed(app)
    create_service.create_party.assert_called_once()
    payload = create_service.create_party.call_args.args[0]
    assert payload.legal_name == "Legacy Legal"
    assert payload.profile_name == "Profile.db"
    app._assign_owner_party.assert_called_once_with(42, record_history=False)


def test_artist_party_combo_resolution_and_party_backed_names() -> None:
    require_qapplication()
    artist = _party_record(
        party_id=4,
        legal_name="Legal Artist",
        display_name="Display Artist",
        artist_name="Primary Artist",
        artist_aliases=("Alias Artist",),
    )
    fallback = _party_record(
        party_id=99,
        legal_name="Created Artist",
        display_name="",
        artist_name="Created Artist",
    )

    class PartyService:
        def __init__(self) -> None:
            self.created: list[str] = []

        def list_artist_parties(self):
            return [artist]

        def find_artist_party_id_by_name(self, name, cursor=None):
            return 4 if str(name).casefold() in {"primary artist", "alias artist"} else None

        def ensure_artist_party_by_name(self, name, cursor=None):
            self.created.append(str(name))
            return 99

        def fetch_party(self, party_id):
            return {4: artist, 99: fallback}.get(int(party_id))

    service = PartyService()
    app = SimpleNamespace(
        party_service=service,
        _artist_party_records=lambda: party_controller._artist_party_records(app),
        _artist_party_choice_label=party_controller._artist_party_choice_label,
        _artist_party_primary_label=party_controller._artist_party_primary_label,
        _resolve_artist_party_choice=lambda combo: party_controller._resolve_artist_party_choice(
            app, combo
        ),
        _configure_artist_party_combo=lambda combo, **kwargs: party_controller._configure_artist_party_combo(
            app, combo, **kwargs
        ),
        _resolve_party_backed_artist_name=lambda raw_name, **kwargs: party_controller._resolve_party_backed_artist_name(
            app, raw_name, **kwargs
        ),
    )

    combo = QComboBox()
    party_controller._configure_artist_party_combo(app, combo, selected_party_id=4)
    assert combo.count() == 1
    assert party_controller._resolve_artist_party_choice(app, combo) == ("Primary Artist", 4)

    unknown_combo = QComboBox()
    party_controller._configure_artist_party_combo(
        app,
        unknown_combo,
        allow_empty=True,
        selected_party_id=42,
        current_text="Legacy Artist",
    )
    assert unknown_combo.findData(42) >= 0
    unknown_combo.setCurrentIndex(-1)
    unknown_combo.setEditText("Typed Artist")
    assert party_controller._resolve_artist_party_choice(app, unknown_combo) == (
        "Typed Artist",
        None,
    )

    assert party_controller._resolve_party_backed_artist_name(app, "Alias Artist") == (
        "Primary Artist",
        4,
    )
    assert party_controller._resolve_party_backed_artist_name(app, "New Artist") == (
        "Created Artist",
        99,
    )
    assert service.created == ["New Artist"]
    assert party_controller._resolve_party_backed_additional_artist_names(
        app,
        ["Alias Artist", "alias artist", "", "New Artist"],
    ) == ["Primary Artist", "Created Artist"]

    no_service_app = SimpleNamespace(party_service=None)
    assert party_controller._artist_party_records(no_service_app) == []
    assert party_controller._resolve_party_backed_artist_name(no_service_app, "Raw") == (
        "Raw",
        None,
    )

    missing_record_service = mock.Mock(
        find_artist_party_id_by_name=mock.Mock(return_value=None),
        ensure_artist_party_by_name=mock.Mock(return_value=123),
        fetch_party=mock.Mock(return_value=None),
    )
    missing_record_app = SimpleNamespace(
        party_service=missing_record_service,
        _artist_party_primary_label=party_controller._artist_party_primary_label,
    )
    assert party_controller._resolve_party_backed_artist_name(missing_record_app, "Ghost") == (
        "Ghost",
        123,
    )


def test_party_authority_refresh_and_selection_helpers_handle_panel_fallbacks(monkeypatch):
    require_qapplication()

    class FakePanel:
        def __init__(self, visible=True, selected_ids=()):
            self._visible = visible
            self._selected_ids = list(selected_ids)
            self.refresh = mock.Mock()

        def isVisible(self):
            return self._visible

        def selected_party_ids(self):
            return list(self._selected_ids)

    monkeypatch.setattr(party_controller, "_party_manager_panel_class", lambda: FakePanel)

    hidden_panel = FakePanel(visible=False, selected_ids=[3])
    visible_panel = FakePanel(visible=True, selected_ids=[])
    dock_panel = FakePanel(visible=True, selected_ids=[8])
    app = SimpleNamespace(
        party_manager_panel=hidden_panel,
        party_manager_dialog=SimpleNamespace(panel=visible_panel),
        party_manager_dock=SimpleNamespace(widget=lambda: dock_panel),
    )
    assert party_controller._selected_party_manager_ids(app) == [8]

    app.party_manager_panel = FakePanel(visible=True, selected_ids=[2])
    assert party_controller._selected_party_manager_ids(app) == [2]

    artist_combo = QComboBox()
    additional_combo = QComboBox()
    party_controller._configure_artist_party_combo(
        SimpleNamespace(
            _artist_party_records=mock.Mock(return_value=[]),
            _artist_party_choice_label=party_controller._artist_party_choice_label,
            _artist_party_primary_label=party_controller._artist_party_primary_label,
        ),
        artist_combo,
        current_text="Artist",
    )
    refresh_app = SimpleNamespace(
        conn=object(),
        artist_field=artist_combo,
        additional_artist_field=additional_combo,
        release_browser_dialog=SimpleNamespace(
            isVisible=mock.Mock(return_value=True), refresh=mock.Mock()
        ),
        _configure_artist_party_combo=mock.Mock(side_effect=RuntimeError("combo refresh failed")),
        populate_all_comboboxes=mock.Mock(side_effect=RuntimeError("combo failure")),
        refresh_table_preserve_view=mock.Mock(side_effect=RuntimeError("table failure")),
        _refresh_work_manager_panel=mock.Mock(side_effect=RuntimeError("work failure")),
        _refresh_party_manager_panel=mock.Mock(side_effect=RuntimeError("party failure")),
        _refresh_catalog_workspace_docks=mock.Mock(side_effect=RuntimeError("dock failure")),
        _refresh_add_track_artist_party_choices=mock.Mock(
            side_effect=RuntimeError("artist failure")
        ),
    )
    refresh_app._resolve_artist_party_choice = (
        lambda combo: party_controller._resolve_artist_party_choice(refresh_app, combo)
    )
    party_controller._on_party_authority_changed(refresh_app)
    refresh_app.populate_all_comboboxes.assert_called_once()
    refresh_app.release_browser_dialog.refresh.assert_called_once()


def test_party_import_report_summary_and_message_box(monkeypatch) -> None:
    report = PartyImportReport(
        format_name="csv",
        mode="dry_run",
        evaluated_mode="apply",
        passed=4,
        failed=1,
        skipped=2,
        warnings=["warning-a", "warning-b"],
        duplicates=["dupe"],
        unknown_fields=["custom_a", "custom_b"],
        would_create_parties=3,
        would_update_parties=2,
        would_set_owner=True,
        created_parties=[1],
        updated_parties=[2],
        owner_party_id=7,
    )

    summary = party_controller._party_import_review_summary(report)
    assert summary[:4] == [
        "Planned mode: apply",
        "Rows ready: 4",
        "Rows blocked: 1",
        "Rows skipped: 2",
    ]
    assert "Would create Parties: 3" in summary
    assert "Unmapped fields: custom_a, custom_b" in summary

    message_box = mock.Mock()
    monkeypatch.setattr(party_controller, "_message_box", lambda: message_box)
    party_controller._show_party_import_report(SimpleNamespace(), "/tmp/source.csv", report)
    message_box.information.assert_called_once()
    assert "Dry run validation mode" in message_box.information.call_args.args[2]


def test_import_party_exchange_file_inspection_cancel_and_dry_run_paths(monkeypatch, tmp_path):
    message_box = mock.Mock()
    monkeypatch.setattr(party_controller, "_message_box", lambda: message_box)

    app = SimpleNamespace(party_exchange_service=None)
    party_controller.import_party_exchange_file(app, "csv")
    message_box.warning.assert_called_once_with(app, "Import Parties", "Open a profile first.")

    submitted: dict[str, object] = {}
    file_dialog = mock.Mock(getOpenFileName=mock.Mock(return_value=("", "")))
    monkeypatch.setattr(party_controller, "_file_dialog", lambda: file_dialog)
    app = SimpleNamespace(
        party_exchange_service=object(),
        _submit_background_bundle_task=mock.Mock(
            side_effect=lambda **kwargs: submitted.update(kwargs)
        ),
    )
    party_controller.import_party_exchange_file(app, "csv")
    assert submitted == {}

    source = tmp_path / "parties.xlsx"
    file_dialog.getOpenFileName.return_value = (str(source), "")
    exchange_service = mock.Mock(
        inspect_xlsx=mock.Mock(return_value="xlsx-inspection"),
        inspect_json=mock.Mock(return_value="json-inspection"),
        supported_import_targets=mock.Mock(return_value=["legal_name"]),
        import_csv=mock.Mock(),
        import_xlsx=mock.Mock(),
        import_json=mock.Mock(),
    )
    app = SimpleNamespace(
        party_exchange_service=exchange_service,
        settings=object(),
        logger=mock.Mock(),
        _scaled_progress_callback=mock.Mock(side_effect=lambda callback, start, end: callback),
        _submit_background_bundle_task=mock.Mock(
            side_effect=lambda **kwargs: submitted.update(kwargs)
        ),
        _show_background_task_error=mock.Mock(),
        _open_import_review_dialog=mock.Mock(return_value=False),
        _party_import_review_summary=party_controller._party_import_review_summary,
        _advance_task_ui_progress=mock.Mock(),
        populate_all_comboboxes=mock.Mock(),
        _refresh_catalog_workspace_docks=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_party_import_report=mock.Mock(),
        conn=mock.Mock(commit=mock.Mock()),
        party_manager_panel=None,
    )

    party_controller.import_party_exchange_file(app, "xlsx")
    assert submitted["title"] == "Inspect Parties XLSX"
    ctx = SimpleNamespace(report_progress=mock.Mock(), raise_if_cancelled=mock.Mock())
    bundle = SimpleNamespace(party_exchange_service=exchange_service, history_manager=object())
    assert submitted["task_fn"](bundle, ctx) == "xlsx-inspection"
    exchange_service.inspect_xlsx.assert_called_once()

    class RejectedImportDialog:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(
        party_controller, "_party_import_dialog_class", lambda: RejectedImportDialog
    )
    submitted["on_success_after_cleanup"](
        PartyExchangeInspection(
            file_path=str(source),
            format_name="xlsx",
            headers=["legal_name"],
            preview_rows=[{"legal_name": "Rejected"}],
            suggested_mapping={"legal_name": "legal_name"},
        )
    )
    assert app._submit_background_bundle_task.call_count == 1

    dry_report = PartyImportReport(
        format_name="xlsx",
        mode="dry_run",
        passed=1,
        failed=0,
        skipped=0,
        warnings=[],
        duplicates=[],
        unknown_fields=[],
    )

    class AcceptedDryRunDialog:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return QDialog.Accepted

        def mapping(self):
            return {"legal_name": "legal_name"}

        def import_options(self):
            return PartyImportOptions(mode="dry_run")

        def resolved_csv_delimiter(self):
            return None

    exchange_service.import_xlsx.return_value = dry_report
    monkeypatch.setattr(
        party_controller, "_party_import_dialog_class", lambda: AcceptedDryRunDialog
    )
    submitted.clear()
    party_controller.import_party_exchange_file(app, "xlsx")
    submitted["on_success_after_cleanup"](
        PartyExchangeInspection(
            file_path=str(source),
            format_name="xlsx",
            headers=["legal_name"],
            preview_rows=[{"legal_name": "Accepted"}],
            suggested_mapping={"legal_name": "legal_name"},
        )
    )
    assert submitted["title"] == "Import Parties XLSX"
    report = submitted["task_fn"](bundle, ctx)
    assert report is dry_report
    exchange_service.import_xlsx.assert_called_once()
    submitted["on_success_before_cleanup"](dry_report, mock.Mock())
    app._advance_task_ui_progress.assert_called_with(
        mock.ANY,
        value=100,
        message="Party import validation complete.",
    )
    submitted["on_success_after_cleanup"](dry_report)
    app._show_party_import_report.assert_called_once_with(str(source), dry_report)

    submitted.clear()
    source_json = tmp_path / "parties.json"
    file_dialog.getOpenFileName.return_value = (str(source_json), "")
    party_controller.import_party_exchange_file(app, "json")
    assert submitted["task_fn"](bundle, ctx) == "json-inspection"
    exchange_service.inspect_json.assert_called_once()


def test_export_party_exchange_file_early_exits_and_background_worker(monkeypatch, tmp_path):
    message_box = mock.Mock()
    monkeypatch.setattr(party_controller, "_message_box", lambda: message_box)

    app = SimpleNamespace(party_exchange_service=None)
    party_controller.export_party_exchange_file(app, "csv", selected_only=False)
    message_box.warning.assert_called_once_with(app, "Export Parties", "Open a profile first.")

    message_box.reset_mock()
    app = SimpleNamespace(
        party_exchange_service=object(),
        _selected_party_manager_ids=mock.Mock(return_value=[]),
    )
    party_controller.export_party_exchange_file(app, "csv", selected_only=True)
    message_box.information.assert_called_once()

    target = tmp_path / "parties.csv"
    file_dialog = mock.Mock(getSaveFileName=mock.Mock(return_value=(str(target), "")))
    monkeypatch.setattr(party_controller, "_file_dialog", lambda: file_dialog)

    submitted: dict[str, object] = {}
    exchange_service = mock.Mock(export_csv=mock.Mock(return_value=4))

    def fake_history_action(**kwargs):
        return kwargs["mutation"]()

    monkeypatch.setattr(party_controller, "_run_file_history_action", fake_history_action)
    app = SimpleNamespace(
        party_exchange_service=exchange_service,
        exports_dir=tmp_path,
        _selected_party_manager_ids=mock.Mock(return_value=[]),
        _resolve_file_export_target=mock.Mock(return_value=target),
        _scaled_progress_callback=mock.Mock(side_effect=lambda callback, start, end: callback),
        _submit_background_bundle_task=mock.Mock(
            side_effect=lambda **kwargs: submitted.update(kwargs)
        ),
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        logger=mock.Mock(),
    )

    party_controller.export_party_exchange_file(app, "csv", selected_only=False)

    assert submitted["title"] == "Export Parties CSV"
    ctx = SimpleNamespace(report_progress=mock.Mock())
    bundle = SimpleNamespace(party_exchange_service=exchange_service, history_manager=object())
    assert submitted["task_fn"](bundle, ctx) == 4
    exchange_service.export_csv.assert_called_once_with(
        target,
        None,
        progress_callback=ctx.report_progress,
    )
    submitted["on_success_after_cleanup"](4)
    app._refresh_history_actions.assert_called_once_with()
    app._log_event.assert_called_once()
    app._audit.assert_called_once()
    app._audit_commit.assert_called_once_with()
    assert message_box.information.call_args.args[2].startswith("Exported 4 Parties")


def test_export_party_exchange_file_cancel_resolve_and_format_worker_paths(monkeypatch, tmp_path):
    message_box = mock.Mock()
    monkeypatch.setattr(party_controller, "_message_box", lambda: message_box)
    submitted: dict[str, object] = {}
    file_dialog = mock.Mock(getSaveFileName=mock.Mock(return_value=("", "")))
    monkeypatch.setattr(party_controller, "_file_dialog", lambda: file_dialog)
    exchange_service = mock.Mock(
        export_xlsx=mock.Mock(return_value=2),
        export_json=mock.Mock(return_value=3),
    )

    app = SimpleNamespace(
        party_exchange_service=exchange_service,
        exports_dir=tmp_path,
        _selected_party_manager_ids=mock.Mock(return_value=[4]),
        _resolve_file_export_target=mock.Mock(return_value=tmp_path / "out.xlsx"),
        _scaled_progress_callback=mock.Mock(side_effect=lambda callback, start, end: callback),
        _submit_background_bundle_task=mock.Mock(
            side_effect=lambda **kwargs: submitted.update(kwargs)
        ),
        _refresh_history_actions=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _show_background_task_error=mock.Mock(),
        logger=mock.Mock(),
    )

    party_controller.export_party_exchange_file(app, "xlsx", selected_only=False)
    assert submitted == {}

    file_dialog.getSaveFileName.return_value = (str(tmp_path / "bad.xlsx"), "")
    app._resolve_file_export_target.side_effect = ValueError("unsafe path")
    party_controller.export_party_exchange_file(app, "xlsx", selected_only=False)
    message_box.warning.assert_called_once_with(app, "Export Parties", "unsafe path")

    def fake_history_action(**kwargs):
        return kwargs["mutation"]()

    monkeypatch.setattr(party_controller, "_run_file_history_action", fake_history_action)
    app._resolve_file_export_target.side_effect = None
    app._resolve_file_export_target.return_value = tmp_path / "selected.xlsx"
    file_dialog.getSaveFileName.return_value = (str(tmp_path / "selected.xlsx"), "")
    submitted.clear()
    party_controller.export_party_exchange_file(app, "xlsx", selected_only=True, party_ids=[10, 11])
    ctx = SimpleNamespace(report_progress=mock.Mock())
    bundle = SimpleNamespace(party_exchange_service=exchange_service, history_manager=object())
    assert submitted["task_fn"](bundle, ctx) == 2
    exchange_service.export_xlsx.assert_called_once_with(
        tmp_path / "selected.xlsx",
        [10, 11],
        progress_callback=ctx.report_progress,
    )

    app._resolve_file_export_target.return_value = tmp_path / "all.json"
    file_dialog.getSaveFileName.return_value = (str(tmp_path / "all.json"), "")
    submitted.clear()
    party_controller.export_party_exchange_file(app, "json", selected_only=False)
    assert submitted["task_fn"](bundle, ctx) == 3
    exchange_service.export_json.assert_called_once_with(
        tmp_path / "all.json",
        None,
        progress_callback=ctx.report_progress,
    )

    app._resolve_file_export_target.return_value = tmp_path / "unsupported"
    file_dialog.getSaveFileName.return_value = (str(tmp_path / "unsupported"), "")
    submitted.clear()
    party_controller.export_party_exchange_file(app, "xml", selected_only=False)
    with pytest.raises(ValueError, match="Unsupported Party exchange format"):
        submitted["task_fn"](bundle, ctx)


def test_open_party_manager_requires_profile_and_routes_to_panel(monkeypatch) -> None:
    message_box = mock.Mock()
    monkeypatch.setattr(party_controller, "_message_box", lambda: message_box)

    no_service = SimpleNamespace(party_service=None)
    party_controller.open_party_manager(no_service)
    message_box.warning.assert_called_once_with(
        no_service,
        "Party Manager",
        "Open a profile first.",
    )
    message_box.reset_mock()

    class _FakePanel:
        def __init__(self) -> None:
            self.focus_calls: list[int | None] = []

        def focus_party(self, party_id: int | None) -> None:
            self.focus_calls.append(int(party_id) if party_id is not None else None)

    def _show_workspace_panel(_ensure_dock, panel_attr, legacy_attr, configure):
        assert panel_attr == "party_manager_panel"
        assert legacy_attr == "party_manager_dialog"
        panel = _FakePanel()
        configure(panel)
        return panel

    app = SimpleNamespace(
        party_service=object(),
        _ensure_party_manager_dock=lambda: object(),
        _show_workspace_panel=_show_workspace_panel,
    )
    panel = party_controller.open_party_manager(app, 7)
    assert isinstance(panel, _FakePanel)
    assert panel.focus_calls == [7]


def test_redirect_owner_registration_edit_to_party_manager(monkeypatch) -> None:
    message_box = mock.Mock()
    monkeypatch.setattr(party_controller, "_message_box", lambda: message_box)
    owner_calls: list[int | None] = []

    app = SimpleNamespace(
        party_service=object(),
        _current_owner_party_id=lambda: 11,
        open_party_manager=lambda party_id=None: owner_calls.append(party_id),
    )
    party_controller._redirect_owner_registration_edit_to_party_manager(app, "Owner Name")
    assert owner_calls == [11]
    message_box.information.assert_called_once()
    assert "Owner Name" in message_box.information.call_args.args[2]

    app._current_owner_party_id = lambda: None
    party_controller._redirect_owner_registration_edit_to_party_manager(app, "Owner Email")
    assert owner_calls == [11, None]
    assert len(message_box.information.call_args_list) == 2


def test_owner_party_bootstrap_scheduler_and_loop_assigns_once(monkeypatch) -> None:
    timer_calls: list[tuple[int, object]] = []
    dialog_invocations: list[int] = []

    class _FakeDialog:
        def __init__(self, **_kwargs) -> None:
            self.seq = _FakeDialog.seq
            _FakeDialog.seq += 1

        seq = 0

        def exec(self):
            if self.seq == 0:
                return QDialog.Rejected
            if self.seq == 1:
                return QDialog.Accepted
            return QDialog.Accepted

        def selected_party_id(self):
            return (None, None, 77)[self.seq]

    class _FakeTimer:
        def singleShot(self, ms, callback):
            timer_calls.append((ms, callback))

    assignments: list[int] = []
    current_owner_id = [None]

    def assign_owner_party(owner_party_id: int, record_history: bool = False) -> None:
        assignments.append(int(owner_party_id))
        current_owner_id[0] = int(owner_party_id)

    app = SimpleNamespace(
        party_service=object(),
        _current_owner_party_id=lambda: current_owner_id[0],
        _assign_owner_party=assign_owner_party,
        _owner_party_bootstrap_scheduled=False,
    )
    app._owner_bootstrap_required = lambda: party_controller._owner_bootstrap_required(app)

    def current_owner_record():
        owner_id = current_owner_id[0]
        return _party_record(owner_id) if owner_id is not None else None

    app._current_owner_party_record = current_owner_record

    monkeypatch.setattr(party_controller, "_timer", lambda: _FakeTimer())
    monkeypatch.setattr(party_controller, "_owner_bootstrap_dialog_class", lambda: _FakeDialog)

    party_controller._schedule_owner_party_bootstrap(app)
    party_controller._schedule_owner_party_bootstrap(app)
    assert app._owner_party_bootstrap_scheduled is True
    assert len(timer_calls) == 1

    dialog_invocations.clear()
    _FakeDialog.seq = 0
    app._owner_party_bootstrap_scheduled = False
    _FakeDialog.seq = 0
    party_controller._ensure_owner_party_bootstrap(app)
    assert assignments == [77]

    app._owner_party_bootstrap_scheduled = False
    party_controller._ensure_owner_party_bootstrap(app)
    assert assignments == [77]
