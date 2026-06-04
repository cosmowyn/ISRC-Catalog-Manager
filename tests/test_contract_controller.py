from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest import mock

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


class ContractControllerTests(unittest.TestCase):
    def test_root_attr_uses_main_window_overrides_and_fallback(self) -> None:
        with mock.patch.dict(
            sys.modules,
            {"isrc_manager.main_window": SimpleNamespace(ContractBrowserPanel="panel override")},
        ):
            self.assertEqual(
                controller._root_attr("ContractBrowserPanel", "fallback"),
                "panel override",
            )
            self.assertEqual(controller._root_attr("Missing", "fallback"), "fallback")

        self.assertEqual(controller._root_attr("Missing", "fallback"), "fallback")

    def test_create_contract_manager_panel_wires_provider_handlers_and_parent(self) -> None:
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

        with mock.patch.dict(
            sys.modules,
            {"isrc_manager.main_window": SimpleNamespace(ContractBrowserPanel=_FakePanel)},
        ):
            service = object()
            host = SimpleNamespace(
                contract_service=service,
                _create_contract_with_history=object(),
                _update_contract_with_history=object(),
                _delete_contract_with_history=object(),
            )
            parent = object()

            panel = controller._create_contract_manager_panel(host, parent)

        self.assertIsInstance(panel, _FakePanel)
        self.assertIs(created["provider"](), service)
        self.assertIs(created["create"], host._create_contract_with_history)
        self.assertIs(created["update"], host._update_contract_with_history)
        self.assertIs(created["delete"], host._delete_contract_with_history)
        self.assertIs(created["parent"], parent)

    def test_ensure_contract_manager_dock_registers_catalog_workspace_panel(self) -> None:
        dock = object()
        calls: list[dict[str, object]] = []

        def fake_ensure_catalog_workspace_dock(host, **kwargs):
            calls.append({"host": host, **kwargs})
            return dock

        with mock.patch.object(
            controller,
            "ensure_catalog_workspace_dock",
            fake_ensure_catalog_workspace_dock,
        ):
            host = SimpleNamespace(_create_contract_manager_panel=object())

            result = controller._ensure_contract_manager_dock(host)

        self.assertIs(result, dock)
        self.assertIs(host.contract_manager_dock, dock)
        self.assertEqual(
            calls,
            [
                {
                    "host": host,
                    "key": "contract_manager",
                    "title": "Contract Manager",
                    "object_name": "contractManagerDock",
                    "panel_factory": host._create_contract_manager_panel,
                }
            ],
        )

    def test_open_contract_manager_warns_when_no_profile_is_open(self) -> None:
        warnings: list[tuple[object, str, str]] = []

        class _FakeMessageBox:
            @staticmethod
            def warning(parent, title: str, message: str) -> None:
                warnings.append((parent, title, message))

        with mock.patch.dict(
            sys.modules,
            {"isrc_manager.main_window": SimpleNamespace(QMessageBox=_FakeMessageBox)},
        ):
            host = SimpleNamespace(contract_service=None)

            self.assertIsNone(controller.open_contract_manager(host, 7))

        self.assertEqual(warnings, [(host, "Contract Manager", "Open a profile first.")])

    def test_open_contract_manager_shows_workspace_panel_and_focuses_contract(self) -> None:
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

        self.assertEqual(
            result,
            {
                "ensure_result": ensure_result,
                "panel_attr": "contract_manager_panel",
                "legacy_attr": "contract_manager_dialog",
            },
        )
        self.assertEqual(focused, [9])

    def test_create_contract_runs_inside_history_snapshot_and_refreshes_workspace(self) -> None:
        payload = ContractPayload(title="  Sync License  ")
        conn = _FakeConnection()
        service = _FakeContractService()
        host = _HistoryHost(service=service, conn=conn)

        contract_id = controller._create_contract_with_history(host, payload)

        self.assertEqual(contract_id, 42)
        self.assertEqual(service.created, [(payload, conn.cursors[0])])
        self.assertEqual(conn.enter_count, 1)
        self.assertEqual(conn.exit_count, 1)
        self.assertEqual(host.refresh_count, 1)
        self.assertEqual(host.history_calls[0]["action_label"], "Create Contract: Sync License")
        self.assertEqual(host.history_calls[0]["action_type"], "contract.create")
        self.assertEqual(host.history_calls[0]["entity_type"], "Contract")
        self.assertEqual(host.history_calls[0]["payload"], {"title": "Sync License"})

    def test_update_contract_runs_inside_history_snapshot_and_refreshes_workspace(self) -> None:
        payload = ContractPayload(title="")
        conn = _FakeConnection()
        service = _FakeContractService()
        host = _HistoryHost(service=service, conn=conn)

        controller._update_contract_with_history(host, 11, payload)

        self.assertEqual(service.updated, [(11, payload, conn.cursors[0])])
        self.assertEqual(conn.enter_count, 1)
        self.assertEqual(conn.exit_count, 1)
        self.assertEqual(host.refresh_count, 1)
        self.assertEqual(
            host.history_calls[0]["action_label"],
            "Update Contract: Untitled Contract",
        )
        self.assertEqual(host.history_calls[0]["action_type"], "contract.update")
        self.assertEqual(host.history_calls[0]["entity_id"], 11)
        self.assertEqual(host.history_calls[0]["payload"], {"title": ""})

    def test_delete_contract_runs_inside_history_snapshot_and_refreshes_workspace(self) -> None:
        cases = [
            (
                SimpleNamespace(title="  Artist Agreement  "),
                "Delete Contract: Artist Agreement",
                {"title": "Artist Agreement"},
            ),
            (None, "Delete Contract: #13", {"title": ""}),
        ]
        for record, expected_label, expected_payload in cases:
            with self.subTest(record=record):
                conn = _FakeConnection()
                service = _FakeContractService(fetched_record=record)
                host = _HistoryHost(service=service, conn=conn)

                controller._delete_contract_with_history(host, 13)

                self.assertEqual(service.fetches, [13])
                self.assertEqual(service.deleted, [13])
                self.assertEqual(conn.enter_count, 1)
                self.assertEqual(conn.exit_count, 1)
                self.assertEqual(host.refresh_count, 1)
                self.assertEqual(host.history_calls[0]["action_label"], expected_label)
                self.assertEqual(host.history_calls[0]["action_type"], "contract.delete")
                self.assertEqual(host.history_calls[0]["entity_id"], 13)
                self.assertEqual(host.history_calls[0]["payload"], expected_payload)

    def test_contract_mutations_raise_when_service_or_connection_is_unavailable(self) -> None:
        functions = [
            ("_create_contract_with_history", (ContractPayload(title="New"),)),
            ("_update_contract_with_history", (1, ContractPayload(title="Edit"))),
            ("_delete_contract_with_history", (1,)),
        ]
        hosts = [
            _HistoryHost(service=None, conn=_FakeConnection()),
            _HistoryHost(service=_FakeContractService(), conn=None),
        ]
        for function_name, args in functions:
            for host in hosts:
                with self.subTest(function_name=function_name, host=host):
                    with self.assertRaisesRegex(
                        ValueError,
                        "Contract service is unavailable.",
                    ):
                        getattr(controller, function_name)(host, *args)
