import unittest
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtWidgets import QDialog, QMessageBox

    from isrc_manager.releases.dialogs import ReleaseEditorDialog
    from isrc_manager.releases.models import ReleaseValidationIssue
    from isrc_manager.search.dialogs import GlobalSearchDialog
    from isrc_manager.search.models import (
        GlobalSearchResult,
        RelationshipSection,
        SavedSearchRecord,
    )
    from isrc_manager.works.dialogs import WorkBrowserDialog
    from isrc_manager.works.models import WorkContributorRecord, WorkDetail, WorkRecord
except Exception as exc:  # pragma: no cover - environment-specific fallback
    DIALOG_IMPORT_ERROR = exc
else:
    DIALOG_IMPORT_ERROR = None


class _SearchService:
    def __init__(self):
        self.saved = [
            SavedSearchRecord(id=1, name="Tracks", query_text="orbit", entity_types=["track"])
        ]
        self.results = [
            GlobalSearchResult(
                entity_type="track",
                entity_id=7,
                title="Orbit",
                subtitle="Single",
                status="cleared",
            )
        ]
        self.saved_args = None
        self.deleted_ids = []
        self.raise_on_save = None
        self.last_browse = None

    def list_saved_searches(self):
        return list(self.saved)

    def search(self, query_text, entity_types=None, limit=200):
        self.last_search = (query_text, entity_types, limit)
        if not query_text.strip():
            return []
        return list(self.results)

    def browse_default_view(self, entity_types=None, limit=200, preview_limit=8):
        self.last_browse = (entity_types, limit, preview_limit)
        return list(self.results)

    def save_search(self, name, query_text, entity_types):
        if self.raise_on_save is not None:
            raise self.raise_on_save
        self.saved_args = (name, query_text, entity_types)
        self.saved.append(
            SavedSearchRecord(
                id=max(saved.id for saved in self.saved) + 1,
                name=name,
                query_text=query_text,
                entity_types=list(entity_types or []),
            )
        )

    def delete_saved_search(self, saved_search_id):
        self.deleted_ids.append(saved_search_id)
        self.saved = [saved for saved in self.saved if saved.id != saved_search_id]


class _RelationshipService:
    def describe_links(self, entity_type, entity_id):
        return [
            RelationshipSection(
                section_title="Contracts",
                results=[
                    GlobalSearchResult(
                        entity_type="contract",
                        entity_id=5,
                        title=f"{entity_type.title()} #{entity_id} agreement",
                        subtitle="license",
                        status="active",
                    )
                ],
            )
        ]


class _ReleaseService:
    def __init__(self, validation_issues=None):
        self.validation_issues = list(validation_issues or [])
        self.last_validate_payload = None
        self.last_validate_release_id = None

    def validate_release(self, payload, release_id=None):
        self.last_validate_payload = payload
        self.last_validate_release_id = release_id
        return list(self.validation_issues)

    def resolve_artwork_path(self, artwork_path):
        return artwork_path


class _WorkService:
    def __init__(self):
        self.records = [
            WorkRecord(
                id=1,
                title="Orbit",
                alternate_titles=[],
                version_subtitle=None,
                language="English",
                lyrics_flag=False,
                instrumental_flag=True,
                genre_notes=None,
                iswc="T-123.456.789-Z",
                registration_number="WRK-1",
                work_status="cleared",
                metadata_complete=True,
                contract_signed=True,
                rights_verified=True,
                notes=None,
                profile_name="Demo",
                created_at=None,
                updated_at=None,
                track_count=2,
                contributor_count=1,
            )
        ]
        self.detail = WorkDetail(
            work=self.records[0],
            contributors=[
                WorkContributorRecord(
                    id=1,
                    work_id=1,
                    party_id=None,
                    display_name="Lyra Moonwake",
                    role="composer",
                    share_percent=100.0,
                    role_share_percent=100.0,
                    notes=None,
                )
            ],
            track_ids=[11, 12],
        )
        self.link_calls = []
        self.delete_calls = []

    def list_works(self, search_text="", linked_track_id=None):
        self.last_list_args = (search_text, linked_track_id)
        return list(self.records)

    def fetch_work_detail(self, work_id):
        return self.detail if work_id == 1 else None

    def link_tracks_to_work(self, work_id, track_ids):
        self.link_calls.append((work_id, list(track_ids)))

    def delete_work(self, work_id):
        self.delete_calls.append(work_id)


class DialogControllerBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if DIALOG_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f"Dialog modules unavailable: {DIALOG_IMPORT_ERROR}")
        cls.app = require_qapplication()

    def test_global_search_dialog_handles_save_open_and_delete_paths(self):
        search_service = _SearchService()
        dialog = GlobalSearchDialog(
            search_service=search_service,
            relationship_service=_RelationshipService(),
        )
        opened = []
        dialog.open_entity_requested.connect(
            lambda entity_type, entity_id: opened.append((entity_type, entity_id))
        )
        try:
            self.assertEqual(search_service.last_browse, (None, 200, 8))
            self.assertEqual(dialog.results_table.rowCount(), 1)
            self.assertEqual(dialog.results_table.currentRow(), -1)
            self.assertIn("catalog overview", dialog.results_status_label.text().lower())

            with mock.patch.object(QMessageBox, "information", return_value=None) as info:
                dialog.open_selected_result()
            info.assert_called_once()

            dialog.search_edit.setText("orbit")
            self.app.processEvents()
            self.assertEqual(dialog.results_table.rowCount(), 1)
            dialog.results_table.selectRow(0)
            self.app.processEvents()
            dialog.open_selected_result()
            self.assertEqual(opened, [("track", 7)])
            self.assertIn("Contracts", dialog.relationships_edit.toPlainText())

            dialog.save_current_search()
            self.assertEqual(search_service.saved_args, ("orbit", "orbit", None))
            self.assertEqual(dialog.saved_searches_list.count(), 2)

            dialog.saved_searches_list.setCurrentRow(1)
            dialog.delete_saved_search()
            self.assertEqual(search_service.deleted_ids, [2])
            self.assertEqual(dialog.saved_searches_list.count(), 1)
        finally:
            dialog.close()

    def test_global_search_dialog_reports_blank_and_failed_save(self):
        search_service = _SearchService()
        search_service.raise_on_save = RuntimeError("disk unavailable")
        dialog = GlobalSearchDialog(
            search_service=search_service,
            relationship_service=_RelationshipService(),
        )
        try:
            with mock.patch.object(QMessageBox, "information", return_value=None) as info:
                dialog.save_current_search()
            info.assert_called_once()

            dialog.search_edit.setText("moon")
            self.app.processEvents()
            with mock.patch.object(QMessageBox, "critical", return_value=None) as critical:
                dialog.save_current_search()
            critical.assert_called_once()
        finally:
            dialog.close()

    def test_release_editor_validates_track_requirements_and_accepts_clean_payloads(self):
        invalid_service = _ReleaseService(
            validation_issues=[
                ReleaseValidationIssue(
                    severity="error",
                    field_name="title",
                    message="Release title is required.",
                )
            ]
        )
        invalid_dialog = ReleaseEditorDialog(
            release_service=invalid_service,
            track_title_resolver=lambda track_id: f"Track {track_id}",
            selected_track_ids_provider=lambda: [3],
        )
        try:
            with mock.patch.object(QMessageBox, "warning", return_value=None) as warning:
                invalid_dialog.accept()
            warning.assert_called_once()
            self.assertEqual(invalid_dialog.result(), QDialog.Rejected)
        finally:
            invalid_dialog.close()

        empty_dialog = ReleaseEditorDialog(
            release_service=_ReleaseService(),
            track_title_resolver=lambda track_id: f"Track {track_id}",
            selected_track_ids_provider=lambda: [],
        )
        try:
            with mock.patch.object(QMessageBox, "warning", return_value=None) as warning:
                empty_dialog.accept()
            warning.assert_called_once()
            self.assertIn("Attach at least one track", warning.call_args.args[2])
            self.assertEqual(empty_dialog.result(), QDialog.Rejected)
        finally:
            empty_dialog.close()

        accepting_service = _ReleaseService()
        accepting_dialog = ReleaseEditorDialog(
            release_service=accepting_service,
            track_title_resolver=lambda track_id: f"Track {track_id}",
            selected_track_ids_provider=lambda: [3, 3, -1, 0, 5],
        )
        try:
            accepting_dialog.title_edit.setText("Orbit Collection")
            accepting_dialog._original_artwork_display_path = "/tmp/original.png"
            accepting_dialog.artwork_path_edit.setText("/tmp/original.png")
            accepting_dialog._clear_artwork()
            accepting_dialog.accept()

            self.assertEqual(accepting_dialog.result(), QDialog.Accepted)
            self.assertIsNotNone(accepting_service.last_validate_payload)
            self.assertEqual(
                [
                    placement.track_id
                    for placement in accepting_service.last_validate_payload.placements
                ],
                [3, 5],
            )
            self.assertTrue(accepting_service.last_validate_payload.clear_artwork)
        finally:
            accepting_dialog.close()

    def test_work_browser_handles_empty_selection_filtering_and_delete_confirmation(self):
        service = _WorkService()
        selected_track_ids: list[int] = []
        dialog = WorkBrowserDialog(
            work_service=service,
            track_title_resolver=lambda track_id: f"Track {track_id}",
            selected_track_ids_provider=lambda: list(selected_track_ids),
        )
        emitted_filters = []
        emitted_links = []
        emitted_child_creations = []
        emitted_album_creations = []
        emitted_deletes = []
        dialog.filter_requested.connect(lambda track_ids: emitted_filters.append(track_ids))
        dialog.create_child_track_requested.connect(
            lambda work_id: emitted_child_creations.append(work_id)
        )
        dialog.create_album_for_work_requested.connect(
            lambda work_id: emitted_album_creations.append(work_id)
        )
        dialog.link_tracks_requested.connect(
            lambda work_id, track_ids: emitted_links.append((work_id, track_ids))
        )
        dialog.delete_requested.connect(lambda work_id: emitted_deletes.append(work_id))
        try:
            with mock.patch.object(QMessageBox, "information", return_value=None) as info:
                dialog.create_child_track()
            info.assert_called_once()

            with mock.patch.object(QMessageBox, "information", return_value=None) as info:
                dialog.create_album_for_work()
            info.assert_called_once()

            with mock.patch.object(QMessageBox, "information", return_value=None) as info:
                dialog.link_selected_tracks()
            info.assert_called_once()

            selected_track_ids[:] = [11, 12]
            dialog.refresh_selection_scope()
            self.assertEqual(dialog.selection_scope_state().track_ids, (11, 12))
            self.assertEqual(dialog.selection_scope_state().source_label, "Catalog selection")

            dialog.table.selectRow(0)
            self.app.processEvents()

            dialog.create_child_track()
            self.assertEqual(emitted_child_creations, [1])

            dialog.create_album_for_work()
            self.assertEqual(emitted_album_creations, [1])

            dialog.link_selected_tracks()
            self.assertEqual(emitted_links, [(1, [11, 12])])

            dialog.panel._selection_override_track_ids = [12]
            dialog.refresh_selection_scope()
            self.assertTrue(dialog.selection_scope_state().override_active)
            self.assertEqual(dialog.selection_scope_state().track_ids, (12,))

            dialog.link_selected_tracks()
            self.assertEqual(emitted_links[-1], (1, [12]))

            dialog.filter_by_work_tracks()
            self.assertEqual(emitted_filters, [[11, 12]])

            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
                dialog.delete_selected()
            self.assertEqual(emitted_deletes, [])

            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                dialog.delete_selected()
            self.assertEqual(emitted_deletes, [1])
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
