"""Additional behavioral coverage for the Work Manager dialogs."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QTableWidgetItem

from isrc_manager.parties import PartyRecord
from isrc_manager.works.dialogs import WorkBrowserDialog, WorkBrowserPanel, WorkEditorDialog
from isrc_manager.works.models import (
    WorkContributorPayload,
    WorkContributorRecord,
    WorkDetail,
    WorkRecord,
)
from tests.qt_test_helpers import require_qapplication


def _party_record(
    party_id: int,
    *,
    legal_name: str = "",
    display_name: str | None = None,
    artist_name: str | None = None,
    company_name: str | None = None,
) -> PartyRecord:
    return PartyRecord(
        id=party_id,
        legal_name=legal_name,
        display_name=display_name,
        artist_name=artist_name,
        company_name=company_name,
        first_name=None,
        middle_name=None,
        last_name=None,
        party_type="person",
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
    )


def _work_record(
    work_id: int,
    title: str,
    *,
    alternate_titles: list[str] | None = None,
    version_subtitle: str | None = None,
    language: str | None = None,
    lyrics_flag: bool = False,
    instrumental_flag: bool = False,
    genre_notes: str | None = None,
    iswc: str | None = None,
    registration_number: str | None = None,
    work_status: str | None = None,
    metadata_complete: bool = False,
    contract_signed: bool = False,
    rights_verified: bool = False,
    notes: str | None = None,
    track_count: int = 0,
    contributor_count: int = 0,
) -> WorkRecord:
    return WorkRecord(
        id=work_id,
        title=title,
        alternate_titles=alternate_titles or [],
        version_subtitle=version_subtitle,
        language=language,
        lyrics_flag=lyrics_flag,
        instrumental_flag=instrumental_flag,
        genre_notes=genre_notes,
        iswc=iswc,
        registration_number=registration_number,
        work_status=work_status,
        metadata_complete=metadata_complete,
        contract_signed=contract_signed,
        rights_verified=rights_verified,
        notes=notes,
        profile_name=None,
        created_at=None,
        updated_at=None,
        track_count=track_count,
        contributor_count=contributor_count,
    )


def _track_title(track_id: int) -> str:
    return {
        1: "Loaded Master",
        2: "Loaded Alt Mix",
        4: "Draft Recording",
        5: "Acoustic Draft",
        9: "Catalog Selection",
        12: "Linked Scope",
    }.get(int(track_id), f"Track {track_id}")


class _FailingPartyService:
    def list_parties(self):
        raise RuntimeError("party authority unavailable")


class _PartyService:
    def __init__(self, parties: tuple[PartyRecord, ...] = ()) -> None:
        self.parties = {int(party.id): party for party in parties}

    def list_parties(self):
        return list(self.parties.values())

    def fetch_party(self, party_id: int):
        return self.parties.get(int(party_id))


class _WorkService:
    def __init__(self, *, party_service=None) -> None:
        self.party_service = party_service
        self.searches: list[str] = []
        self.rows = [
            _work_record(
                101,
                "Loaded Work",
                iswc="T-111.222.333-4",
                work_status="metadata_incomplete",
                track_count=2,
                contributor_count=1,
            )
        ]
        self.details = {
            101: WorkDetail(
                work=self.rows[0],
                contributors=[
                    WorkContributorRecord(
                        id=501,
                        work_id=101,
                        party_id=7,
                        display_name="Existing Writer",
                        role="composer",
                        share_percent=60.0,
                        role_share_percent=None,
                        notes="Lead writer",
                    )
                ],
                track_ids=[1, 2],
            )
        }

    def list_works(self, *, search_text: str = ""):
        self.searches.append(search_text)
        return list(self.rows)

    def fetch_work_detail(self, work_id: int):
        return self.details.get(int(work_id))


def test_editor_loads_existing_work_rejects_cancel_and_preserves_loaded_payload() -> None:
    require_qapplication()
    work = _work_record(
        77,
        "Loaded Work",
        alternate_titles=["Earlier Title", "Working Title"],
        version_subtitle="Live Version",
        language="nl",
        lyrics_flag=True,
        instrumental_flag=True,
        genre_notes="Art pop",
        iswc="T-123.456.789-0",
        registration_number="REG-77",
        work_status="metadata_incomplete",
        metadata_complete=True,
        contract_signed=True,
        rights_verified=True,
        notes="Imported from publisher sheet.",
    )
    dialog = WorkEditorDialog(
        work_service=SimpleNamespace(party_service=_FailingPartyService()),
        track_title_resolver=_track_title,
        selected_track_ids_provider=lambda: [2],
        work=work,
        contributors=[
            WorkContributorPayload(
                role="lyricist",
                name="Fallback Writer",
                share_percent=None,
                role_share_percent=12.5,
                party_id=42,
            )
        ],
        track_ids=[1, 1, 2],
        parent=None,
    )
    try:
        assert dialog.windowTitle() == "Edit Work"
        assert dialog.title_edit.text() == "Loaded Work"
        assert dialog.alt_titles_edit.toPlainText() == "Earlier Title\nWorking Title"
        assert dialog.status_combo.currentText() == "Metadata Incomplete"
        assert dialog.lyrics_checkbox.isChecked()
        assert dialog.instrumental_checkbox.isChecked()
        assert dialog.metadata_checkbox.isChecked()
        assert dialog.contract_checkbox.isChecked()
        assert dialog.rights_checkbox.isChecked()
        assert dialog.track_table.rowCount() == 2

        combo = dialog.contributors_table.cellWidget(0, 0)
        assert isinstance(combo, QComboBox)
        assert combo.currentData() == 42
        assert combo.currentText() == "Fallback Writer"

        payload = dialog.payload()
        assert payload.title == "Loaded Work"
        assert payload.alternate_titles == ["Earlier Title", "Working Title"]
        assert payload.version_subtitle == "Live Version"
        assert payload.language == "nl"
        assert payload.genre_notes == "Art pop"
        assert payload.iswc == "T-123.456.789-0"
        assert payload.registration_number == "REG-77"
        assert payload.work_status == "metadata_incomplete"
        assert payload.notes == "Imported from publisher sheet."
        assert payload.track_ids == [1, 2]
        assert len(payload.contributors) == 1
        assert payload.contributors[0].name == "Fallback Writer"
        assert payload.contributors[0].party_id == 42
        assert payload.contributors[0].share_percent is None
        assert payload.contributors[0].role_share_percent == 12.5

        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        buttons.rejected.emit()
        assert dialog.result() == QDialog.Rejected
    finally:
        dialog.close()


def test_editor_accept_button_trims_required_and_identifier_payload_fields() -> None:
    require_qapplication()
    dialog = WorkEditorDialog(
        work_service=SimpleNamespace(),
        track_title_resolver=_track_title,
        selected_track_ids_provider=lambda: [4, 4, 5],
        parent=None,
    )
    try:
        assert not dialog.new_contributor_party_button.isEnabled()
        assert not dialog.edit_contributor_party_button.isEnabled()
        dialog._create_contributor_party()
        dialog._edit_contributor_party()
        assert dialog.contributors_table.rowCount() == 0

        dialog.title_edit.setText("  New Required Title  ")
        dialog.alt_titles_edit.setPlainText("\n Working Name \n\n Alternate Name\n")
        dialog.iswc_edit.setText("  T-000.111.222-3  ")
        dialog.registration_edit.setText("  REG-NEW  ")
        dialog.status_combo.setCurrentText("Rights Verified")
        dialog.notes_edit.setPlainText("  Ready after identifier review.  ")
        dialog._add_contributor_row()
        identity_combo = dialog.contributors_table.cellWidget(0, 0)
        assert isinstance(identity_combo, QComboBox)
        identity_combo.setEditText("  Typed Writer  ")
        role_combo = dialog.contributors_table.cellWidget(0, 1)
        assert isinstance(role_combo, QComboBox)
        role_combo.setCurrentText("Subpublisher")
        dialog.contributors_table.item(0, 2).setText("")
        dialog.contributors_table.item(0, 3).setText("66.6")
        dialog._add_contributor_row()

        dialog._add_selected_tracks()
        dialog._append_track_row(5)
        assert dialog.track_table.rowCount() == 2

        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        buttons.accepted.emit()
        assert dialog.result() == QDialog.Accepted

        payload = dialog.payload()
        assert payload.title == "New Required Title"
        assert payload.alternate_titles == ["Working Name", "Alternate Name"]
        assert payload.iswc == "T-000.111.222-3"
        assert payload.registration_number == "REG-NEW"
        assert payload.work_status == "rights_verified"
        assert payload.notes == "Ready after identifier review."
        assert payload.track_ids == [4, 5]
        assert [(item.name, item.role) for item in payload.contributors] == [
            ("Typed Writer", "subpublisher")
        ]
        assert payload.contributors[0].share_percent is None
        assert payload.contributors[0].role_share_percent == 66.6
    finally:
        dialog.close()


def test_editor_equal_split_distributes_remainder_and_remove_no_selection_is_noop() -> None:
    require_qapplication()
    dialog = WorkEditorDialog(
        work_service=SimpleNamespace(),
        track_title_resolver=_track_title,
        selected_track_ids_provider=lambda: [],
        parent=None,
    )
    try:
        for name in ("Writer A", "Writer B", "Writer C"):
            dialog._add_contributor_row()
            combo = dialog.contributors_table.cellWidget(
                dialog.contributors_table.rowCount() - 1,
                0,
            )
            assert isinstance(combo, QComboBox)
            combo.setEditText(name)

        dialog._equal_split_contributors((2, 3))
        assert [dialog.contributors_table.item(row, 2).text() for row in range(3)] == [
            "33.33",
            "33.33",
            "33.34",
        ]
        assert [dialog.contributors_table.item(row, 3).text() for row in range(3)] == [
            "33.33",
            "33.33",
            "33.34",
        ]

        dialog.contributors_table.clearSelection()
        dialog._remove_contributor_rows()
        assert dialog.contributors_table.rowCount() == 3

        dialog.contributors_table.selectRow(1)
        dialog._remove_contributor_rows()
        assert dialog.contributors_table.rowCount() == 2
        remaining_names = []
        for row in range(dialog.contributors_table.rowCount()):
            combo = dialog.contributors_table.cellWidget(row, 0)
            assert isinstance(combo, QComboBox)
            remaining_names.append(combo.currentText())
        assert remaining_names == ["Writer A", "Writer C"]
    finally:
        dialog.close()


def test_browser_edit_dialog_for_builds_loaded_new_and_missing_linked_data_dialogs() -> None:
    require_qapplication()
    service = _WorkService(
        party_service=_PartyService((_party_record(7, legal_name="Existing Writer"),))
    )
    panel = WorkBrowserPanel(
        work_service_provider=lambda: service,
        track_title_resolver=_track_title,
        selected_track_ids_provider=lambda: [9],
        parent=None,
    )
    loaded_editor = None
    missing_editor = None
    new_editor = None
    try:
        loaded_editor = panel._edit_dialog_for(101)
        assert loaded_editor.windowTitle() == "Edit Work"
        assert loaded_editor.title_edit.text() == "Loaded Work"
        assert loaded_editor.track_table.rowCount() == 2
        assert loaded_editor.contributors_table.rowCount() == 1
        loaded_combo = loaded_editor.contributors_table.cellWidget(0, 0)
        assert isinstance(loaded_combo, QComboBox)
        assert loaded_combo.currentData() == 7

        missing_editor = panel._edit_dialog_for(999)
        assert missing_editor.windowTitle() == "Create Work"
        assert missing_editor.title_edit.text() == ""
        assert missing_editor.track_table.rowCount() == 0
        assert missing_editor.contributors_table.rowCount() == 0

        new_editor = panel._edit_dialog_for()
        assert new_editor.windowTitle() == "Create Work"
        assert new_editor.track_table.rowCount() == 1
        assert new_editor.track_table.item(0, 0).text() == "9"
    finally:
        for editor in (loaded_editor, missing_editor, new_editor):
            if editor is not None:
                editor.close()
        panel.close()


def test_browser_scope_provider_failures_linked_id_changes_and_bad_table_ids() -> None:
    require_qapplication()
    service = _WorkService()
    panel = WorkBrowserPanel(
        work_service_provider=lambda: service,
        track_title_resolver=_track_title,
        selected_track_ids_provider=lambda: (_ for _ in ()).throw(
            RuntimeError("selection unavailable")
        ),
        track_choice_provider=lambda: (_ for _ in ()).throw(RuntimeError("choices unavailable")),
        parent=None,
    )
    try:
        assert panel.selected_track_ids() == []
        assert panel._available_track_choices() == []

        panel.set_selection_override_track_ids([12, "12", 0, -1, "bad", None, 9])
        assert panel.selected_track_ids() == [12, 9]
        assert not panel.clear_scope_button.isHidden()
        panel._use_current_selection()
        assert panel.selected_track_ids() == []
        assert panel.clear_scope_button.isHidden()

        previous_refreshes = len(service.searches)
        panel.set_linked_track_id("12")
        assert panel.linked_track_id == 12
        assert len(service.searches) == previous_refreshes + 1
        panel.set_linked_track_id(None)
        assert panel.linked_track_id is None

        panel.table.setItem(0, 0, QTableWidgetItem("not-a-work-id"))
        panel.focus_work(101)
        panel.table.selectRow(0)
        panel.table.takeItem(0, 0)
        assert panel.selected_work_id() is None
    finally:
        panel.close()


def test_browser_dialog_forwards_panel_signals_and_delegates_attributes() -> None:
    require_qapplication()
    service = _WorkService()
    dialog = WorkBrowserDialog(
        work_service=service,
        track_title_resolver=_track_title,
        selected_track_ids_provider=lambda: [9],
        linked_track_id=9,
        parent=None,
    )
    try:
        forwarded: dict[str, list[object]] = {
            "filter": [],
            "create": [],
            "child": [],
            "album": [],
            "update": [],
            "duplicate": [],
            "link": [],
            "delete": [],
        }
        dialog.filter_requested.connect(lambda track_ids: forwarded["filter"].append(track_ids))
        dialog.create_requested.connect(lambda payload: forwarded["create"].append(payload))
        dialog.create_child_track_requested.connect(
            lambda work_id: forwarded["child"].append(work_id)
        )
        dialog.create_album_for_work_requested.connect(
            lambda work_id: forwarded["album"].append(work_id)
        )
        dialog.update_requested.connect(
            lambda work_id, payload: forwarded["update"].append((work_id, payload))
        )
        dialog.duplicate_requested.connect(lambda work_id: forwarded["duplicate"].append(work_id))
        dialog.link_tracks_requested.connect(
            lambda work_id, track_ids: forwarded["link"].append((work_id, track_ids))
        )
        dialog.delete_requested.connect(lambda work_id: forwarded["delete"].append(work_id))

        payload = object()
        dialog.panel.filter_requested.emit([1, 2])
        dialog.panel.create_requested.emit(payload)
        dialog.panel.create_child_track_requested.emit(101)
        dialog.panel.create_album_for_work_requested.emit(101)
        dialog.panel.update_requested.emit(101, payload)
        dialog.panel.duplicate_requested.emit(101)
        dialog.panel.link_tracks_requested.emit(101, [9])
        dialog.panel.delete_requested.emit(101)

        assert forwarded["filter"] == [[1, 2]]
        assert forwarded["create"] == [payload]
        assert forwarded["child"] == [101]
        assert forwarded["album"] == [101]
        assert forwarded["update"] == [(101, payload)]
        assert forwarded["duplicate"] == [101]
        assert forwarded["link"] == [(101, [9])]
        assert forwarded["delete"] == [101]

        assert dialog.selected_work_id() == dialog.panel.selected_work_id()
        try:
            getattr(dialog, "missing_work_manager_attribute")
        except AttributeError as exc:
            assert str(exc) == "missing_work_manager_attribute"
        else:
            raise AssertionError("missing attributes must not be silently delegated")
    finally:
        dialog.close()
