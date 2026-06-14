from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest import mock

from isrc_manager.assets import controller as asset_controller
from isrc_manager.contract_templates import controller as contract_template_controller
from isrc_manager.rights import controller as rights_controller


class _FakeMessageBox:
    warnings: list[tuple[object, str, str]] = []

    @classmethod
    def warning(cls, parent, title: str, message: str) -> None:
        cls.warnings.append((parent, title, message))


def setup_function() -> None:
    _FakeMessageBox.warnings.clear()


def test_asset_registry_controller_uses_root_overrides_and_workspace_panel() -> None:
    class _FakeAssetPanel:
        def __init__(self, *, asset_service_provider, drill_in_host_provider, parent) -> None:
            self.asset_service_provider = asset_service_provider
            self.drill_in_host_provider = drill_in_host_provider
            self.parent = parent
            self.focused: list[int | None] = []

        def focus_asset(self, asset_id: int | None) -> None:
            self.focused.append(asset_id)

    dock = object()
    dock_calls: list[dict[str, object]] = []
    shown: dict[str, object] = {}

    def fake_ensure_catalog_workspace_dock(host, **kwargs):
        dock_calls.append({"host": host, **kwargs})
        return dock

    def fake_show_workspace_panel(ensure_factory, **kwargs):
        panel = _FakeAssetPanel(
            asset_service_provider=lambda: "unused",
            drill_in_host_provider=lambda: "unused",
            parent="shown parent",
        )
        kwargs["configure"](panel)
        shown.update(kwargs)
        shown["ensure_result"] = ensure_factory()
        shown["panel"] = panel
        return panel

    host = SimpleNamespace(
        asset_service=object(),
        _create_asset_registry_panel=lambda parent: asset_controller._create_asset_registry_panel(
            host, parent
        ),
        _ensure_asset_registry_dock=lambda: asset_controller._ensure_asset_registry_dock(host),
        _show_workspace_panel=fake_show_workspace_panel,
    )
    with (
        mock.patch.dict(
            sys.modules,
            {
                "isrc_manager.main_window": SimpleNamespace(
                    AssetBrowserPanel=_FakeAssetPanel,
                    QMessageBox=_FakeMessageBox,
                )
            },
        ),
        mock.patch.object(
            asset_controller,
            "ensure_catalog_workspace_dock",
            fake_ensure_catalog_workspace_dock,
        ),
    ):
        panel = asset_controller._create_asset_registry_panel(host, "parent")
        opened = asset_controller.open_asset_registry(host, 12)

    assert isinstance(panel, _FakeAssetPanel)
    assert panel.asset_service_provider() is host.asset_service
    assert panel.drill_in_host_provider() is host
    assert panel.parent == "parent"
    assert opened is shown["panel"]
    assert opened.focused == [12]
    assert shown["panel_attr"] == "asset_registry_panel"
    assert shown["legacy_attr"] == "asset_browser_dialog"
    assert shown["ensure_result"] is dock
    assert host.asset_registry_dock is dock
    assert dock_calls == [
        {
            "host": host,
            "key": "asset_registry",
            "title": "Deliverables and Asset Versions",
            "object_name": "assetRegistryDock",
            "panel_factory": host._create_asset_registry_panel,
            "retabify_when_shown": True,
        }
    ]


def test_asset_registry_controller_warns_without_profile() -> None:
    host = SimpleNamespace(asset_service=None)

    with mock.patch.dict(
        sys.modules,
        {"isrc_manager.main_window": SimpleNamespace(QMessageBox=_FakeMessageBox)},
    ):
        assert asset_controller.open_asset_registry(host, 4) is None

    assert _FakeMessageBox.warnings == [(host, "Asset Registry", "Open a profile first.")]


def test_contract_template_workspace_controller_wires_services_and_focuses_tab() -> None:
    class _FakeTemplatePanel:
        def __init__(
            self,
            *,
            catalog_service_provider,
            template_service_provider,
            form_service_provider,
            export_service_provider,
            parent,
        ) -> None:
            self.catalog_service_provider = catalog_service_provider
            self.template_service_provider = template_service_provider
            self.form_service_provider = form_service_provider
            self.export_service_provider = export_service_provider
            self.parent = parent
            self.focused: list[str] = []

        def focus_tab(self, tab_name: str) -> None:
            self.focused.append(tab_name)

    dock = object()
    dock_calls: list[dict[str, object]] = []

    def fake_ensure_catalog_workspace_dock(host, **kwargs):
        dock_calls.append({"host": host, **kwargs})
        return dock

    def fake_show_workspace_panel(ensure_factory, **kwargs):
        panel = _FakeTemplatePanel(
            catalog_service_provider=lambda: "unused",
            template_service_provider=lambda: "unused",
            form_service_provider=lambda: "unused",
            export_service_provider=lambda: "unused",
            parent="shown parent",
        )
        kwargs["configure"](panel)
        return {
            "panel": panel,
            "ensure_result": ensure_factory(),
            "panel_attr": kwargs["panel_attr"],
        }

    host = SimpleNamespace(
        contract_template_catalog_service=object(),
        contract_template_service=object(),
        contract_template_form_service=object(),
        contract_template_export_service=object(),
        _create_contract_template_workspace_panel=lambda parent: (
            contract_template_controller._create_contract_template_workspace_panel(host, parent)
        ),
        _ensure_contract_template_workspace_dock=lambda: (
            contract_template_controller._ensure_contract_template_workspace_dock(host)
        ),
        _show_workspace_panel=fake_show_workspace_panel,
    )
    with (
        mock.patch.dict(
            sys.modules,
            {
                "isrc_manager.main_window": SimpleNamespace(
                    ContractTemplateWorkspacePanel=_FakeTemplatePanel,
                    QMessageBox=_FakeMessageBox,
                )
            },
        ),
        mock.patch.object(
            contract_template_controller,
            "ensure_catalog_workspace_dock",
            fake_ensure_catalog_workspace_dock,
        ),
    ):
        panel = contract_template_controller._create_contract_template_workspace_panel(
            host, "parent"
        )
        opened = contract_template_controller.open_contract_template_workspace(
            host, initial_tab="fill"
        )

    assert isinstance(panel, _FakeTemplatePanel)
    assert panel.catalog_service_provider() is host.contract_template_catalog_service
    assert panel.template_service_provider() is host.contract_template_service
    assert panel.form_service_provider() is host.contract_template_form_service
    assert panel.export_service_provider() is host.contract_template_export_service
    assert panel.parent == "parent"
    assert opened["panel"].focused == ["fill"]
    assert opened["ensure_result"] is dock
    assert opened["panel_attr"] == "contract_template_workspace_panel"
    assert host.contract_template_workspace_dock is dock
    assert dock_calls == [
        {
            "host": host,
            "key": "contract_template_workspace",
            "title": "Template Workspace",
            "object_name": "contractTemplateWorkspaceDock",
            "panel_factory": host._create_contract_template_workspace_panel,
        }
    ]


