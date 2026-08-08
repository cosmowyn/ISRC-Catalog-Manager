from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings

from isrc_manager.history import HistoryManager
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.parties import controller as party_controller
from isrc_manager.parties import history_actions as party_history_actions
from isrc_manager.parties.history_actions import (
    delete_parties_with_history,
    merge_parties_with_history,
)
from isrc_manager.qa.history_scenarios import (
    qualify_party_delete_merge_history,
    qualify_right_delete_history,
)
from isrc_manager.rights import RightPayload, RightsService
from isrc_manager.rights import controller as rights_controller
from isrc_manager.rights import dialogs as rights_dialogs
from isrc_manager.services import DatabaseSchemaService, DatabaseSessionService
from isrc_manager.tasks.history_helpers import run_snapshot_history_action
from isrc_manager.works import WorkPayload, WorkService
from tests.qt_test_helpers import require_qapplication


@pytest.fixture
def history_context(tmp_path):
    db_path = tmp_path / "Database" / "catalog.db"
    session_service = DatabaseSessionService()
    session = session_service.open(db_path)
    conn = session.conn
    schema = DatabaseSchemaService(conn, data_root=tmp_path / "data")
    schema.init_db()
    schema.migrate_schema()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    history = HistoryManager(
        conn,
        settings,
        db_path,
        tmp_path / "history",
        tmp_path / "data",
        tmp_path / "backups",
    )
    context = SimpleNamespace(
        conn=conn,
        settings=settings,
        history=history,
        history_manager=history,
        party_service=PartyService(conn),
        rights_service=RightsService(conn),
        work_service=WorkService(conn),
    )
    context._run_snapshot_history_action = lambda **kwargs: run_snapshot_history_action(
        history_manager=history,
        **kwargs,
    )
    try:
        yield context
    finally:
        settings.clear()
        session_service.close(conn)


def test_party_delete_is_latest_reversible_action_and_supports_redo(history_context) -> None:
    context = history_context
    prior_entry = context.history.record_setting_change(
        key="isrc_prefix",
        label="Earlier Unrelated Action",
        before_value="",
        after_value="NLABC",
    )
    context.settings.setValue("isrc_prefix", "NLABC")
    party_id = context.party_service.create_party(
        PartyPayload(legal_name="Delete Me B.V.", display_name="Delete Me")
    )
    work_id = context.work_service.create_work(WorkPayload(title="Delete Relationship Work"))
    right_id = context.rights_service.create_right(
        RightPayload(
            title="Delete Relationship Right",
            right_type="composition_publishing",
            work_id=work_id,
            granted_to_party_id=party_id,
        )
    )

    deleted = delete_parties_with_history(
        context,
        [party_id],
        party_label=party_controller._party_identity_primary_label,
    )

    assert deleted == 1
    assert context.party_service.fetch_party(party_id) is None
    assert context.rights_service.fetch_right(right_id).granted_to_party_id is None
    delete_entry = context.history.get_current_entry()
    assert delete_entry is not None
    assert delete_entry.action_type == "party.delete"
    assert delete_entry.label == "Delete Party: Delete Me"
    assert delete_entry.parent_id == prior_entry.entry_id

    undone = context.history.undo()
    assert undone is not None and undone.entry_id == delete_entry.entry_id
    assert context.party_service.fetch_party(party_id) is not None
    assert context.rights_service.fetch_right(right_id).granted_to_party_id == party_id
    assert context.settings.value("isrc_prefix") == "NLABC"
    assert context.history.get_current_entry_id() == prior_entry.entry_id

    redone = context.history.redo()
    assert redone is not None and redone.entry_id == delete_entry.entry_id
    assert context.party_service.fetch_party(party_id) is None
    assert context.rights_service.fetch_right(right_id).granted_to_party_id is None


