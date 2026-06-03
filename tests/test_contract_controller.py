from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from isrc_manager.contracts import ContractPayload, controller


class _FakeCursor:
    pass


class _FakeConnection:
    def __init__(self) -> None:
        self.enter_count = 0
        self.exit_count = 0
        self.cursors: list[_FakeCursor] = []

    def __enter__(self):
        self.enter_count += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.exit_count += 1
        return False

    def cursor(self) -> _FakeCursor:
        cursor = _FakeCursor()
        self.cursors.append(cursor)
        return cursor


class _FakeContractService:
    def __init__(self, *, fetched_record=None) -> None:
        self.fetched_record = fetched_record
        self.created: list[tuple[ContractPayload, _FakeCursor]] = []
        self.updated: list[tuple[int, ContractPayload, _FakeCursor]] = []
        self.deleted: list[int] = []
        self.fetches: list[int] = []

    def create_contract(self, payload: ContractPayload, *, cursor: _FakeCursor) -> int:
        self.created.append((payload, cursor))
        return 42

    def update_contract(
        self,
        contract_id: int,
        payload: ContractPayload,
        *,
        cursor: _FakeCursor,
    ) -> None:
        self.updated.append((contract_id, payload, cursor))

    def fetch_contract(self, contract_id: int):
        self.fetches.append(contract_id)
        return self.fetched_record

    def delete_contract(self, contract_id: int) -> None:
        self.deleted.append(contract_id)


class _HistoryHost:
    def __init__(self, *, service=None, conn=None) -> None:
        self.contract_service = service
        self.conn = conn
        self.history_calls: list[dict[str, object]] = []
        self.refresh_count = 0

    def _run_snapshot_history_action(self, **kwargs):
        self.history_calls.append(kwargs)
        return kwargs["mutation"]()

    def _refresh_catalog_workspace_docks(self) -> None:
        self.refresh_count += 1


def test_root_attr_uses_main_window_overrides_and_fallback(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "isrc_manager.main_window",
        SimpleNamespace(ContractBrowserPanel="panel override"),
    )

    assert controller._root_attr("ContractBrowserPanel", "fallback") == "panel override"
    assert controller._root_attr("Missing", "fallback") == "fallback"

    monkeypatch.delitem(sys.modules, "isrc_manager.main_window")
    assert controller._root_attr("Missing", "fallback") == "fallback"


def test_create_contract_manager_panel_wires_provider_handlers_and_parent(monkeypatch) -> None:
    created: dict[str, object] = {}

    class _FakePanel:
        def __init__(
            self,
            *,
            contract_service_provider,
            create_contract_handler,
            update_contract_handler,
            delete_contract_handler,
            parent,
        ) -> None:
            created["provider"] = contract_service_provider
            created["create"] = create_contract_handler
            created["update"] = update_contract_handler
            created["delete"] = delete_contract_handler
            created["parent"] = parent

    monkeypatch.setitem(
        sys.modules,
        "isrc_manager.main_window",
        SimpleNamespace(ContractBrowserPanel=_FakePanel),
    )
    service = object()
    host = SimpleNamespace(
        contract_service=service,
        _create_contract_with_history=object(),
        _update_contract_with_history=object(),
        _delete_contract_with_history=object(),
    )
    parent = object()

    panel = controller._create_contract_manager_panel(host, parent)

    assert isinstance(panel, _FakePanel)
    assert created["provider"]() is service
    assert created["create"] is host._create_contract_with_history
    assert created["update"] is host._update_contract_with_history
    assert created["delete"] is host._delete_contract_with_history
    assert created["parent"] is parent


def test_ensure_contract_manager_dock_registers_catalog_workspace_panel(monkeypatch) -> None:
    dock = object()
    calls: list[dict[str, object]] = []

    def fake_ensure_catalog_workspace_dock(host, **kwargs):
        calls.append({"host": host, **kwargs})
        return dock

    monkeypatch.setattr(
        controller,
        "ensure_catalog_workspace_dock",
        fake_ensure_catalog_workspace_dock,
    )
    host = SimpleNamespace(_create_contract_manager_panel=object())

    result = controller._ensure_contract_manager_dock(host)

    assert result is dock
    assert host.contract_manager_dock is dock
    assert calls == [
        {
            "host": host,
            "key": "contract_manager",
            "title": "Contract Manager",
            "object_name": "contractManagerDock",
            "panel_factory": host._create_contract_manager_panel,
        }
    ]


