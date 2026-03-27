# ruff: noqa: E402, I001
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from demo.build_demo_workspace import build_demo_workspace
from isrc_manager.constants import APP_NAME
from isrc_manager.starter_themes import starter_theme_library

if TYPE_CHECKING:
    from ISRC_manager import App


RUNTIME_ROOT = ROOT / "demo" / ".runtime"
SCREENSHOT_DIR = ROOT / "docs" / "screenshots"
QT_SETTINGS_ROOT = RUNTIME_ROOT / "qt-settings"


def _safe_close(widget) -> None:
    try:
        widget.close()
    except Exception:
        pass
    QApplication.processEvents()


def _show_and_capture(
    widget, target: Path, *, width: int | None = None, height: int | None = None, wait_ms: int = 250
) -> None:
    if width is not None and height is not None:
        widget.resize(width, height)
    widget.show()
    widget.raise_()
    widget.activateWindow()
    QApplication.processEvents()
    QTest.qWait(wait_ms)
    target.parent.mkdir(parents=True, exist_ok=True)
    widget.grab().save(str(target))


def _prepare_environment() -> dict[str, Path]:
    if RUNTIME_ROOT.exists():
        shutil.rmtree(RUNTIME_ROOT)
    home_root = RUNTIME_ROOT / "home"
    localapp_root = RUNTIME_ROOT / "localappdata"
    home_root.mkdir(parents=True, exist_ok=True)
    localapp_root.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(home_root)
    os.environ["LOCALAPPDATA"] = str(localapp_root)
    os.environ["TMPDIR"] = str(RUNTIME_ROOT / "tmp")
    Path(os.environ["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    return build_demo_workspace(localapp_root)


def _fake_writable_location(location) -> str:
    location_name = getattr(location, "name", str(location)).replace("/", "_")
    if location_name in {"AppDataLocation", "AppLocalDataLocation"}:
        path = Path(os.environ["LOCALAPPDATA"]) / APP_NAME
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    path = QT_SETTINGS_ROOT / location_name
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _select_first_row(window: App) -> None:
    if window.table.rowCount() <= 0:
        return
    window.table.selectRow(0)
    QApplication.processEvents()


def _apply_demo_theme(window: App, theme_name: str = "VS Code Dark") -> None:
    library = starter_theme_library()
    raw_theme = dict(library.get(theme_name) or {})
    if not raw_theme:
        return
    raw_theme["selected_name"] = theme_name
    window.theme_settings = window._normalize_theme_settings(raw_theme)
    window._apply_theme(window.theme_settings)
    QApplication.processEvents()


def _no_catalog_background_refresh(self, *args, **kwargs):
    del self, args
    on_finished = kwargs.get("on_finished")
    on_complete = kwargs.get("on_complete")
    if callable(on_finished):
        on_finished()
    if callable(on_complete):
        on_complete()
    return None


def _skip_post_ready_modal(self) -> None:
    del self
    return None


def capture() -> list[Path]:
    build_info = _prepare_environment()
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ISRC Catalog Manager Demo Capture")

    from ISRC_manager import App, CatalogManagersDialog, CustomColumnsDialog
    from isrc_manager.history.dialogs import HistoryDialog

    with (
        mock.patch.object(
            QStandardPaths,
            "writableLocation",
            side_effect=_fake_writable_location,
        ),
        mock.patch.object(
            App,
            "_refresh_catalog_ui_in_background",
            _no_catalog_background_refresh,
        ),
        mock.patch.object(
            App,
            "_schedule_owner_party_bootstrap",
            _skip_post_ready_modal,
        ),
        mock.patch.object(
            App,
            "_offer_settings_on_first_launch_if_pending",
            _skip_post_ready_modal,
        ),
    ):
        window = App()
        window.open_database(str(build_info["db_path"]))
        _apply_demo_theme(window)
        window.identity["window_title"] = "ISRC Catalog Manager Demo"
        window._apply_identity()
        window.resize(1560, 980)
        window.active_custom_fields = None
        window.add_data_dock.show()
        window.catalog_table_dock.show()
        window.add_data_dock.setFloating(False)
        window.catalog_table_dock.setFloating(False)
        window.addDockWidget(Qt.LeftDockWidgetArea, window.add_data_dock)
        window.addDockWidget(Qt.RightDockWidgetArea, window.catalog_table_dock)
        window.resizeDocks(
            [window.add_data_dock, window.catalog_table_dock],
            [520, 1040],
            Qt.Horizontal,
        )
        window.refresh_table()
        window.left_scroll.verticalScrollBar().setValue(0)
        window.table.scrollToTop()
        _select_first_row(window)

        captured: list[Path] = []

        workspace_path = SCREENSHOT_DIR / "workspace-overview.png"
        _show_and_capture(window, workspace_path, wait_ms=450)
        captured.append(workspace_path)

        managers = CatalogManagersDialog(window, initial_tab="artists", parent=window)
        managers.focus_tab("albums")
        managers.resize(1220, 780)
        managers.tabs.setCurrentIndex(1)
        managers.albums_tab.reload()
        managers_path = SCREENSHOT_DIR / "catalog-managers.png"
        _show_and_capture(managers, managers_path, wait_ms=350)
        captured.append(managers_path)
        _safe_close(managers)

        window.open_help_dialog(topic_id="overview", parent=window)
        help_dialog = window.help_dialog
        help_dialog.search_field.setText("snapshot")
        help_dialog.open_topic("history", focus_search=False)
        help_path = SCREENSHOT_DIR / "help-browser.png"
        _show_and_capture(help_dialog, help_path, width=1240, height=860, wait_ms=350)
        captured.append(help_path)
        _safe_close(help_dialog)

        history = HistoryDialog(window, parent=window)
        history.resize(1120, 680)
        history.tabs.setCurrentIndex(1)
        history.refresh_data()
        if history.history_table.rowCount() > 0:
            history.history_table.selectRow(0)
        history_path = SCREENSHOT_DIR / "history-and-snapshots.png"
        _show_and_capture(history, history_path, wait_ms=350)
        captured.append(history_path)
        _safe_close(history)

        custom_columns = CustomColumnsDialog(window.load_active_custom_fields(), parent=window)
        custom_columns.resize(760, 520)
        if custom_columns.listw.count() > 0:
            custom_columns.listw.setCurrentRow(0)
        custom_columns_path = SCREENSHOT_DIR / "custom-columns.png"
        _show_and_capture(custom_columns, custom_columns_path, wait_ms=300)
        captured.append(custom_columns_path)
        _safe_close(custom_columns)

        _safe_close(window)
    app.quit()
    return captured


def main() -> int:
    paths = capture()
    for path in paths:
        print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