def test_party_merge_restores_duplicate_and_dependent_right_links(history_context) -> None:
    context = history_context
    primary_id = context.party_service.create_party(
        PartyPayload(legal_name="Primary Publisher B.V.", display_name="Primary Publisher")
    )
    duplicate_id = context.party_service.create_party(
        PartyPayload(legal_name="Duplicate Publisher B.V.", display_name="Duplicate Publisher")
    )
    work_id = context.work_service.create_work(WorkPayload(title="Linked Composition"))
    right_id = context.rights_service.create_right(
        RightPayload(
            title="Publishing Control",
            right_type="composition_publishing",
            work_id=work_id,
            granted_to_party_id=duplicate_id,
        )
    )

    merged = merge_parties_with_history(
        context,
        primary_id,
        [duplicate_id],
        party_label=party_controller._party_identity_primary_label,
    )

    assert merged.id == primary_id
    assert context.party_service.fetch_party(duplicate_id) is None
    assert context.rights_service.fetch_right(right_id).granted_to_party_id == primary_id
    merge_entry = context.history.get_current_entry()
    assert merge_entry is not None
    assert merge_entry.action_type == "party.merge"
    assert merge_entry.label == "Merge Parties into: Primary Publisher"
    assert merge_entry.payload["duplicate_party_ids"] == [duplicate_id]

    context.history.undo()
    assert context.party_service.fetch_party(duplicate_id) is not None
    assert context.rights_service.fetch_right(right_id).granted_to_party_id == duplicate_id

    context.history.redo()
    assert context.party_service.fetch_party(duplicate_id) is None
    assert context.rights_service.fetch_right(right_id).granted_to_party_id == primary_id


def test_right_delete_restores_record_and_party_relationship_on_undo(history_context) -> None:
    context = history_context
    party_id = context.party_service.create_party(
        PartyPayload(legal_name="Rights Recipient B.V.", display_name="Rights Recipient")
    )
    work_id = context.work_service.create_work(WorkPayload(title="Rights Work"))
    right_id = context.rights_service.create_right(
        RightPayload(
            title="Worldwide Publishing",
            right_type="composition_publishing",
            territory="Worldwide",
            work_id=work_id,
            granted_to_party_id=party_id,
        )
    )

    deleted_id = rights_controller._delete_right_with_history(context, right_id)

    assert deleted_id == right_id
    assert context.rights_service.fetch_right(right_id) is None
    delete_entry = context.history.get_current_entry()
    assert delete_entry is not None
    assert delete_entry.action_type == "right.delete"
    assert delete_entry.label == "Delete Rights Record: Worldwide Publishing"

    context.history.undo()
    restored = context.rights_service.fetch_right(right_id)
    assert restored is not None
    assert restored.granted_to_party_id == party_id
    assert restored.territory == "Worldwide"

    context.history.redo()
    assert context.rights_service.fetch_right(right_id) is None


def test_party_history_qa_probe_uses_injected_handlers_and_finishes_redone(
    history_context,
) -> None:
    context = history_context
    work_id = context.work_service.create_work(WorkPayload(title="QA Party History Work"))
    panel = SimpleNamespace()
    party_history_actions.configure_party_history_handlers(
        panel,
        context,
        party_label=party_controller._party_identity_primary_label,
    )

    evidence = qualify_party_delete_merge_history(context, panel, work_id=work_id)

    assert evidence["party_delete_redo_removed"] is True
    assert evidence["party_merge_redo_applied"] is True
    assert context.party_service.fetch_party(evidence["party_delete_transient_id"]) is None
    assert (
        context.party_service.fetch_party(evidence["party_merge_primary_transient_id"]) is not None
    )
    assert context.party_service.fetch_party(evidence["party_merge_duplicate_transient_id"]) is None
    merged_right = context.rights_service.fetch_right(evidence["party_merge_right_transient_id"])
    assert merged_right is not None
    assert merged_right.granted_to_party_id == evidence["party_merge_primary_transient_id"]
    assert context.history.get_current_entry().action_type == "party.merge"


