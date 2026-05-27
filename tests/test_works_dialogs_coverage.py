"""Additional behavioral coverage for the Work Manager dialogs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
)

from isrc_manager.parties import PartyRecord
from isrc_manager.works import WorkPayload
from isrc_manager.works import controller as works_controller
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


class _WorkControllerMessages:
    Yes = 1
    No = 2

    def __init__(self) -> None:
        self.warnings: list[tuple[str, str]] = []
        self.infos: list[tuple[str, str]] = []
        self.criticals: list[tuple[str, str]] = []
        self.questions: list[tuple[str, str]] = []
        self.question_response = self.Yes

    def warning(self, _parent, title: str, message: str) -> None:
        self.warnings.append((title, message))

    def information(self, _parent, title: str, message: str) -> None:
        self.infos.append((title, message))

    def critical(self, _parent, title: str, message: str) -> None:
        self.criticals.append((title, message))

    def question(self, _parent, title: str, message: str, *_args) -> int:
        self.questions.append((title, message))
        return self.question_response


class _ControllerProgress:
    def __init__(self) -> None:
        self.updates: list[tuple[int, int, str]] = []

    def report_progress(self, *, value: int, maximum: int, message: str) -> None:
        self.updates.append((value, maximum, message))


class _ControllerConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _ControllerWorkService:
    def __init__(self) -> None:
        work = _work_record(101, "Loaded Work", iswc="T-111.222.333-4")
        self.detail = WorkDetail(work=work, contributors=[], track_ids=[1, 2])
        self.created_payloads: list[WorkPayload] = []
        self.updated_payloads: list[tuple[int, WorkPayload]] = []
        self.deleted_ids: list[int] = []
        self.linked: list[tuple[int, list[int]]] = []
        self.next_id = 201
        self.fail_duplicate = False
        self.fail_link = False

    def fetch_work_detail(self, work_id: int):
        return self.detail if int(work_id) == 101 else None

    def list_works(self, **_kwargs):
        return [self.detail.work]

    def create_work(self, payload: WorkPayload) -> int:
        self.created_payloads.append(payload)
        self.next_id += 1
        return self.next_id

    def update_work(self, work_id: int, payload: WorkPayload) -> None:
        self.updated_payloads.append((int(work_id), payload))

    def delete_work(self, work_id: int) -> None:
        self.deleted_ids.append(int(work_id))

    def duplicate_work(self, work_id: int) -> int:
        if self.fail_duplicate:
            raise RuntimeError("duplicate failed")
        return int(work_id) + 500

    def link_tracks_to_work(self, work_id: int, track_ids: list[int]) -> None:
        if self.fail_link:
            raise RuntimeError("link failed")
        self.linked.append((int(work_id), list(track_ids)))


def _controller_app() -> SimpleNamespace:
    app = SimpleNamespace()
    app.work_service = _ControllerWorkService()
    app.conn = _ControllerConnection()
    app.logger = SimpleNamespace(exception=lambda *_args, **_kwargs: None)
    app.submitted_tasks = []
    app.refresh_requests = []
    app.applied_refreshes = []
    app.focused_work_ids = []
    app.events = []
    app.audits = []
    app.audit_commits = 0
    app.history_refreshes = 0
    app.work_panel_refreshes = 0
    app.child_track_requests = []
    app.context_refreshes = 0
    app.add_track_choice_refreshes = 0
    app.ui_progress = []
    app.errors = []
    app._current_profile_name = lambda: "QA Profile"
    app._capture_catalog_refresh_request = lambda **kwargs: app.refresh_requests.append(kwargs) or {
        "request": kwargs
    }
    app._load_catalog_ui_dataset_from_bundle = lambda _bundle, _ctx, **kwargs: {
        "loaded_with": kwargs
    }
    app._apply_catalog_refresh_request = (
        lambda dataset, request, **_kwargs: app.applied_refreshes.append((dataset, request))
    )
    app._scaled_ui_progress_callback = lambda _ui_progress, **_kwargs: (lambda *_args, **_kw: None)
    app._advance_task_ui_progress = lambda _ui_progress, **kwargs: app.ui_progress.append(kwargs)
    app._refresh_history_actions = lambda: setattr(
        app,
        "history_refreshes",
        app.history_refreshes + 1,
    )
    app._refresh_add_track_artist_party_choices = lambda: setattr(
        app,
        "add_track_choice_refreshes",
        app.add_track_choice_refreshes + 1,
    )
    app._refresh_work_track_creation_context_ui = lambda: setattr(
        app,
        "context_refreshes",
        app.context_refreshes + 1,
    )
    app._refresh_work_manager_panel = lambda: setattr(
        app,
        "work_panel_refreshes",
        app.work_panel_refreshes + 1,
    )
    app._focus_work_in_manager = lambda work_id: app.focused_work_ids.append(int(work_id))
    app._log_event = lambda *args, **kwargs: app.events.append((args, kwargs))
    app._audit = lambda *args, **kwargs: app.audits.append((args, kwargs))
    app._audit_commit = lambda: setattr(app, "audit_commits", app.audit_commits + 1)
    app._work_manager_task_owner = lambda: app
    app._show_background_task_error = lambda title, failure, **kwargs: app.errors.append(
        (title, failure, kwargs)
    )
    app._begin_work_child_track_creation = (
        lambda work_id, **kwargs: app.child_track_requests.append((int(work_id), kwargs)) or True
    )
    app._submit_background_bundle_task = lambda **kwargs: app.submitted_tasks.append(kwargs)
    app._normalize_track_ids = lambda track_ids: [
        int(track_id) for track_id in track_ids if track_id
    ]
    app._run_snapshot_history_action = lambda **kwargs: kwargs["mutation"]()
    app._adjacent_work_id_in_manager = lambda _work_id: 202
    return app


def test_work_controller_create_update_and_delete_background_callbacks(monkeypatch) -> None:
    messages = _WorkControllerMessages()

    def root_attr(name: str, fallback):
        if name == "QMessageBox":
            return messages
        if name == "run_snapshot_history_action":
            return lambda **kwargs: kwargs["mutation"]()
        return fallback

    monkeypatch.setattr(works_controller, "_root_attr", root_attr)
    app = _controller_app()
    bundle = SimpleNamespace(work_service=app.work_service, history_manager=object())

    works_controller.create_work(app, WorkPayload(title="Created Work", track_ids=[3]))
    create_task = app.submitted_tasks[-1]
    create_result = create_task["task_fn"](bundle, _ControllerProgress())
    assert create_result["dataset"]["loaded_with"]["progress_start"] == 62
    create_task["on_success_before_cleanup"](create_result, object())
    create_task["on_success_after_cleanup"](create_result)
    assert app.conn.commits == 1
    assert app.applied_refreshes[-1][1] == {"request": {"focus_id": 3}}
    assert app.events[-1][0][0] == "work.create"
    assert messages.questions == []

    works_controller.create_work(app, WorkPayload(title="Empty Work"))
    empty_task = app.submitted_tasks[-1]
    empty_result = empty_task["task_fn"](bundle, _ControllerProgress())
    empty_task["on_success_before_cleanup"](empty_result, object())
    empty_task["on_success_after_cleanup"](empty_result)
    assert app.history_refreshes == 1
    assert messages.questions[-1][0] == "Work Manager"
    assert app.child_track_requests[-1][0] == empty_result["work_id"]

    update_payload = WorkPayload(title="Updated Work", track_ids=[1, 2])
    works_controller.update_work(app, 101, update_payload)
    update_task = app.submitted_tasks[-1]
    update_result = update_task["task_fn"](bundle, _ControllerProgress())
    update_task["on_success_before_cleanup"](update_result, object())
    update_task["on_success_after_cleanup"](update_result)
    assert app.work_service.updated_payloads == [(101, update_payload)]
    assert app.events[-1][0][0] == "work.update"
    assert app.focused_work_ids[-1] == 101

    works_controller.delete_work(app, 101)
    delete_task = app.submitted_tasks[-1]
    delete_result = delete_task["task_fn"](bundle, _ControllerProgress())
    delete_task["on_success_before_cleanup"](delete_result, object())
    delete_task["on_success_after_cleanup"](delete_result)
    assert app.work_service.deleted_ids == [101]
    assert delete_result["next_work_id"] == 202
    assert app.focused_work_ids[-1] == 202
    delete_task["on_error"](RuntimeError("delete failed"))
    assert app.errors[-1][0] == "Work Manager"


def test_work_controller_direct_actions_handle_success_conflicts_and_missing_input(
    monkeypatch,
) -> None:
    messages = _WorkControllerMessages()
    monkeypatch.setattr(
        works_controller,
        "_root_attr",
        lambda name, fallback: messages if name == "QMessageBox" else fallback,
    )
    app = _controller_app()

    works_controller.duplicate_work(app, 101)
    assert app.audits[-1][0][0] == "CREATE"
    assert app.history_refreshes == 1

    app.work_service.fail_duplicate = True
    works_controller.duplicate_work(app, 101)
    assert app.conn.rollbacks == 1
    assert messages.criticals[-1][1].startswith("Could not duplicate the work:")

    works_controller.link_tracks_to_work(app, 101, [])
    assert messages.infos[-1][1] == "Select one or more tracks first."

    works_controller.link_tracks_to_work(app, 101, [4, "5", None])
    assert app.work_service.linked == [(101, [4, 5])]
    app.work_service.fail_link = True
    works_controller.link_tracks_to_work(app, 101, [6])
    assert app.conn.rollbacks == 2
    assert messages.criticals[-1][1].startswith("Could not link the tracks:")

    missing_app = _controller_app()
    missing_app.work_service = None
    works_controller.create_work(missing_app, WorkPayload(title="No profile"))
    works_controller.update_work(missing_app, 101, WorkPayload(title="No profile"))
    works_controller.delete_work(missing_app, 101)
    assert messages.warnings[-3:] == [
        ("Work Manager", "Open a profile first."),
        ("Work Manager", "Open a profile first."),
        ("Work Manager", "Open a profile first."),
    ]

    works_controller.update_work(app, 999, WorkPayload(title="Missing Work"))
    works_controller.delete_work(app, 999)
    assert messages.warnings[-2:] == [
        ("Work Manager", "The selected work could not be loaded."),
        ("Work Manager", "The selected work could not be loaded."),
    ]


def _work_context_app() -> SimpleNamespace:
    require_qapplication()
    app = SimpleNamespace()
    app.work_service = _ControllerWorkService()
    app.add_data_work_context_group = QPushButton()
    app.add_data_work_mode_combo = QComboBox()
    app.add_data_work_work_combo = QComboBox()
    app.add_data_work_relationship_combo = QComboBox()
    app.add_data_work_parent_combo = QComboBox()
    app.add_data_work_context_summary = QLabel()
    app.add_data_work_context_hint = QLabel()
    app.add_data_clear_work_context_button = QPushButton()
    app.save_button = QPushButton()
    app.track_title_field = QLineEdit()
    app.iswc_field = QLineEdit()
    app.panel_states = []
    app.form_clears = 0
    app.focused_work_ids = []
    app.opened_manager_ids = []
    app.heading_resets = 0
    app._default_work_track_context = lambda: works_controller._default_work_track_context(app)
    app._current_work_track_context = lambda: works_controller._current_work_track_context(app)
    app._normalize_work_track_relationship = (
        lambda value: works_controller._normalize_work_track_relationship(app, value)
    )
    app._work_track_governance_modes = lambda: works_controller._work_track_governance_modes()
    app._work_track_relationship_choices = (
        lambda: works_controller._work_track_relationship_choices()
    )
    app._work_track_relationship_label = (
        lambda value: works_controller._work_track_relationship_label(value)
    )
    app._available_work_records = lambda: works_controller._available_work_records(app)
    app._work_choice_label = lambda record: works_controller._work_choice_label(record)
    app._get_track_title = _track_title
    app._reset_add_track_heading = lambda: setattr(
        app,
        "heading_resets",
        app.heading_resets + 1,
    )
    app._refresh_work_track_creation_context_ui = (
        lambda: works_controller._refresh_work_track_creation_context_ui(app)
    )
    app._clear_work_track_creation_context = (
        lambda: works_controller._clear_work_track_creation_context(app)
    )
    app._begin_work_child_track_creation = (
        lambda work_id, **kwargs: works_controller._begin_work_child_track_creation(
            app,
            work_id,
            **kwargs,
        )
    )
    app._apply_add_data_panel_state = lambda state: app.panel_states.append(bool(state))
    app.clear_form_fields = lambda: setattr(app, "form_clears", app.form_clears + 1)
    app.open_work_manager = lambda **kwargs: app.opened_manager_ids.append(kwargs.get("work_id"))
    app._focus_work_in_manager = lambda work_id: app.focused_work_ids.append(int(work_id))
    return app


def test_work_track_context_normalizes_and_refreshes_linked_work_ui() -> None:
    app = _work_context_app()
    app._pending_work_track_context = {
        "mode": "bad mode",
        "work_id": "101",
        "relationship_type": "not-a-real-relationship",
        "parent_track_id": "bad parent",
        "locked_work": True,
        "return_to_work_manager": True,
    }

    context = works_controller._current_work_track_context(app)
    assert context == {
        "mode": "link_existing_work",
        "work_id": 101,
        "relationship_type": "original",
        "parent_track_id": None,
        "locked_work": True,
        "return_to_work_manager": True,
    }

    works_controller._refresh_work_track_creation_context_ui(app)

    assert app.heading_resets == 1
    assert app.add_data_work_context_group.isVisible()
    assert app.add_data_work_mode_combo.currentData() == "link_existing_work"
    assert not app.add_data_work_work_combo.isEnabled()
    assert "Loaded Work" in app.add_data_work_context_summary.text()
    assert app.add_data_work_relationship_combo.isEnabled()
    assert app.add_data_work_parent_combo.isEnabled()
    assert app.add_data_clear_work_context_button.isVisible()
    assert app.save_button.text() == "Save Governed Track"

    app.add_data_work_mode_combo.setCurrentIndex(
        app.add_data_work_mode_combo.findData("create_new_work")
    )
    works_controller._on_add_track_governance_mode_changed(app, 0)
    assert app._pending_work_track_context["mode"] == "create_new_work"
    assert app._pending_work_track_context["work_id"] is None
    assert app.save_button.text() == "Create Work + Save Track"

    app.add_data_work_work_combo.addItem("Invalid", "not an int")
    app.add_data_work_work_combo.setCurrentIndex(app.add_data_work_work_combo.count() - 1)
    works_controller._on_add_track_work_changed(app, 0)
    assert app._pending_work_track_context["work_id"] is None

    app._pending_work_track_context = {
        "mode": "link_existing_work",
        "work_id": 101,
        "relationship_type": "original",
        "parent_track_id": None,
        "locked_work": False,
        "return_to_work_manager": False,
    }
    works_controller._refresh_work_track_creation_context_ui(app)
    app.add_data_work_relationship_combo.setCurrentIndex(
        app.add_data_work_relationship_combo.findData("remix")
    )
    works_controller._on_add_track_relationship_changed(app, 0)
    assert app._pending_work_track_context["relationship_type"] == "remix"

    app.add_data_work_parent_combo.addItem("Bad Parent", "bad")
    app.add_data_work_parent_combo.setCurrentIndex(app.add_data_work_parent_combo.count() - 1)
    works_controller._on_add_track_parent_track_changed(app, 0)
    assert app._pending_work_track_context["parent_track_id"] is None

    works_controller._clear_work_track_creation_context(app)
    assert app._pending_work_track_context == works_controller._default_work_track_context(app)


def test_work_child_track_creation_handles_missing_work_seed_and_return(monkeypatch) -> None:
    messages = _WorkControllerMessages()
    monkeypatch.setattr(
        works_controller,
        "_root_attr",
        lambda name, fallback: messages if name == "QMessageBox" else fallback,
    )
    app = _work_context_app()

    app.work_service = None
    assert works_controller._begin_work_child_track_creation(app, 101) is False
    assert messages.warnings[-1] == ("Work Manager", "Open a profile first.")

    app.work_service = _ControllerWorkService()
    assert works_controller._begin_work_child_track_creation(app, 999) is False
    assert messages.warnings[-1] == (
        "Work Manager",
        "The selected work could not be loaded.",
    )

    app.track_title_field.setText("Existing")
    app.iswc_field.setText("")
    assert (
        works_controller._begin_work_child_track_creation(
            app,
            101,
            seed_from_work=False,
        )
        is True
    )
    assert app.track_title_field.text() == "Existing"
    assert app.panel_states[-1] is True
    assert app.form_clears == 1
    assert app.focused_work_ids[-1] == 101

    app.work_service.detail.work.title = "Seeded Work"
    app.work_service.detail.work.iswc = "T-555.666.777-8"
    assert works_controller._launch_work_scoped_child_track_creation(
        app,
        101,
        relationship_type="Remix",
        parent_track_id=2,
    )
    assert app.track_title_field.text() == "Seeded Work"
    assert app.iswc_field.text() == "T-555.666.777-8"
    assert app._pending_work_track_context["relationship_type"] == "remix"
    assert app._pending_work_track_context["parent_track_id"] == 2

    works_controller._return_from_work_track_creation_context(app)
    assert app.panel_states[-1] is False
    assert app.opened_manager_ids[-1] == 101


def test_work_manager_selection_helpers_ignore_bad_panels_and_find_adjacent_ids() -> None:
    class BadSelectionPanel:
        def selected_work_id(self):
            raise RuntimeError("selection unavailable")

    class GoodSelectionPanel:
        def selected_work_id(self):
            return "101"

    app = SimpleNamespace(
        work_manager_panel=BadSelectionPanel(),
        work_browser_dialog=GoodSelectionPanel(),
    )
    assert works_controller._current_work_manager_selected_work_id(app) == 101

    class Table:
        def __init__(self, values):
            self.values = list(values)

        def rowCount(self):
            return len(self.values)

        def item(self, row, _column):
            value = self.values[row]
            return None if value is None else QTableWidgetItem(str(value))

    visible_panel = SimpleNamespace(
        isVisible=lambda: True,
        table=Table(["bad", 10, None, 20, 30]),
    )
    hidden_panel = SimpleNamespace(isVisible=lambda: False, table=Table([999]))
    app = SimpleNamespace(work_manager_panel=hidden_panel, work_browser_dialog=visible_panel)

    assert works_controller._adjacent_work_id_in_manager(app, 10) == 20
    assert works_controller._adjacent_work_id_in_manager(app, 30) == 20
    assert works_controller._adjacent_work_id_in_manager(app, 999) is None


def test_work_open_work_creation_dialog_profiles_and_result_paths(monkeypatch) -> None:
    class _AcceptedFakeDialog:
        exec_result = QDialog.Accepted

        def __init__(self, *_, **__) -> None:
            self._payload = WorkPayload(title="Created from Dialog", track_ids=[12])

        def exec(self):
            return self.exec_result

        def payload(self):
            return self._payload

    class _RejectedFakeDialog(_AcceptedFakeDialog):
        exec_result = QDialog.Rejected

    messages = _WorkControllerMessages()
    root_attr_calls: list[str] = []

    def root_attr(name: str, fallback):
        root_attr_calls.append(name)
        if name == "QMessageBox":
            return messages
        if name == "WorkEditorDialog":
            return _AcceptedFakeDialog
        return fallback

    monkeypatch.setattr(works_controller, "_root_attr", root_attr)

    assert works_controller._open_work_creation_dialog(SimpleNamespace(work_service=None)) is None
    assert messages.warnings[-1] == ("Work Manager", "Open a profile first.")

    app = SimpleNamespace(work_service=object(), _get_track_title=_track_title)
    payload = works_controller._open_work_creation_dialog(app)
    assert isinstance(payload, WorkPayload)
    assert payload.title == "Created from Dialog"
    assert payload.track_ids == [12]
    assert root_attr_calls.count("WorkEditorDialog") == 1

    def root_attr_rejected(name: str, fallback):
        if name == "WorkEditorDialog":
            return _RejectedFakeDialog
        if name == "QMessageBox":
            return messages
        return fallback

    monkeypatch.setattr(works_controller, "_root_attr", root_attr_rejected)
    assert works_controller._open_work_creation_dialog(app) is None


def test_work_open_work_manager_configures_panel_and_available_records(monkeypatch) -> None:
    class _FakeSearchEdit:
        def __init__(self, text: str = "") -> None:
            self._text = text
            self._blocked: list[bool] = []

        def text(self):
            return self._text

        def clear(self):
            self._text = ""

        def blockSignals(self, state: bool):
            self._blocked.append(state)
            return bool(self._blocked[-2]) if len(self._blocked) >= 2 else False

    class _FakePanel:
        def __init__(self) -> None:
            self.search_edit = _FakeSearchEdit(" prefill ")
            self.linked_track_id = 777
            self.refresh_calls = 0
            self.selected_track_ids = []
            self.focus_calls: list[int] = []

        def set_linked_track_id(self, value):
            self.linked_track_id = value

        def set_selection_override_track_ids(self, values):
            self.selected_track_ids = list(values)

        def refresh(self):
            self.refresh_calls += 1

        def focus_work(self, work_id: int):
            self.focus_calls.append(int(work_id))

    class _RecordingWork:
        def __init__(self, payload: WorkPayload, rows=None) -> None:
            self.payload = payload
            self._rows = rows or []

        def list_works(self, **_kwargs):
            return list(self._rows)

    app = SimpleNamespace(
        work_service=_RecordingWork(
            WorkPayload(title=""),
            rows=[_work_record(901, "Scoped")],
        )
    )
    panels: list[_FakePanel] = []
    app._ensure_work_manager_dock = lambda: object()
    app._configure_work_manager_panel = (
        lambda panel, **kwargs: works_controller._configure_work_manager_panel(
            app,
            panel,
            **kwargs,
        )
    )

    def show_workspace_panel(
        factory, panel_attr, legacy_attr, configure, refresh_scope
    ) -> _FakePanel:
        panel = _FakePanel()
        panels.append(panel)
        configure(panel)
        return panel

    app._show_workspace_panel = show_workspace_panel
    result = works_controller.open_work_manager(
        app,
        linked_track_id=401,
        work_id=901,
        scope_track_ids=[14, 15],
    )
    assert result is panels[-1]
    assert result.refresh_calls == 0
    assert result.selected_track_ids == [14, 15]
    assert result.focus_calls == [901, 901]

    app.work_service = _RecordingWork(WorkPayload(title=""), rows=[_work_record(901, "Scoped")])
    app._show_workspace_panel = show_workspace_panel
    result_no_rows = works_controller.open_work_manager(app)
    assert result_no_rows is panels[-1]
    assert result_no_rows.selected_track_ids == []

    # Exercise _configure_work_manager_panel error branch when work lookup fails.
    app.work_service = _RecordingWork(
        WorkPayload(title=""), rows=[_work_record(111, "Target Work")]
    )
    bad_panel = _FakePanel()
    bad_panel.linked_track_id = None
    app.work_service.list_works = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("lookup failed")
    )
    works_controller._configure_work_manager_panel(app, bad_panel, linked_track_id=111)
    assert bad_panel.focus_calls == []


def test_work_available_records_and_panel_focus_branches() -> None:
    no_service = SimpleNamespace(work_service=None)
    assert works_controller._available_work_records(no_service) == []

    missing = SimpleNamespace(
        work_service=mock.Mock(list_works=mock.Mock(side_effect=RuntimeError("nope")))
    )
    assert works_controller._available_work_records(missing) == []
    missing.work_service.list_works.assert_called_once()

    class _BadWorkPanel:
        def selected_work_id(self):
            raise RuntimeError("selection unavailable")

    class _GoodWorkPanel:
        def selected_work_id(self):
            return "101"

    app = SimpleNamespace(
        work_manager_panel=_BadWorkPanel(),
        work_browser_dialog=_GoodWorkPanel(),
    )
    assert works_controller._current_work_manager_selected_work_id(app) == 101

    class _BadPanel:
        def __init__(self, values):
            self.values = list(values)

        def rowCount(self):
            return len(self.values)

        def item(self, row, _column):
            value = self.values[row]
            return None if value is None else QTableWidgetItem(str(value))

    app = SimpleNamespace(
        work_manager_panel=SimpleNamespace(
            isVisible=lambda: False,
            table=_BadPanel(["bad", 10, None, 20, 30]),
        ),
        work_browser_dialog=SimpleNamespace(
            isVisible=lambda: True,
            table=_BadPanel(["bad", 10, None, 20, 30]),
        ),
    )
    assert works_controller._adjacent_work_id_in_manager(app, 10) == 20
    assert works_controller._adjacent_work_id_in_manager(app, 30) == 20
    assert works_controller._adjacent_work_id_in_manager(app, 999) is None


def test_work_controller_small_helpers_payloads_and_focus_noops() -> None:
    payload = works_controller._work_payload_from_track_seed(
        SimpleNamespace(_current_profile_name=lambda: "QA Profile"),
        track_title="  Seeded Work  ",
        iswc="  T-123.456.789-0  ",
        registration_number="  REG-123  ",
    )
    assert payload == WorkPayload(
        title="Seeded Work",
        iswc="T-123.456.789-0",
        registration_number="REG-123",
        profile_name="QA Profile",
    )
    assert works_controller._work_choice_label(SimpleNamespace(id=0, title="", iswc="")) == (
        "Untitled Work"
    )
    assert works_controller._work_choice_label(SimpleNamespace(id=45, title="", iswc="")) == (
        "Work #45"
    )

    app = SimpleNamespace()
    works_controller._focus_work_in_manager(app, None)
    works_controller._focus_work_in_manager(app, 12)

    no_focus_panel = SimpleNamespace()
    app.work_browser_dialog = no_focus_panel
    works_controller._focus_work_in_manager(app, 12)

    focused: list[int] = []
    app.work_browser_dialog = SimpleNamespace(focus_work=lambda work_id: focused.append(work_id))
    works_controller._focus_work_in_manager(app, 12)
    assert focused == [12]

    works_controller._refresh_work_track_creation_context_ui(SimpleNamespace())


def test_work_context_handles_missing_detail_invalid_choices_and_missing_parent() -> None:
    app = _work_context_app()
    missing_record = _work_record(303, "Unavailable Work")
    app.work_service = SimpleNamespace(
        list_works=lambda: [
            SimpleNamespace(id="bad", title="Bad", iswc=None),
            SimpleNamespace(id=0, title="Zero", iswc=None),
            missing_record,
        ],
        fetch_work_detail=lambda _work_id: None,
    )
    app._pending_work_track_context = {
        "mode": "link_existing_work",
        "work_id": 999,
        "relationship_type": "version",
        "parent_track_id": 12,
        "locked_work": False,
        "return_to_work_manager": False,
    }

    works_controller._refresh_work_track_creation_context_ui(app)

    combo_values = [
        app.add_data_work_work_combo.itemData(index)
        for index in range(app.add_data_work_work_combo.count())
    ]
    assert combo_values == [None, 303, 999]
    assert "Choose the existing Work" in app.add_data_work_context_summary.text()
    assert app._pending_work_track_context["parent_track_id"] is None
    assert not app.add_data_work_relationship_combo.isEnabled()


def test_work_create_declined_child_prompt_and_update_delete_no_refresh_branches(
    monkeypatch,
) -> None:
    messages = _WorkControllerMessages()
    messages.question_response = messages.No

    def root_attr(name: str, fallback):
        if name == "QMessageBox":
            return messages
        if name == "run_snapshot_history_action":
            return lambda **kwargs: kwargs["mutation"]()
        return fallback

    monkeypatch.setattr(works_controller, "_root_attr", root_attr)

    app = _controller_app()
    bundle = SimpleNamespace(work_service=app.work_service, history_manager=object())
    works_controller.create_work(app, WorkPayload(title="Prompt Declined"))
    create_task = app.submitted_tasks[-1]
    create_result = create_task["task_fn"](bundle, _ControllerProgress())
    create_task["on_success_before_cleanup"](create_result, object())
    create_task["on_success_after_cleanup"](create_result)
    assert messages.questions[-1][0] == "Work Manager"
    assert app.child_track_requests == []

    class FailingCommitConnection(_ControllerConnection):
        def commit(self) -> None:
            super().commit()
            raise RuntimeError("commit failed")

    app.conn = FailingCommitConnection()
    works_controller.update_work(app, 101, WorkPayload(title="No Refresh", track_ids=[1, 2]))
    update_task = app.submitted_tasks[-1]
    update_result = update_task["task_fn"](bundle, _ControllerProgress())
    update_task["on_success_before_cleanup"](update_result, object())
    assert app.conn.commits == 1
    assert app.history_refreshes >= 2
    assert app.add_track_choice_refreshes >= 2
    assert app.context_refreshes >= 2

    app.work_service.detail = WorkDetail(
        work=_work_record(101, "Delete Without Tracks"),
        contributors=[],
        track_ids=[],
    )
    app._adjacent_work_id_in_manager = lambda _work_id: None
    works_controller.delete_work(app, 101)
    delete_task = app.submitted_tasks[-1]
    delete_result = delete_task["task_fn"](bundle, _ControllerProgress())
    assert "dataset" not in delete_result
    focus_count = len(app.focused_work_ids)
    delete_task["on_success_before_cleanup"](delete_result, object())
    delete_task["on_success_after_cleanup"](delete_result)
    assert len(app.focused_work_ids) == focus_count


def test_work_manager_missing_profile_and_missing_details_are_reported(monkeypatch) -> None:
    messages = _WorkControllerMessages()
    monkeypatch.setattr(
        works_controller,
        "_root_attr",
        lambda name, fallback: messages if name == "QMessageBox" else fallback,
    )
    no_profile_app = SimpleNamespace(work_service=None)

    assert works_controller.open_work_manager(no_profile_app) is None
    assert messages.warnings[-1] == ("Work Manager", "Open a profile first.")

    app = _controller_app()
    works_controller.duplicate_work(app, 999)
    works_controller.link_tracks_to_work(app, 999, [1])

    assert messages.warnings[-2:] == [
        ("Work Manager", "The selected work could not be loaded."),
        ("Work Manager", "The selected work could not be loaded."),
    ]
