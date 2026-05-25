from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import QComboBox

from isrc_manager.parties import PartyImportReport, PartyRecord
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