def test_right_history_qa_probe_preserves_primary_and_finishes_redone(history_context) -> None:
    context = history_context
    party_id = context.party_service.create_party(
        PartyPayload(legal_name="QA Rights Party B.V.", display_name="QA Rights Party")
    )
    work_id = context.work_service.create_work(WorkPayload(title="QA Rights History Work"))
    primary_right_id = context.rights_service.create_right(
        RightPayload(
            title="QA Primary Right",
            right_type="sync",
            work_id=work_id,
            granted_to_party_id=party_id,
        )
    )
    panel = SimpleNamespace(
        delete_right_handler=lambda right_id: rights_controller._delete_right_with_history(
            context,
            right_id,
        )
    )

    evidence = qualify_right_delete_history(
        context,
        panel,
        party_id=party_id,
        work_id=work_id,
        track_id=0,
        release_id=0,
        contract_id=0,
        primary_right_id=primary_right_id,
    )

    assert evidence["right_delete_undo_relationships_restored"] is True
    assert evidence["right_delete_redo_removed"] is True
    assert context.rights_service.fetch_right(evidence["right_delete_transient_id"]) is None
    assert context.rights_service.fetch_right(primary_right_id) is not None
    assert context.history.get_current_entry().action_type == "right.delete"


def test_party_and_rights_controllers_inject_history_handlers(monkeypatch) -> None:
    class FakePanel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    party_calls: list[tuple[str, object]] = []
    monkeypatch.setattr(party_controller, "_party_manager_panel_class", lambda: FakePanel)
    monkeypatch.setattr(
        party_history_actions,
        "delete_parties_with_history",
        lambda _app, ids, **_kwargs: party_calls.append(("delete", list(ids))),
    )
    monkeypatch.setattr(
        party_history_actions,
        "merge_parties_with_history",
        lambda _app, primary, duplicates, **_kwargs: party_calls.append(
            ("merge", (primary, list(duplicates)))
        ),
    )
    party_host = SimpleNamespace(
        party_service=object(),
        _current_owner_party_id=lambda: None,
        _assign_owner_party=lambda _party_id: None,
        import_party_exchange_file=lambda *_args: None,
        export_party_exchange_file=lambda *_args: None,
    )
    party_panel = party_controller._create_party_manager_panel(party_host, None)
    party_panel.delete_party_handler([2, 3])
    party_panel.merge_party_handler(2, [3])
    assert party_calls == [("delete", [2, 3]), ("merge", (2, [3]))]

    rights_calls: list[int] = []
    monkeypatch.setattr(rights_controller, "_rights_browser_panel_class", lambda: FakePanel)
    monkeypatch.setattr(
        rights_controller,
        "_delete_right_with_history",
        lambda _app, right_id: rights_calls.append(int(right_id)),
    )
    rights_host = SimpleNamespace(
        rights_service=object(),
        party_service=object(),
        contract_service=object(),
    )
    rights_panel = rights_controller._create_rights_matrix_panel(rights_host, None)
    rights_panel.delete_right_handler(17)
    assert rights_calls == [17]


def test_rights_panel_reports_history_delete_failure_and_remains_usable(
    history_context,
    monkeypatch,
) -> None:
    require_qapplication()
    context = history_context
    work_id = context.work_service.create_work(WorkPayload(title="Protected Rights Work"))
    right_id = context.rights_service.create_right(
        RightPayload(title="Protected Right", right_type="sync", work_id=work_id)
    )
    critical_messages: list[tuple[str, str]] = []
    monkeypatch.setattr(rights_dialogs, "_confirm_destructive_action", lambda *_a, **_k: True)
    monkeypatch.setattr(
        rights_dialogs.QMessageBox,
        "critical",
        lambda _parent, title, message: critical_messages.append((title, message)),
    )
    panel = rights_dialogs.RightsBrowserPanel(
        rights_service_provider=lambda: context.rights_service,
        party_service_provider=lambda: None,
        contract_service_provider=lambda: None,
    )
    try:
        panel.focus_right(right_id)
        panel.delete_right_handler = lambda _right_id: (_ for _ in ()).throw(
            RuntimeError("history snapshot unavailable")
        )

        panel.delete_selected()

        assert critical_messages == [("Rights Matrix", "history snapshot unavailable")]
        assert context.rights_service.fetch_right(right_id) is not None
        assert panel.table.rowCount() == 1
        assert panel.isEnabled()
    finally:
        panel.close()
