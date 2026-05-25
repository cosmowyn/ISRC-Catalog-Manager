from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from isrc_manager import catalog_managers
from isrc_manager.catalog_managers import (
    CatalogManagersPanel,
    DiagnosticsCatalogCleanupPanel,
    _CatalogAlbumsPane,
    _CatalogArtistsPane,
)
from tests.qt_test_helpers import require_qapplication


def _artist(**overrides):
    values = {
        "artist_id": 1,
        "name": "Unused Artist",
        "main_uses": 0,
        "extra_uses": 0,
        "total_uses": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _album(**overrides):
    values = {
        "album_id": 10,
        "title": "Unused Album",
        "uses": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _yes_message_box(monkeypatch, messages: list[tuple[str, tuple]] | None = None) -> None:
    messages = messages if messages is not None else []

    monkeypatch.setattr(catalog_managers.QMessageBox, "Yes", 1)
    monkeypatch.setattr(catalog_managers.QMessageBox, "No", 2)
    monkeypatch.setattr(
        catalog_managers.QMessageBox,
        "question",
        lambda *args: catalog_managers.QMessageBox.Yes,
    )
    monkeypatch.setattr(
        catalog_managers.QMessageBox,
        "information",
        lambda *args: messages.append(("information", args)),
    )
    monkeypatch.setattr(
        catalog_managers.QMessageBox,
        "warning",
        lambda *args: messages.append(("warning", args)),
    )


def test_artist_pane_reload_marks_usage_and_selected_unused_ids():
    require_qapplication()
    service = SimpleNamespace(
        list_artists_with_usage=mock.Mock(
            return_value=[
                _artist(artist_id=1, name="Unused Artist"),
                _artist(
                    artist_id=2,
                    name="Used Artist",
                    main_uses=1,
                    extra_uses=1,
                    total_uses=2,
                ),
            ]
        )
    )
    pane = _CatalogArtistsPane(SimpleNamespace(catalog_service=service))

    assert pane.table.rowCount() == 2
    assert pane.summary_label.text() == "2 stored artist(s). 1 currently unused and safe to remove."
    assert pane.table.item(0, 4).text() == "Unused"
    assert pane.table.item(0, 5).checkState() == Qt.Checked
    assert pane.table.item(1, 4).text() == "In Use"
    assert pane.table.item(1, 5).flags() == Qt.NoItemFlags
    assert pane._selected_unused_ids() == [1]

    pane.table.item(0, 3).setText("not-a-number")
    assert pane._selected_unused_ids() == []


def test_artist_delete_and_purge_use_snapshot_history_and_refresh(monkeypatch):
    require_qapplication()
    messages = []
    _yes_message_box(monkeypatch, messages)
    service = SimpleNamespace(
        list_artists_with_usage=mock.Mock(return_value=[_artist(artist_id=7)]),
        delete_artists=mock.Mock(),
    )
    history_calls = []

    def run_snapshot_history_action(**kwargs):
        history_calls.append(kwargs)
        return kwargs["mutation"]()

    app = SimpleNamespace(
        catalog_service=service,
        populate_all_comboboxes=mock.Mock(),
        _run_snapshot_history_action=run_snapshot_history_action,
    )
    pane = _CatalogArtistsPane(app)

    pane._delete_selected()
    pane._purge_unused()

    assert [call.args[0] for call in service.delete_artists.call_args_list] == [[7], [7]]
    assert [call["action_type"] for call in history_calls] == [
        "catalog.artists_delete",
        "catalog.artists_purge",
    ]
    assert app.populate_all_comboboxes.call_count == 2
    assert messages == []


def test_artist_pane_handles_missing_service_and_empty_selection(monkeypatch):
    require_qapplication()
    messages = []
    _yes_message_box(monkeypatch, messages)
    pane = _CatalogArtistsPane(SimpleNamespace(catalog_service=None))

    assert pane.summary_label.text() == "Open a profile to manage stored artists."
    pane._delete_selected()
    pane._purge_unused()

    assert messages[0][0] == "information"
    assert messages[1][0] == "warning"


def test_album_pane_reload_delete_and_purge_background_paths(monkeypatch):
    require_qapplication()
    _yes_message_box(monkeypatch)
    service = SimpleNamespace(
        list_albums_with_usage=mock.Mock(
            return_value=[
                _album(album_id=11, title="Unused Album"),
                _album(album_id=12, title="Used Album", uses=3),
            ]
        ),
        delete_albums=mock.Mock(),
    )
    background_calls = []

    def delete_unused_albums_in_background(album_ids, **kwargs):
        background_calls.append((album_ids, kwargs))
        kwargs["on_ui_ready"]()

    app = SimpleNamespace(
        catalog_service=service,
        populate_all_comboboxes=mock.Mock(),
        _delete_unused_albums_in_background=delete_unused_albums_in_background,
    )
    pane = _CatalogAlbumsPane(app)

    assert (
        pane.summary_label.text()
        == "2 stored album title(s). 1 currently unused and safe to remove."
    )
    assert pane.table.item(0, 2).text() == "Unused"
    assert pane.table.item(1, 3).flags() == Qt.NoItemFlags
    assert pane._selected_unused_ids() == [11]

    pane._delete_selected()
    pane._purge_unused()

    assert [call[0] for call in background_calls] == [[11], [11]]
    assert [call[1]["action_type"] for call in background_calls] == [
        "catalog.albums_delete",
        "catalog.albums_purge",
    ]
    assert app.populate_all_comboboxes.call_count == 2


def test_album_pane_fallback_delete_without_background_and_empty_selection(monkeypatch):
    require_qapplication()
    messages = []
    _yes_message_box(monkeypatch, messages)
    service = SimpleNamespace(
        list_albums_with_usage=mock.Mock(return_value=[_album(album_id=20)]),
        delete_albums=mock.Mock(),
    )
    app = SimpleNamespace(catalog_service=service, populate_all_comboboxes=mock.Mock())
    pane = _CatalogAlbumsPane(app)

    pane._delete_selected()
    service.delete_albums.assert_called_once_with([20])
    app.populate_all_comboboxes.assert_called_once()

    pane.table.item(0, 1).setText("invalid")
    pane._delete_selected()
    assert messages[-1][0] == "information"


def test_catalog_manager_panels_focus_known_and_unknown_tabs(monkeypatch):
    require_qapplication()
    monkeypatch.setattr(
        catalog_managers,
        "_apply_standard_widget_chrome",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(catalog_managers, "_compose_widget_stylesheet", lambda *args: "")
    monkeypatch.setattr(catalog_managers, "_create_round_help_button", lambda *args: QWidget())

    service = SimpleNamespace(
        list_artists_with_usage=mock.Mock(return_value=[]),
        list_albums_with_usage=mock.Mock(return_value=[]),
    )
    app = SimpleNamespace(catalog_service=service, populate_all_comboboxes=mock.Mock())
    parent = QWidget()

    diagnostics = DiagnosticsCatalogCleanupPanel(app, parent=parent)
    diagnostics.focus_tab("albums")
    assert diagnostics.tabs.currentIndex() == 1
    diagnostics.focus_tab("unknown")
    assert diagnostics.tabs.currentIndex() == 0

    panel = CatalogManagersPanel(app, initial_tab="albums", parent=parent)
    assert panel.tabs.currentIndex() == 1
    panel.focus_tab("missing")
    assert panel.tabs.currentIndex() == 0
    panel.refresh()
    assert service.list_artists_with_usage.call_count >= 3
    assert service.list_albums_with_usage.call_count >= 3