def test_open_contract_manager_warns_when_no_profile_is_open(monkeypatch) -> None:
    warnings: list[tuple[object, str, str]] = []

    class _FakeMessageBox:
        @staticmethod
        def warning(parent, title: str, message: str) -> None:
            warnings.append((parent, title, message))

    monkeypatch.setitem(
        sys.modules,
        "isrc_manager.main_window",
        SimpleNamespace(QMessageBox=_FakeMessageBox),
    )
    host = SimpleNamespace(contract_service=None)

    assert controller.open_contract_manager(host, 7) is None
    assert warnings == [(host, "Contract Manager", "Open a profile first.")]


def test_open_contract_manager_shows_workspace_panel_and_focuses_contract() -> None:
    focused: list[int | None] = []
    ensure_result = object()

    class _Panel:
        def focus_contract(self, contract_id: int | None) -> None:
            focused.append(contract_id)

    def show_workspace_panel(ensure_factory, **kwargs):
        panel = _Panel()
        kwargs["configure"](panel)
        return {
            "ensure_result": ensure_factory(),
            "panel_attr": kwargs["panel_attr"],
            "legacy_attr": kwargs["legacy_attr"],
        }

    host = SimpleNamespace(
        contract_service=object(),
        _ensure_contract_manager_dock=lambda: ensure_result,
        _show_workspace_panel=show_workspace_panel,
    )

    result = controller.open_contract_manager(host, 9)

    assert result == {
        "ensure_result": ensure_result,
        "panel_attr": "contract_manager_panel",
        "legacy_attr": "contract_manager_dialog",
    }
    assert focused == [9]


def test_create_contract_runs_inside_history_snapshot_and_refreshes_workspace() -> None:
    payload = ContractPayload(title="  Sync License  ")
    conn = _FakeConnection()
    service = _FakeContractService()
    host = _HistoryHost(service=service, conn=conn)

    contract_id = controller._create_contract_with_history(host, payload)

    assert contract_id == 42
    assert service.created == [(payload, conn.cursors[0])]
    assert conn.enter_count == 1
    assert conn.exit_count == 1
    assert host.refresh_count == 1
    assert host.history_calls[0]["action_label"] == "Create Contract: Sync License"
    assert host.history_calls[0]["action_type"] == "contract.create"
    assert host.history_calls[0]["entity_type"] == "Contract"
    assert host.history_calls[0]["payload"] == {"title": "Sync License"}


def test_update_contract_runs_inside_history_snapshot_and_refreshes_workspace() -> None:
    payload = ContractPayload(title="")
    conn = _FakeConnection()
    service = _FakeContractService()
    host = _HistoryHost(service=service, conn=conn)

    controller._update_contract_with_history(host, 11, payload)

    assert service.updated == [(11, payload, conn.cursors[0])]
    assert conn.enter_count == 1
    assert conn.exit_count == 1
    assert host.refresh_count == 1
    assert host.history_calls[0]["action_label"] == "Update Contract: Untitled Contract"
    assert host.history_calls[0]["action_type"] == "contract.update"
    assert host.history_calls[0]["entity_id"] == 11
    assert host.history_calls[0]["payload"] == {"title": ""}


@pytest.mark.parametrize(
    ("record", "expected_label", "expected_payload"),
    [
        (
            SimpleNamespace(title="  Artist Agreement  "),
            "Delete Contract: Artist Agreement",
            {"title": "Artist Agreement"},
        ),
        (None, "Delete Contract: #13", {"title": ""}),
    ],
)
def test_delete_contract_runs_inside_history_snapshot_and_refreshes_workspace(
    record,
    expected_label: str,
    expected_payload: dict[str, str],
) -> None:
    conn = _FakeConnection()
    service = _FakeContractService(fetched_record=record)
    host = _HistoryHost(service=service, conn=conn)

    controller._delete_contract_with_history(host, 13)

    assert service.fetches == [13]
    assert service.deleted == [13]
    assert conn.enter_count == 1
    assert conn.exit_count == 1
    assert host.refresh_count == 1
    assert host.history_calls[0]["action_label"] == expected_label
    assert host.history_calls[0]["action_type"] == "contract.delete"
    assert host.history_calls[0]["entity_id"] == 13
    assert host.history_calls[0]["payload"] == expected_payload


@pytest.mark.parametrize(
    ("function_name", "args"),
    [
        ("_create_contract_with_history", (ContractPayload(title="New"),)),
        ("_update_contract_with_history", (1, ContractPayload(title="Edit"))),
        ("_delete_contract_with_history", (1,)),
    ],
)
@pytest.mark.parametrize(
    "host",
    [
        _HistoryHost(service=None, conn=_FakeConnection()),
        _HistoryHost(service=_FakeContractService(), conn=None),
    ],
)
def test_contract_mutations_raise_when_service_or_connection_is_unavailable(
    function_name: str,
    args: tuple[object, ...],
    host: _HistoryHost,
) -> None:
    with pytest.raises(ValueError, match="Contract service is unavailable."):
        getattr(controller, function_name)(host, *args)
