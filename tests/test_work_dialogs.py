import unittest
from types import SimpleNamespace
from unittest import mock

try:
    from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QMessageBox
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QComboBox = None
    QDialog = None
    QMessageBox = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.parties import PartyPayload, PartyRecord
from isrc_manager.selection_scope import TrackChoice
from isrc_manager.works.dialogs import WorkBrowserPanel, WorkEditorDialog
from isrc_manager.works.models import (
    WorkContributorPayload,
    WorkContributorRecord,
    WorkDetail,
    WorkPayload,
    WorkRecord,
)


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
    iswc: str | None = None,
    work_status: str | None = "idea",
    track_count: int = 0,
    contributor_count: int = 0,
) -> WorkRecord:
    return WorkRecord(
        id=work_id,
        title=title,
        alternate_titles=[],
        version_subtitle=None,
        language=None,
        lyrics_flag=False,
        instrumental_flag=False,
        genre_notes=None,
        iswc=iswc,
        registration_number=None,
        work_status=work_status,
        metadata_complete=False,
        contract_signed=False,
        rights_verified=False,
        notes=None,
        profile_name=None,
        created_at=None,
        updated_at=None,
        track_count=track_count,
        contributor_count=contributor_count,
    )


class _FakePartyService:
    def __init__(self, parties=()):
        self.parties = {int(party.id): party for party in parties}
        self.list_error: Exception | None = None
        self.create_error: Exception | None = None
        self.update_error: Exception | None = None
        self.create_calls: list[object] = []
        self.update_calls: list[tuple[int, object]] = []
        self.next_id = max(self.parties, default=40) + 1

    def list_parties(self):
        if self.list_error is not None:
            raise self.list_error
        return list(self.parties.values())

    def create_party(self, payload):
        self.create_calls.append(payload)
        if self.create_error is not None:
            raise self.create_error
        party_id = self.next_id
        self.next_id += 1
        self.parties[party_id] = _party_record(
            party_id,
            legal_name=getattr(payload, "legal_name", "") or f"Party {party_id}",
            display_name=getattr(payload, "display_name", None)
            or getattr(payload, "legal_name", None),
        )
        return party_id

    def fetch_party(self, party_id: int):
        return self.parties.get(int(party_id))

    def update_party(self, party_id: int, payload):
        self.update_calls.append((int(party_id), payload))
        if self.update_error is not None:
            raise self.update_error
        current = self.parties[int(party_id)]
        self.parties[int(party_id)] = _party_record(
            int(party_id),
            legal_name=getattr(payload, "legal_name", current.legal_name),
            display_name=getattr(payload, "display_name", current.display_name),
        )


class _FakeWorkService:
    def __init__(self, *, party_service=None):
        self.party_service = party_service
        self.rows = [
            _work_record(
                101,
                "Northern Lights",
                iswc="T-100.200.300-4",
                work_status="contract_pending",
                track_count=2,
                contributor_count=3,
            ),
            _work_record(202, "Sea Signal", track_count=1, contributor_count=1),
        ]
        self.details = {
            101: WorkDetail(
                work=self.rows[0],
                contributors=[
                    WorkContributorRecord(
                        id=1,
                        work_id=101,
                        party_id=7,
                        display_name="Writer Seven",
                        role="songwriter",
                        share_percent=50.0,
                        role_share_percent=100.0,
                        notes="",
                    )
                ],
                track_ids=[7, 8],
            )
        }
        self.searches: list[str] = []

    def list_works(self, *, search_text: str = ""):
        self.searches.append(search_text)
        return [row for row in self.rows if search_text.casefold() in row.title.casefold()]

    def fetch_work_detail(self, work_id: int):
        return self.details.get(int(work_id))


class WorkDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def _track_title(self, track_id: int) -> str:
        return {7: "Northern Lights", 8: "Sea Signal", 9: "Archive Take"}.get(
            int(track_id),
            f"Track {track_id}",
        )

    def test_editor_payload_splits_parties_and_linked_tracks_are_normalized(self):
        party_service = _FakePartyService(
            [
                _party_record(7, legal_name="Alex Writer Legal", display_name="Alex Writer"),
                _party_record(8, legal_name="Beta Songs", company_name="Beta Songs BV"),
            ]
        )
        work_service = SimpleNamespace(party_service=party_service)
        dialog = WorkEditorDialog(
            work_service=work_service,
            track_title_resolver=self._track_title,
            selected_track_ids_provider=lambda: [7, 7, 8],
            parent=None,
        )
        try:
            self.assertEqual(
                WorkEditorDialog._contributor_party_primary_label(_party_record(99, legal_name="")),
                "Party #99",
            )
            self.assertEqual(
                WorkEditorDialog._contributor_party_choice_label(
                    _party_record(
                        7,
                        legal_name="Alex Writer Legal",
                        display_name="Alex Writer",
                    )
                ),
                "Alex Writer (Alex Writer Legal)",
            )

            with mock.patch.object(QMessageBox, "information", return_value=None) as information:
                dialog._equal_split_contributors((2, 3))
            information.assert_called_once()

            dialog.title_edit.setText("  Northern Lights  ")
            dialog.alt_titles_edit.setPlainText("\nAurora Theme\n \nSky Signal\n")
            dialog.subtitle_edit.setText("Radio Edit")
            dialog.language_edit.setText("en")
            dialog.genre_edit.setText("Synth Pop")
            dialog.iswc_edit.setText("T-100.200.300-4")
            dialog.registration_edit.setText("REG-77")
            dialog.status_combo.setCurrentText("Contract Pending")
            dialog.lyrics_checkbox.setChecked(True)
            dialog.metadata_checkbox.setChecked(True)
            dialog.contract_checkbox.setChecked(True)
            dialog.rights_checkbox.setChecked(True)
            dialog.notes_edit.setPlainText("Ready for publisher review.")

            dialog._add_contributor_row(
                WorkContributorPayload(
                    role="composer",
                    name="Legacy Linked Writer",
                    party_id=777,
                )
            )
            fallback_combo = dialog.contributors_table.cellWidget(0, 0)
            self.assertIsInstance(fallback_combo, QComboBox)
            self.assertEqual(fallback_combo.currentData(), 777)

            dialog._add_contributor_row()
            typed_combo = dialog.contributors_table.cellWidget(1, 0)
            self.assertIsInstance(typed_combo, QComboBox)
            typed_combo.setEditText("Typed Writer")
            role_combo = dialog.contributors_table.cellWidget(1, 1)
            self.assertIsInstance(role_combo, QComboBox)
            role_combo.setCurrentText("Publisher")

            dialog._equal_split_contributors((2, 3))
            self.assertEqual(dialog.contributors_table.item(0, 2).text(), "50")
            self.assertEqual(dialog.contributors_table.item(1, 3).text(), "50")

            dialog._add_selected_tracks()
            self.assertEqual(dialog.track_table.rowCount(), 2)
            dialog.track_table.selectRow(1)
            dialog._remove_track_rows()
            self.assertEqual(dialog.track_table.rowCount(), 1)
            dialog._append_track_row(8)

            payload = dialog.payload()
            self.assertEqual(payload.title, "Northern Lights")
            self.assertEqual(payload.alternate_titles, ["Aurora Theme", "Sky Signal"])
            self.assertEqual(payload.version_subtitle, "Radio Edit")
            self.assertEqual(payload.language, "en")
            self.assertTrue(payload.lyrics_flag)
            self.assertTrue(payload.metadata_complete)
            self.assertTrue(payload.contract_signed)
            self.assertTrue(payload.rights_verified)
            self.assertEqual(payload.genre_notes, "Synth Pop")
            self.assertEqual(payload.iswc, "T-100.200.300-4")
            self.assertEqual(payload.registration_number, "REG-77")
            self.assertEqual(payload.work_status, "contract_pending")
            self.assertEqual(payload.notes, "Ready for publisher review.")
            self.assertEqual(payload.track_ids, [7, 8])
            self.assertEqual(
                [(item.name, item.role, item.party_id) for item in payload.contributors],
                [
                    ("Legacy Linked Writer", "composer", 777),
                    ("Typed Writer", "publisher", None),
                ],
            )
            self.assertEqual([item.share_percent for item in payload.contributors], [50.0, 50.0])
        finally:
            dialog.close()

    def test_editor_contributor_party_create_edit_and_failure_paths_are_user_visible(self):
        party_service = _FakePartyService(
            [_party_record(7, legal_name="Alex Writer Legal", display_name="Alex Writer")]
        )
        work_service = SimpleNamespace(party_service=party_service)
        dialog = WorkEditorDialog(
            work_service=work_service,
            track_title_resolver=self._track_title,
            selected_track_ids_provider=lambda: [],
            parent=None,
        )
        try:
            rejected_editor = mock.Mock()
            rejected_editor.exec.return_value = QDialog.Rejected
            with mock.patch(
                "isrc_manager.works.dialogs.PartyEditorDialog",
                return_value=rejected_editor,
            ):
                dialog._create_contributor_party()
            self.assertEqual(dialog.contributors_table.rowCount(), 0)

            accepted_editor = mock.Mock()
            accepted_editor.exec.return_value = QDialog.Accepted
            accepted_editor.payload.return_value = PartyPayload(
                legal_name="New Writer Legal",
                display_name="New Writer",
            )
            with mock.patch(
                "isrc_manager.works.dialogs.PartyEditorDialog",
                return_value=accepted_editor,
            ):
                dialog._create_contributor_party()
            self.assertEqual(dialog.contributors_table.rowCount(), 1)
            combo = dialog.contributors_table.cellWidget(0, 0)
            self.assertIsInstance(combo, QComboBox)
            created_id = party_service.create_calls and max(party_service.parties)
            self.assertEqual(combo.currentData(), created_id)

            party_service.create_error = ValueError("party create failed")
            with (
                mock.patch(
                    "isrc_manager.works.dialogs.PartyEditorDialog",
                    return_value=accepted_editor,
                ),
                mock.patch.object(QMessageBox, "warning", return_value=None) as warning,
            ):
                dialog._create_contributor_party()
            warning.assert_called_once()
            self.assertIn("party create failed", warning.call_args.args[2])
            party_service.create_error = None

            typed_combo = dialog.contributors_table.cellWidget(0, 0)
            self.assertIsInstance(typed_combo, QComboBox)
            typed_combo.setCurrentIndex(-1)
            typed_combo.setEditText("Unlinked Writer")
            with mock.patch.object(QMessageBox, "information", return_value=None) as information:
                dialog._edit_contributor_party()
            information.assert_called_once()

            dialog._add_contributor_row(
                WorkContributorPayload(role="songwriter", name="Missing Party", party_id=999)
            )
            dialog.contributors_table.selectRow(1)
            with mock.patch.object(QMessageBox, "warning", return_value=None) as warning:
                dialog._edit_contributor_party()
            warning.assert_called_once()
            self.assertIn("could not be loaded", warning.call_args.args[2])

            dialog.contributors_table.selectRow(0)
            real_combo = dialog.contributors_table.cellWidget(0, 0)
            self.assertIsInstance(real_combo, QComboBox)
            real_combo.setCurrentIndex(real_combo.findData(7))
            party_service.update_error = ValueError("party update failed")
            with (
                mock.patch(
                    "isrc_manager.works.dialogs.PartyEditorDialog",
                    return_value=accepted_editor,
                ),
                mock.patch.object(QMessageBox, "warning", return_value=None) as warning,
            ):
                dialog._edit_contributor_party()
            warning.assert_called_once()
            self.assertIn("party update failed", warning.call_args.args[2])

            party_service.update_error = None
            with mock.patch(
                "isrc_manager.works.dialogs.PartyEditorDialog",
                return_value=accepted_editor,
            ):
                dialog._edit_contributor_party()
            self.assertEqual(party_service.update_calls[-1][0], 7)
        finally:
            dialog.close()

    def test_browser_panel_scope_selection_and_work_action_routing(self):
        service = _FakeWorkService()
        panel = WorkBrowserPanel(
            work_service_provider=lambda: service,
            track_title_resolver=self._track_title,
            selected_track_ids_provider=lambda: [7, 8],
            track_choice_provider=lambda: [
                {"track_id": "9", "title": "", "subtitle": "Alt"},
                {"track_id": "9", "title": "Duplicate", "subtitle": ""},
                {"track_id": "bad", "title": "Ignored"},
                TrackChoice(track_id=10, title="Tenth Track", subtitle=""),
            ],
            parent=None,
        )
        try:
            self.assertEqual(panel.table.rowCount(), 2)
            self.assertEqual(service.searches[-1], "")
            panel.search_edit.setText("Sea")
            self.app.processEvents()
            self.assertEqual(panel.table.rowCount(), 1)
            self.assertEqual(service.searches[-1], "Sea")
            panel.search_edit.clear()
            self.app.processEvents()

            choices = panel._available_track_choices()
            self.assertEqual([choice.track_id for choice in choices], [9, 10])
            self.assertEqual(choices[0].title, "Archive Take")

            panel.set_selection_override_track_ids(["9", 9, 0, "bad", 10])
            self.assertEqual(panel.selected_track_ids(), [9, 10])
            self.assertIn("Pinned chooser override", panel.selection_banner.scope_label.text())
            self.assertFalse(panel.clear_scope_button.isHidden())
            self.assertTrue(panel.clear_scope_button.isEnabled())
            panel._clear_selection_override()
            self.assertEqual(panel.selected_track_ids(), [7, 8])

            rejected_chooser = mock.Mock()
            rejected_chooser.exec.return_value = QDialog.Rejected
            with mock.patch(
                "isrc_manager.works.dialogs.TrackSelectionChooserDialog",
                return_value=rejected_chooser,
            ):
                panel._choose_tracks()
            self.assertEqual(panel.selected_track_ids(), [7, 8])

            accepted_chooser = mock.Mock()
            accepted_chooser.exec.return_value = QDialog.Accepted
            accepted_chooser.selected_track_ids.return_value = [10]
            with mock.patch(
                "isrc_manager.works.dialogs.TrackSelectionChooserDialog",
                return_value=accepted_chooser,
            ):
                panel._choose_tracks()
            self.assertEqual(panel.selected_track_ids(), [10])

            emitted: dict[str, list[object]] = {
                "child": [],
                "album": [],
                "duplicate": [],
                "link": [],
                "delete": [],
                "filter": [],
            }
            panel.create_child_track_requested.connect(emitted["child"].append)
            panel.create_album_for_work_requested.connect(emitted["album"].append)
            panel.duplicate_requested.connect(emitted["duplicate"].append)
            panel.link_tracks_requested.connect(
                lambda work_id, track_ids: emitted["link"].append((work_id, list(track_ids)))
            )
            panel.delete_requested.connect(emitted["delete"].append)
            panel.filter_requested.connect(
                lambda track_ids: emitted["filter"].append(list(track_ids))
            )

            panel.table.selectRow(0)
            self.assertEqual(panel.selected_work_id(), 101)
            panel.create_child_track()
            panel.create_album_for_work()
            panel.duplicate_selected()
            panel.link_selected_tracks()
            panel.filter_by_work_tracks()
            self.assertEqual(emitted["child"], [101])
            self.assertEqual(emitted["album"], [101])
            self.assertEqual(emitted["duplicate"], [101])
            self.assertEqual(emitted["link"], [(101, [10])])
            self.assertEqual(emitted["filter"], [[7, 8]])

            with mock.patch(
                "isrc_manager.works.dialogs._confirm_destructive_action",
                return_value=False,
            ):
                panel.delete_selected()
            self.assertEqual(emitted["delete"], [])
            with mock.patch(
                "isrc_manager.works.dialogs._confirm_destructive_action",
                return_value=True,
            ):
                panel.delete_selected()
            self.assertEqual(emitted["delete"], [101])

            service.details[101] = None
            panel.filter_by_work_tracks()
            self.assertEqual(emitted["filter"], [[7, 8]])
        finally:
            panel.close()

    def test_browser_panel_missing_service_selection_guards_and_editor_routing(self):
        service = _FakeWorkService()
        panel = WorkBrowserPanel(
            work_service_provider=lambda: service,
            track_title_resolver=self._track_title,
            selected_track_ids_provider=lambda: [],
            parent=None,
        )
        try:
            with mock.patch.object(QMessageBox, "information", return_value=None) as information:
                panel.create_child_track()
                panel.create_album_for_work()
                panel.edit_selected()
                panel.duplicate_selected()
                panel.link_selected_tracks()
                panel.delete_selected()
                panel.filter_by_work_tracks()
            self.assertGreaterEqual(information.call_count, 7)

            created_payloads: list[WorkPayload] = []
            updated_payloads: list[tuple[int, WorkPayload]] = []
            panel.create_requested.connect(created_payloads.append)
            panel.update_requested.connect(
                lambda work_id, payload: updated_payloads.append((work_id, payload))
            )
            payload = WorkPayload(title="Accepted Work", track_ids=[7])

            accepted_dialog = mock.Mock()
            accepted_dialog.exec.return_value = QDialog.Accepted
            accepted_dialog.payload.return_value = payload
            rejected_dialog = mock.Mock()
            rejected_dialog.exec.return_value = QDialog.Rejected

            with mock.patch.object(panel, "_edit_dialog_for", return_value=rejected_dialog):
                panel.create_work()
            self.assertEqual(created_payloads, [])
            with mock.patch.object(panel, "_edit_dialog_for", return_value=accepted_dialog):
                panel.create_work()
            self.assertEqual(created_payloads, [payload])

            panel.table.selectRow(0)
            with mock.patch.object(panel, "_edit_dialog_for", return_value=rejected_dialog):
                panel.edit_selected()
            self.assertEqual(updated_payloads, [])
            with mock.patch.object(panel, "_edit_dialog_for", return_value=accepted_dialog):
                panel.edit_selected()
            self.assertEqual(updated_payloads, [(101, payload)])

            panel.set_selection_override_track_ids([])
            with mock.patch.object(QMessageBox, "information", return_value=None) as information:
                panel.link_selected_tracks()
            information.assert_called_once()
            self.assertIn("Select one or more tracks", information.call_args.args[2])
        finally:
            panel.close()

        no_service_panel = WorkBrowserPanel(
            work_service_provider=lambda: None,
            track_title_resolver=self._track_title,
            selected_track_ids_provider=lambda: (_ for _ in ()).throw(
                RuntimeError("selection unavailable")
            ),
            parent=None,
        )
        try:
            self.assertEqual(no_service_panel.table.rowCount(), 0)
            self.assertEqual(no_service_panel.selected_track_ids(), [])
            with mock.patch.object(QMessageBox, "warning", return_value=None) as warning:
                no_service_panel.create_work()
                no_service_panel.create_child_track()
                no_service_panel.create_album_for_work()
                no_service_panel.edit_selected()
                no_service_panel.duplicate_selected()
                no_service_panel.link_selected_tracks()
                no_service_panel.delete_selected()
                no_service_panel.filter_by_work_tracks()
            self.assertEqual(warning.call_count, 8)
        finally:
            no_service_panel.close()


if __name__ == "__main__":
    unittest.main()