def test_contract_template_workspace_controller_warns_when_any_service_missing() -> None:
    host = SimpleNamespace(
        contract_template_catalog_service=object(),
        contract_template_service=None,
        contract_template_form_service=object(),
        contract_template_export_service=object(),
    )

    with mock.patch.dict(
        sys.modules,
        {"isrc_manager.main_window": SimpleNamespace(QMessageBox=_FakeMessageBox)},
    ):
        assert contract_template_controller.open_contract_template_workspace(host) is None

    assert _FakeMessageBox.warnings == [(host, "Template Workspace", "Open a profile first.")]


def test_rights_matrix_controller_wires_services_and_workspace_panel() -> None:
    class _FakeRightsPanel:
        def __init__(
            self,
            *,
            rights_service_provider,
            party_service_provider,
            contract_service_provider,
            parent,
        ) -> None:
            self.rights_service_provider = rights_service_provider
            self.party_service_provider = party_service_provider
            self.contract_service_provider = contract_service_provider
            self.parent = parent
            self.focused: list[int | None] = []

        def focus_right(self, right_id: int | None) -> None:
            self.focused.append(right_id)

    dock = object()
    dock_calls: list[dict[str, object]] = []

    def fake_ensure_catalog_workspace_dock(host, **kwargs):
        dock_calls.append({"host": host, **kwargs})
        return dock

    def fake_show_workspace_panel(ensure_factory, **kwargs):
        panel = _FakeRightsPanel(
            rights_service_provider=lambda: "unused",
            party_service_provider=lambda: "unused",
            contract_service_provider=lambda: "unused",
            parent="shown parent",
        )
        kwargs["configure"](panel)
        return {
            "panel": panel,
            "ensure_result": ensure_factory(),
            "panel_attr": kwargs["panel_attr"],
            "legacy_attr": kwargs["legacy_attr"],
        }

    host = SimpleNamespace(
        rights_service=object(),
        party_service=object(),
        contract_service=object(),
        _create_rights_matrix_panel=lambda parent: rights_controller._create_rights_matrix_panel(
            host, parent
        ),
        _ensure_rights_matrix_dock=lambda: rights_controller._ensure_rights_matrix_dock(host),
        _show_workspace_panel=fake_show_workspace_panel,
    )
    with (
        mock.patch.dict(
            sys.modules,
            {
                "isrc_manager.main_window": SimpleNamespace(
                    RightsBrowserPanel=_FakeRightsPanel,
                    QMessageBox=_FakeMessageBox,
                )
            },
        ),
        mock.patch.object(
            rights_controller,
            "ensure_catalog_workspace_dock",
            fake_ensure_catalog_workspace_dock,
        ),
    ):
        panel = rights_controller._create_rights_matrix_panel(host, "parent")
        opened = rights_controller.open_rights_matrix(host, 21)

    assert isinstance(panel, _FakeRightsPanel)
    assert panel.rights_service_provider() is host.rights_service
    assert panel.party_service_provider() is host.party_service
    assert panel.contract_service_provider() is host.contract_service
    assert panel.parent == "parent"
    assert opened["panel"].focused == [21]
    assert opened["ensure_result"] is dock
    assert opened["panel_attr"] == "rights_matrix_panel"
    assert opened["legacy_attr"] == "rights_browser_dialog"
    assert host.rights_matrix_dock is dock
    assert dock_calls == [
        {
            "host": host,
            "key": "rights_matrix",
            "title": "Rights Matrix",
            "object_name": "rightsMatrixDock",
            "panel_factory": host._create_rights_matrix_panel,
        }
    ]


def test_rights_matrix_controller_warns_when_a_required_service_is_missing() -> None:
    host = SimpleNamespace(
        rights_service=object(),
        party_service=None,
        contract_service=object(),
    )

    with mock.patch.dict(
        sys.modules,
        {"isrc_manager.main_window": SimpleNamespace(QMessageBox=_FakeMessageBox)},
    ):
        assert rights_controller.open_rights_matrix(host) is None

    assert _FakeMessageBox.warnings == [(host, "Rights Matrix", "Open a profile first.")]
