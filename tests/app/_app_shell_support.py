import io
import json
import os
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isrc_manager.constants import APP_NAME
from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.media.derivatives import DerivativeLedgerService
from isrc_manager.paths import AppStorageLayout
from isrc_manager.services import (
    AssetVersionPayload,
    ContractPayload,
    ContractTemplatePayload,
    ContractTemplateRevisionPayload,
    DatabaseSchemaService,
    DatabaseSessionService,
    PartyPayload,
    RightPayload,
    TrackCreatePayload,
    TrackUpdatePayload,
)
from isrc_manager.starter_themes import starter_theme_names
from isrc_manager.startup_progress import StartupPhase, startup_phase_label
from tests.contract_templates._support import (
    FakeDocxHtmlAdapter,
    FakePagesAdapter,
    make_docx_bytes,
)
from tests.qt_test_helpers import pump_events, require_qapplication, wait_for

try:
    from PySide6.QtCore import QBuffer, QDate, QIODevice, QPoint, Qt
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QScrollArea, QTabBar

    import ISRC_manager as app_module
    from isrc_manager.qss_reference import collect_qss_reference_entries
except Exception as exc:  # pragma: no cover - environment-specific fallback
    app_module = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None


def _no_catalog_background_refresh(self, *args, **kwargs):
    on_finished = kwargs.get("on_finished")
    on_complete = kwargs.get("on_complete")
    if callable(on_finished):
        on_finished()
    if callable(on_complete):
        on_complete()
    return None


def _fast_test_apply_theme(self, raw_values=None):
    del self, raw_values
    return None


def _skip_owner_bootstrap(self):
    del self
    return None


class _DeferredMigrationMessageBox:
    Warning = object()
    Information = object()
    Critical = object()
    AcceptRole = object()
    RejectRole = object()
    last_text = ""
    active_splash = None
    suspended_during_exec = False
    messages_during_exec: list[str] = []
    exec_count = 0

    def __init__(self, *_args, **_kwargs):
        self._migrate_button = None
        self._keep_button = None
        self._clicked_button = None

    def setWindowTitle(self, _title):
        return None

    def setWindowModality(self, _modality):
        return None

    def setIcon(self, _icon):
        return None

    def setText(self, text):
        type(self).last_text = str(text)

    def addButton(self, label, _role):
        button = object()
        if "Keep Current Folder For Now" in label:
            self._keep_button = button
        else:
            self._migrate_button = button
        return button

    def setDefaultButton(self, _button):
        return None

    def exec(self):
        type(self).exec_count += 1
        splash = type(self).active_splash
        type(self).suspended_during_exec = bool(
            getattr(splash, "suspended", False) if splash is not None else False
        )
        type(self).messages_during_exec = list(getattr(splash, "messages", []))
        self._clicked_button = self._keep_button

    def clickedButton(self):
        return self._clicked_button


class _AcceptMigrationMessageBox(_DeferredMigrationMessageBox):
    def exec(self):
        type(self).exec_count += 1
        splash = type(self).active_splash
        type(self).suspended_during_exec = bool(
            getattr(splash, "suspended", False) if splash is not None else False
        )
        type(self).messages_during_exec = list(getattr(splash, "messages", []))
        self._clicked_button = self._migrate_button


class _FakeStartupSplashController:
    def __init__(self):
        self.phase_updates: list[tuple[object, str]] = []
        self.progress_updates: list[tuple[int, object | None, str]] = []
        self.messages: list[str] = []
        self.finish_calls: list[object] = []
        self.show_calls = 0
        self.suspend_calls = 0
        self.resume_calls = 0
        self.suspended = False
        self._finished = False
        self.current_phase = None
        self.current_message = ""
        self.current_progress = 0

    def show(self):
        self.show_calls += 1

    def set_phase(self, phase, message_override=None):
        self.current_phase = phase
        message = str(message_override or startup_phase_label(StartupPhase(phase)))
        self.current_message = message
        self.phase_updates.append((phase, message))
        self.messages.append(message)

    def set_status(self, message):
        self.current_message = str(message)
        self.messages.append(self.current_message)

    def report_progress(self, progress, message_override=None, *, phase=None):
        if phase is not None:
            self.current_phase = phase
        self.current_progress = max(self.current_progress, int(progress))
        if message_override is not None:
            message = str(message_override)
        elif self.current_phase is not None:
            message = startup_phase_label(StartupPhase(self.current_phase))
        else:
            message = ""
        self.current_message = message
        self.phase_updates.append((self.current_phase, message))
        self.progress_updates.append((self.current_progress, self.current_phase, message))
        self.messages.append(message)

    def suspend(self):
        self.suspended = True
        self.suspend_calls += 1

    def resume(self):
        self.suspended = False
        self.resume_calls += 1

    def finish(self, window):
        if self._finished:
            return
        self._finished = True
        self.current_phase = StartupPhase.READY
        self.current_progress = max(self.current_progress, 100)
        self.current_message = startup_phase_label(StartupPhase.READY)
        self.finish_calls.append(window)


class _FakeWheelEvent:
    def __init__(
        self,
        *,
        angle_x: int = 0,
        angle_y: int = 0,
        pixel_x: int = 0,
        pixel_y: int = 0,
        modifiers=Qt.NoModifier,
    ):
        self._angle_delta = QPoint(angle_x, angle_y)
        self._pixel_delta = QPoint(pixel_x, pixel_y)
        self._modifiers = modifiers
        self.accepted = False
        self.ignored = False

    def angleDelta(self):
        return self._angle_delta

    def pixelDelta(self):
        return self._pixel_delta

    def type(self):
        return app_module.QEvent.Wheel

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


class _FakeNativeGestureEvent:
    def __init__(self, gesture_type, value=0.0):
        self._gesture_type = gesture_type
        self._value = float(value)
        self.accepted = False

    def type(self):
        return app_module.QEvent.NativeGesture

    def gestureType(self):
        return self._gesture_type

    def value(self):
        return self._value

    def accept(self):
        self.accepted = True


class _FakeMouseDoubleClickEvent:
    def __init__(self, button=Qt.LeftButton):
        self._button = button
        self.accepted = False

    def type(self):
        return app_module.QEvent.MouseButtonDblClick

    def button(self):
        return self._button

    def accept(self):
        self.accepted = True


class AppShellTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if app_module is None:
            raise unittest.SkipTest(f"ISRC_manager import unavailable: {APP_IMPORT_ERROR}")
        cls.app = require_qapplication()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.local_appdata = self.root / "local-appdata"
        self.qt_settings_root = self.root / "qt-settings"
        self._patchers = [
            mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.local_appdata)}, clear=False),
            mock.patch.object(
                app_module.QStandardPaths,
                "writableLocation",
                side_effect=self._fake_writable_location,
            ),
            mock.patch.object(
                app_module.App,
                "_refresh_catalog_ui_in_background",
                _no_catalog_background_refresh,
            ),
            mock.patch.object(
                app_module.App, "_schedule_owner_party_bootstrap", _skip_owner_bootstrap
            ),
            mock.patch.object(app_module.App, "_apply_theme", _fast_test_apply_theme),
        ]
        for patcher in self._patchers:
            patcher.start()
        self._set_first_launch_prompt_pending(False)
        self._open_window(skip_background_prepare=True)

    def tearDown(self):
        try:
            if getattr(self, "window", None) is not None:
                self._close_window()
        finally:
            for patcher in reversed(getattr(self, "_patchers", [])):
                patcher.stop()
            self.tmpdir.cleanup()

    def _fake_writable_location(self, location):
        location_name = getattr(location, "name", str(location)).replace("/", "_")
        path = self.qt_settings_root / location_name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _drain_events(self, cycles: int = 4) -> None:
        pump_events(app=self.app, cycles=cycles)

    def _cancel_background_tasks(self, window) -> None:
        task_manager = getattr(window, "background_tasks", None)
        if task_manager is None:
            return
        for record in list(getattr(task_manager, "_tasks", {}).values()):
            record.context.cancel()
        if task_manager.has_running_tasks():
            wait_for(
                lambda: not task_manager.has_running_tasks(),
                timeout_ms=1500,
                interval_ms=10,
                app=self.app,
                description="app shell background tasks to finish",
            )

    def _close_window(self) -> str:
        window = getattr(self, "window", None)
        if window is None:
            return ""
        settings_path = window.settings.fileName()
        self._cancel_background_tasks(window)
        top_level_widgets = [widget for widget in self.app.topLevelWidgets() if widget is not None]
        active_modal = self.app.activeModalWidget()
        active_popup = self.app.activePopupWidget()
        for extra_widget in (active_modal, active_popup):
            if extra_widget is not None and extra_widget not in top_level_widgets:
                top_level_widgets.append(extra_widget)
        if window not in top_level_widgets:
            top_level_widgets.append(window)

        for widget in top_level_widgets:
            try:
                widget.close()
            except Exception:
                pass
        self._drain_events(cycles=6)

        try:
            window._close_database_connection()
        except Exception:
            pass

        for widget in reversed(top_level_widgets):
            delete_later = getattr(widget, "deleteLater", None)
            if callable(delete_later):
                try:
                    delete_later()
                except Exception:
                    pass
        self._drain_events(cycles=8)
        self.window = None
        return settings_path

    def _open_window(self, *, skip_background_prepare: bool = False):
        if skip_background_prepare:
            with mock.patch.object(
                app_module.App,
                "_prepare_database_for_open_blocking",
                return_value=False,
            ):
                self.window = app_module.App()
        else:
            self.window = app_module.App()
        self.window.show()
        self._drain_events()
        return self.window

    def _reopen_window(self, *, skip_background_prepare: bool = False):
        self._close_window()
        return self._open_window(skip_background_prepare=skip_background_prepare)

    def _settings_path(self) -> Path:
        return self.qt_settings_root / "AppDataLocation" / "settings.ini"

    def _settings(self):
        settings = app_module.QSettings(str(self._settings_path()), app_module.QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        return settings

    def _run_bundle_task_inline(self, window, **kwargs):
        class _InlineTaskContext:
            def set_status(self, _message):
                return None

            def report_progress(self, *args, **kwargs):
                del args, kwargs
                return None

            def is_cancelled(self):
                return False

            def raise_if_cancelled(self):
                return None

        class _InlineUiProgress:
            def set_status(self, _message):
                return None

            def report_progress(self, *args, **kwargs):
                del args, kwargs
                return None

        if hasattr(window, "_prepare_for_background_db_task"):
            window._prepare_for_background_db_task()
        with window.background_service_factory.open_bundle() as bundle:
            result = kwargs["task_fn"](bundle, _InlineTaskContext())
        on_success_before_cleanup = kwargs.get("on_success_before_cleanup")
        if callable(on_success_before_cleanup):
            on_success_before_cleanup(result, _InlineUiProgress())
        on_success = kwargs.get("on_success")
        if callable(on_success):
            on_success(result)
        on_success_after_cleanup = kwargs.get("on_success_after_cleanup")
        if callable(on_success_after_cleanup):
            on_success_after_cleanup(result)
        on_finished = kwargs.get("on_finished")
        if callable(on_finished):
            on_finished()
        return "inline-task"

    def _set_first_launch_prompt_pending(self, pending: bool) -> None:
        settings = self._settings()
        settings.setValue("startup/offer_open_settings_on_first_launch_pending", bool(pending))
        settings.sync()
        settings.deleteLater() if hasattr(settings, "deleteLater") else None

    def _seed_startup_settings_for_legacy_db(self, legacy_db: Path) -> None:
        settings = self._settings()
        settings.setValue("storage/legacy_data_root", str(legacy_db.parent.parent.resolve()))
        settings.setValue("storage/active_data_root", str(legacy_db.parent.parent.resolve()))
        settings.setValue("db/last_path", str(legacy_db.resolve()))
        settings.setValue("paths/database_dir", str(legacy_db.parent.resolve()))
        settings.sync()
        settings.deleteLater() if hasattr(settings, "deleteLater") else None

    def _create_profile_database(self, path: Path) -> None:
        session = DatabaseSessionService().open(path)
        try:
            schema = DatabaseSchemaService(session.conn, data_root=self.local_appdata / APP_NAME)
            schema.init_db()
            schema.migrate_schema()
        finally:
            DatabaseSessionService.close(session.conn)

    def _create_track(self, *, index: int, title: str, album_title: str = "Workspace Tests") -> int:
        payload = TrackCreatePayload(
            isrc=f"NL-TST-26-{index:05d}",
            track_title=title,
            artist_name="Moonwake",
            additional_artists=[],
            album_title=album_title,
            release_date="2026-03-17",
            track_length_sec=180 + index,
            iswc=None,
            upc=None,
            genre="Ambient",
            catalog_number=None,
        )
        if getattr(self.window, "governed_track_creation_service", None) is not None:
            return self.window.governed_track_creation_service.create_governed_track(
                payload,
                governance_mode="create_new_work",
                profile_name=self.window._current_profile_name(),
            ).track_id
        return self.window.track_service.create_track(payload)

    def _create_media_file(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.write_bytes(payload)
        return path

    def _create_wav_file(self, name: str, *, frame_count: int = 22050) -> Path:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(b"\x00\x00" * frame_count)
        return self._create_media_file(name, buffer.getvalue())

    def _create_png_file(self, name: str, *, color: str = "#3A7AFE", size: int = 48) -> Path:
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(QColor(color))
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        return self._create_media_file(name, bytes(buffer.data()))

    def _attach_standard_media(
        self,
        track_id: int,
        *,
        audio_path: Path | None = None,
        album_art_path: Path | None = None,
        storage_mode: str = STORAGE_MODE_DATABASE,
    ) -> None:
        if audio_path is not None:
            self.window.track_set_media(
                track_id,
                "audio_file",
                str(audio_path),
                storage_mode=storage_mode,
            )
        if album_art_path is not None:
            self.window.track_set_media(
                track_id,
                "album_art",
                str(album_art_path),
                storage_mode=storage_mode,
            )
        self.window.conn.commit()
        self.window.refresh_table_preserve_view(focus_id=track_id)

    def _open_audio_preview_dialog(self, track_id: int):
        self.window._preview_standard_media_for_track(track_id, "audio_file")
        pump_events()
        return self.window.audio_preview_dialog

    def _open_image_preview_dialog(self, track_id: int):
        self.window._preview_standard_media_for_track(track_id, "album_art")
        pump_events()
        return self.window.image_preview_dialog

    @staticmethod
    def _label_texts(widget) -> list[str]:
        return [label.text() for label in widget.findChildren(app_module.QLabel)]

    def _table_row_for_track_id(self, track_id: int) -> int:
        for row in range(self.window.table.rowCount()):
            item = self.window.table.item(row, 0)
            if item is None:
                continue
            try:
                current_track_id = int(item.text())
            except Exception:
                continue
            if current_track_id == int(track_id):
                return row
        raise AssertionError(f"Track row not found: {track_id}")

    @staticmethod
    def _menu_action_texts(menu) -> list[str]:
        return [action.text() for action in menu.actions() if action.text()]

    @classmethod
    def _menu_snapshot(cls, menu) -> dict[str, object]:
        texts: list[str] = []
        submenus: dict[str, dict[str, object]] = {}
        for action in menu.actions():
            text = action.text()
            if not text:
                continue
            texts.append(text)
            if action.menu() is not None:
                submenus[text] = cls._menu_snapshot(action.menu())
        return {"texts": texts, "submenus": submenus}

    @staticmethod
    def _menu_snapshot_at_path(snapshot: dict[str, object], *path: str) -> dict[str, object]:
        current = snapshot
        for title in path:
            current = (current.get("submenus") or {}).get(title) or None
            if current is None:
                raise AssertionError(f"Submenu path not found: {' > '.join(path)}")
        return current

    @staticmethod
    def _flatten_menu_snapshot(snapshot: dict[str, object]) -> list[str]:
        texts = list(snapshot.get("texts") or [])
        for submenu in (snapshot.get("submenus") or {}).values():
            texts.extend(AppShellTestCase._flatten_menu_snapshot(submenu))
        return texts

    def _table_context_menu_snapshot(self, row: int, col: int) -> dict[str, object]:
        captured: dict[str, dict[str, object]] = {}
        index = self.window.table.model().index(row, col)

        class _CapturedMenu:
            def __init__(self, *_args, title: str = "", **_kwargs):
                self._title = str(title or "")
                self._entries: list[object] = []

            def addAction(self, action):
                self._entries.append(action)
                return action

            def addSeparator(self):
                self._entries.append(None)
                return None

            def addMenu(self, title):
                submenu = _CapturedMenu(title=title)
                self._entries.append(submenu)
                return submenu

            def _snapshot(self) -> dict[str, object]:
                texts: list[str] = []
                submenus: dict[str, dict[str, object]] = {}
                for entry in self._entries:
                    if isinstance(entry, _CapturedMenu):
                        if entry._title:
                            texts.append(entry._title)
                            submenus[entry._title] = entry._snapshot()
                        continue
                    if hasattr(entry, "text") and entry.text():
                        texts.append(entry.text())
                return {"texts": texts, "submenus": submenus}

            def exec(self, *_args, **_kwargs):
                captured["snapshot"] = self._snapshot()
                return None

        with (
            mock.patch.object(app_module, "QMenu", _CapturedMenu),
            mock.patch.object(self.window.table, "indexAt", return_value=index),
        ):
            self.window._on_table_context_menu(app_module.QPoint(0, 0))
            self.app.processEvents()

        return captured.get("snapshot", {"texts": [], "submenus": {}})

    def _action_ribbon_context_menu_snapshot(self) -> dict[str, object]:
        captured: dict[str, dict[str, object]] = {}

        class _CapturedMenu:
            def __init__(self, *_args, title: str = "", **_kwargs):
                self._title = str(title or "")
                self._entries: list[object] = []

            def addAction(self, action):
                self._entries.append(action)
                return action

            def addSeparator(self):
                self._entries.append(None)
                return None

            def addMenu(self, title):
                submenu = _CapturedMenu(title=title)
                self._entries.append(submenu)
                return submenu

            def _snapshot(self) -> dict[str, object]:
                texts: list[str] = []
                submenus: dict[str, dict[str, object]] = {}
                for entry in self._entries:
                    if isinstance(entry, _CapturedMenu):
                        if entry._title:
                            texts.append(entry._title)
                            submenus[entry._title] = entry._snapshot()
                        continue
                    if hasattr(entry, "text") and entry.text():
                        texts.append(entry.text())
                return {"texts": texts, "submenus": submenus}

            def exec(self, *_args, **_kwargs):
                captured["snapshot"] = self._snapshot()
                return None

        with mock.patch.object(app_module, "QMenu", _CapturedMenu):
            self.window._open_action_ribbon_context_menu(app_module.QPoint(0, 0))
            self.app.processEvents()

        return captured.get("snapshot", {"texts": [], "submenus": {}})

    def _table_context_action_texts(self, row: int, col: int) -> list[str]:
        snapshot = self._table_context_menu_snapshot(row, col)
        return self._flatten_menu_snapshot(snapshot)

    def _select_track_ids(self, track_ids: list[int]) -> None:
        track_id_set = {int(track_id) for track_id in track_ids}
        self.window.table.clearSelection()
        selection_model = self.window.table.selectionModel()
        for row in range(self.window.table.rowCount()):
            item = self.window.table.item(row, 0)
            if item is None:
                continue
            try:
                current_track_id = int(item.text())
            except Exception:
                continue
            if current_track_id not in track_id_set:
                continue
            index = self.window.table.model().index(row, 0)
            selection_model.select(
                index,
                app_module.QItemSelectionModel.Select | app_module.QItemSelectionModel.Rows,
            )
        self.app.processEvents()

    def _assert_tabified_workspace_dock(self, dock, *, dock_name: str, panel_name: str):
        panel = dock.widget()
        self.assertFalse(dock.isHidden())
        self.assertEqual(dock.objectName(), dock_name)
        self.assertIsNotNone(panel)
        self.assertEqual(panel.objectName(), panel_name)
        self.assertIn(dock, self.window.tabifiedDockWidgets(self.window.catalog_table_dock))
        return panel

    @staticmethod
    def _is_within_scroll_content(scroll_area, widget) -> bool:
        content = scroll_area.widget()
        return content is widget or (content is not None and content.isAncestorOf(widget))

    @staticmethod
    def _button_by_text(container, text: str):
        for button in container.findChildren(app_module.QPushButton):
            if button.text() == text:
                return button
        raise AssertionError(f"Button not found: {text}")

    def _menu_by_text(self, text: str):
        for menu in self.window.menuBar().findChildren(app_module.QMenu):
            if menu.title() == text:
                return menu
        raise AssertionError(f"Menu not found: {text}")

    def _saved_layout_selector_widget(self):
        selector = getattr(self.window, "saved_layout_selector", None)
        if isinstance(selector, app_module.QComboBox):
            return selector
        raise AssertionError("Saved layout selector not found")

    def _saved_layouts_menu_list_widget(self):
        self.window._populate_saved_layouts_menu()
        for action in self.window.saved_layouts_menu.actions():
            if not isinstance(action, app_module.QWidgetAction):
                continue
            widget = action.defaultWidget()
            if isinstance(widget, app_module.QListWidget):
                return widget
        raise AssertionError("Saved layouts menu list widget not found")

    def _workspace_dock_tab_bar(self) -> QTabBar:
        expected_titles = {
            dock.windowTitle()
            for dock in (
                getattr(self.window, "catalog_table_dock", None),
                getattr(self.window, "release_browser_dock", None),
                getattr(self.window, "work_manager_dock", None),
                getattr(self.window, "global_search_dock", None),
            )
            if dock is not None
        }
        for tab_bar in self.window.findChildren(QTabBar):
            texts = {tab_bar.tabText(index) for index in range(tab_bar.count())}
            if texts & expected_titles:
                return tab_bar
        raise AssertionError("Workspace dock tab bar not found")

    def case_startup_builds_main_window_with_core_actions(self):
        self.assertIsNotNone(self.window.conn)
        self.assertTrue(Path(self.window.current_db_path).exists())
        self.assertEqual(self.window.menuBar(), self.window.menu_bar)
        self.assertGreaterEqual(self.window.profile_combo.count(), 1)
        self.assertEqual(self.window.profile_combo.itemData(0), self.window.current_db_path)
        self.assertEqual(self.window.windowTitle(), self.window.identity["window_title"])
        self.assertEqual(self.window.toolbar.objectName(), "profilesToolbar")
        self.assertEqual(self.window.statusBar().currentMessage(), "")

        expected_actions = {
            "New Profile…": self.window.new_profile_action,
            "Open Profile…": self.window.open_profile_action,
            "Add Track…": self.window.add_track_action,
            "Add Album…": self.window.add_album_action,
            "Release Browser…": self.window.release_browser_action,
            "Work Manager…": self.window.work_manager_action,
            "Contract Manager…": self.window.contract_manager_action,
            "Contract Template Workspace…": self.window.contract_template_workspace_action,
            "Derivative Ledger…": self.window.derivative_ledger_action,
            "Global Search and Relationships…": self.window.global_search_action,
            "Create Snapshot…": self.window.create_snapshot_action,
        }
        self.assertEqual(
            {text: action.text() for text, action in expected_actions.items()},
            {text: text for text in expected_actions},
        )
        self.assertTrue(self.window.close())
        self.app.processEvents()
        self.assertFalse(self.window.isVisible())

    def case_startup_status_messages_cover_real_bootstrap_phases_and_ready_boundary(self):
        self._close_window()
        splash = _FakeStartupSplashController()
        splash.show()

        self.window = app_module.App(startup_feedback=splash)

        ordered_bootstrap_phases = []
        for phase, _message in splash.phase_updates:
            if phase in {
                StartupPhase.RESOLVING_STORAGE,
                StartupPhase.INITIALIZING_SETTINGS,
                StartupPhase.OPENING_PROFILE_DB,
                StartupPhase.PREPARING_DATABASE,
                StartupPhase.LOADING_SERVICES,
                StartupPhase.FINALIZING_INTERFACE,
            } and (not ordered_bootstrap_phases or ordered_bootstrap_phases[-1] != phase):
                ordered_bootstrap_phases.append(phase)
        self.assertEqual(
            [
                StartupPhase.RESOLVING_STORAGE,
                StartupPhase.INITIALIZING_SETTINGS,
                StartupPhase.OPENING_PROFILE_DB,
                StartupPhase.PREPARING_DATABASE,
                StartupPhase.LOADING_SERVICES,
                StartupPhase.FINALIZING_INTERFACE,
            ],
            ordered_bootstrap_phases[:6],
        )
        self.assertEqual(splash.finish_calls, [])
        self.assertTrue(splash.progress_updates)
        self.assertEqual(
            [update[0] for update in splash.progress_updates],
            sorted(update[0] for update in splash.progress_updates),
        )

        self.window.show()
        self.assertEqual(splash.finish_calls, [])
        self._drain_events()

        self.assertIn(
            StartupPhase.RESTORING_WORKSPACE, [phase for phase, _ in splash.phase_updates]
        )
        self.assertEqual(splash.current_progress, 100)
        self.assertEqual(splash.finish_calls, [self.window])

    def case_startup_splash_waits_for_catalog_refresh_completion(self):
        self._close_window()
        splash = _FakeStartupSplashController()
        splash.show()
        callbacks: dict[str, object] = {}

        def _deferred_refresh(window, *args, **kwargs):
            del window, args
            callbacks["complete"] = kwargs.get("on_complete")
            return "deferred-startup-refresh"

        with mock.patch.object(
            app_module.App,
            "_refresh_catalog_ui_in_background",
            autospec=True,
            side_effect=_deferred_refresh,
        ):
            self.window = app_module.App(startup_feedback=splash)
            self.window.show()
            self._drain_events()

        self.assertTrue(callable(callbacks.get("complete")))
        self.assertIn(
            StartupPhase.RESTORING_WORKSPACE, [phase for phase, _ in splash.phase_updates]
        )
        self.assertEqual(splash.current_phase, StartupPhase.LOADING_CATALOG)
        self.assertEqual(splash.finish_calls, [])

        callbacks["complete"]()
        self._drain_events()

        self.assertEqual(splash.phase_updates[-1][0], StartupPhase.READY)
        self.assertEqual(splash.current_progress, 100)
        self.assertEqual(splash.finish_calls, [self.window])

    def case_startup_prepares_database_before_live_open(self):
        self._close_window()
        splash = _FakeStartupSplashController()
        splash.show()
        open_calls: list[bool] = []
        original_open_database = app_module.App.open_database

        def _spy_open_database(window, path, *args, **kwargs):
            del args
            open_calls.append(bool(kwargs.get("schema_prepared")))
            return original_open_database(window, path, **kwargs)

        with (
            mock.patch.object(
                app_module.App,
                "_prepare_database_for_open_blocking",
                return_value=True,
            ),
            mock.patch.object(
                app_module.App,
                "open_database",
                autospec=True,
                side_effect=_spy_open_database,
            ),
        ):
            self.window = app_module.App(startup_feedback=splash)
            self.window.show()
            self._drain_events()

        self.assertEqual(open_calls, [True])

    def case_startup_ignores_repo_demo_runtime_last_path_for_normal_settings(self):
        self._close_window()
        settings = self._settings()
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        repo_root = Path(app_module.__file__).resolve().parent
        demo_runtime_db = (
            repo_root / "demo" / ".runtime" / "localappdata" / APP_NAME / "Database" / "library.db"
        )
        expected_default = (preferred_root / "Database" / "default.db").resolve()
        settings.setValue("storage/active_data_root", str(preferred_root.resolve()))
        settings.setValue("paths/database_dir", str((preferred_root / "Database").resolve()))
        settings.setValue("db/last_path", str(demo_runtime_db.resolve()))
        settings.sync()

        self._open_window(skip_background_prepare=True)

        self.assertEqual(Path(self.window.current_db_path).resolve(), expected_default)
        self.assertEqual(
            self.window.settings.value("db/last_path", "", str),
            str(expected_default),
        )

    def case_audio_conversion_format_prompt_uses_export_button_label(self):
        fake_capabilities = SimpleNamespace(
            managed_targets=(SimpleNamespace(id="wav", label="WAV"),),
            managed_forensic_targets=(),
            managed_lossy_targets=(SimpleNamespace(id="mp3", label="MP3"),),
            external_targets=(),
        )
        captured = {}

        with (
            mock.patch.object(
                self.window.audio_conversion_service,
                "capabilities",
                return_value=fake_capabilities,
            ),
            mock.patch.object(
                app_module,
                "_prompt_compact_choice_dialog",
                side_effect=lambda *args, **kwargs: captured.update(kwargs) or "mp3",
            ),
        ):
            selected = self.window._prompt_audio_conversion_format(
                title="Export Audio Derivatives",
                prompt="Choose a managed derivative output format.",
                capability_group="managed_any",
            )

        self.assertEqual(selected, "mp3")
        self.assertEqual(captured.get("ok_text"), "Export")

    def case_startup_first_launch_prompt_can_open_settings_and_clears_pending_flag(self):
        self._close_window()
        self._set_first_launch_prompt_pending(True)

        prompts: list[tuple[str, str]] = []

        class _FakePromptBox:
            def __init__(self):
                self._buttons = {}
                self._clicked_button = None

            def addButton(self, label, _role):
                button = object()
                self._buttons[str(label)] = button
                return button

            def setDefaultButton(self, _button):
                return None

            def clickedButton(self):
                return self._clicked_button

        def _fake_startup_message_box(
            window,
            *,
            title,
            icon,
            text,
            configure=None,
        ):
            _ = icon
            prompts.append((str(title), str(text)))
            box = _FakePromptBox()
            if callable(configure):
                configure(box)
            box._clicked_button = box._buttons.get("Open Settings")
            return box

        with (
            mock.patch.object(
                app_module.App,
                "_run_startup_message_box",
                new=_fake_startup_message_box,
            ),
            mock.patch.object(
                app_module.App, "open_settings_dialog", autospec=True
            ) as open_settings,
        ):
            self.window = app_module.App()
            self.window.show()
            self._drain_events()

        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][0], "Open Settings")
        self.assertIn("first time", prompts[0][1])
        self.assertFalse(
            self.window.settings.value(
                "startup/offer_open_settings_on_first_launch_pending",
                True,
                bool,
            )
        )
        open_settings.assert_called_once_with(self.window)

        with mock.patch.object(app_module.App, "_run_startup_message_box") as prompt_again:
            self._reopen_window()
            prompt_again.assert_not_called()

    def case_owner_bootstrap_requires_assigning_a_party_before_normal_use(self):
        created_party_id = self.window.party_service.create_party(
            PartyPayload(
                legal_name="Bootstrap Owner B.V.",
                display_name="Bootstrap Owner",
                party_type="organization",
            )
        )
        dialog_calls: list[int | None] = []

        class _FakeOwnerBootstrapDialog:
            def __init__(self, *, current_owner_party_id=None, **kwargs):
                del kwargs
                dialog_calls.append(current_owner_party_id)

            def exec(self):
                return app_module.QDialog.Accepted

            def selected_party_id(self):
                return created_party_id

        with mock.patch.object(
            app_module,
            "OwnerBootstrapDialog",
            _FakeOwnerBootstrapDialog,
        ):
            self.window._ensure_owner_party_bootstrap()
            self._drain_events()

        self.assertEqual(dialog_calls, [None])
        self.assertEqual(self.window.settings_reads.load_owner_party_id(), created_party_id)
        owner_record = self.window.party_service.fetch_party(created_party_id)
        self.assertIsNotNone(owner_record)

    def case_window_title_defaults_to_app_name_then_owner_then_manual_override(self):
        self.window.settings_mutations.set_owner_party_id(None)
        self.window.settings.setValue("identity/window_title", "ISRC Manager")
        self.window.settings.remove("identity/window_title_override")
        self.window.settings.sync()
        self.window.identity = self.window._load_identity()
        self.window._apply_identity()
        self.assertEqual(self.window.windowTitle(), app_module.DEFAULT_WINDOW_TITLE)
        self.assertEqual(self.window.identity.get("window_title_override"), "")

        first_owner_id = self.window.party_service.create_party(
            PartyPayload(
                legal_name="Moonwake Records B.V.",
                display_name="Moonwake Records",
                company_name="Moonwake Records",
                party_type="organization",
            )
        )
        self.window._assign_owner_party(first_owner_id, record_history=False)
        self._drain_events()
        self.assertEqual(self.window.windowTitle(), "Moonwake Records")
        self.assertEqual(self.window.identity.get("window_title_override"), "")

        self.window.settings_mutations.set_identity(
            window_title_override="Custom Shell",
            icon_path=self.window.identity.get("icon_path") or "",
        )
        self.window.identity = self.window._load_identity()
        self.window._apply_identity()
        self.assertEqual(self.window.windowTitle(), "Custom Shell")
        self.assertEqual(self.window.identity.get("window_title_override"), "Custom Shell")

        second_owner_id = self.window.party_service.create_party(
            PartyPayload(
                legal_name="North Star Publishing B.V.",
                display_name="North Star Publishing",
                company_name="North Star Publishing",
                party_type="organization",
            )
        )
        self.window._assign_owner_party(second_owner_id, record_history=False)
        self._drain_events()
        self.assertEqual(self.window.windowTitle(), "Custom Shell")

    def case_file_menu_nests_profile_maintenance_under_profiles_and_removes_verify_integrity(self):
        file_menu = self._menu_by_text("File")
        file_snapshot = self._menu_snapshot(file_menu)
        file_texts = list(file_snapshot.get("texts") or [])

        self.assertNotIn("Profile Maintenance", file_texts)
        profiles_snapshot = self._menu_snapshot_at_path(file_snapshot, "Profiles")
        self.assertEqual(
            list(profiles_snapshot.get("texts") or []),
            [
                "New Profile…",
                "Open Profile…",
                "Reload Profile List",
                "Remove Selected Profile…",
                "Profile Maintenance",
            ],
        )
        maintenance_snapshot = self._menu_snapshot_at_path(profiles_snapshot, "Profile Maintenance")
        self.assertEqual(
            list(maintenance_snapshot.get("texts") or []),
            [
                "Backup Database",
                "Restore from Backup…",
            ],
        )
        self.assertNotIn("verify", self.window._action_ribbon_specs_by_id)

    def case_edit_menu_exposes_catalog_table_edit_actions_and_preserves_enablement(self):
        edit_menu = self._menu_by_text("Edit")
        edit_actions = {
            action.text(): action
            for action in edit_menu.actions()
            if action.text() and action.menu() is None
        }

        self.assertIn("GS1 Metadata…", edit_actions)
        self.assertIs(edit_actions["GS1 Metadata…"], self.window.gs1_metadata_action)
        self.assertTrue(self.window.gs1_metadata_action.isEnabled())

        with (
            mock.patch.object(self.window, "_selected_track_ids", return_value=[]),
            mock.patch.object(app_module.QMessageBox, "information") as info_mock,
        ):
            self.window.gs1_metadata_action.trigger()
            self._drain_events()

        info_mock.assert_called_once()
        self.assertIn("Select a catalog row first", info_mock.call_args.args[2])

    def case_file_menu_groups_xml_import_under_import_exchange_and_preserves_wiring(self):
        file_menu = self._menu_by_text("File")
        file_texts = [action.text() for action in file_menu.actions() if action.text()]
        self.assertNotIn("Import Catalog XML…", file_texts)
        self.assertNotIn("Convert External Audio Files…", file_texts)
        self.assertNotIn("Inspect Forensic Watermark…", file_texts)

        import_action = next(
            action
            for action in file_menu.actions()
            if action.menu() is not None and action.text() == "Import & Exchange"
        )
        import_menu = import_action.menu()
        assert import_menu is not None
        import_snapshot = self._menu_snapshot(import_menu)
        self.assertEqual(
            list(import_snapshot.get("texts") or []),
            [
                "Master Catalog Transfer",
                "Catalog Exchange",
                "Parties",
                "Contracts and Rights",
            ],
        )
        master_transfer_menu = self._menu_snapshot_at_path(
            import_snapshot, "Master Catalog Transfer"
        )
        import_exchange_menu = self._menu_snapshot_at_path(import_snapshot, "Catalog Exchange")
        parties_menu = self._menu_snapshot_at_path(import_snapshot, "Parties")
        contracts_menu = self._menu_snapshot_at_path(import_snapshot, "Contracts and Rights")
        self.assertEqual(
            list(master_transfer_menu.get("texts") or []),
            [
                "Import Master Transfer ZIP…",
            ],
        )
        self.assertEqual(
            list(import_exchange_menu.get("texts") or []),
            [
                "Import XML…",
                "Import CSV…",
                "Import XLSX…",
                "Import JSON…",
                "Import ZIP Package…",
                "Reset Saved Import Choices…",
            ],
        )
        self.assertEqual(
            list(parties_menu.get("texts") or []),
            [
                "Import Parties CSV…",
                "Import Parties XLSX…",
                "Import Parties JSON…",
            ],
        )
        self.assertEqual(
            list(contracts_menu.get("texts") or []),
            [
                "Import Contracts and Rights JSON…",
                "Import Contracts and Rights XLSX…",
                "Import Contracts and Rights CSV Bundle…",
                "Import Contracts and Rights ZIP Package…",
            ],
        )
        self.assertTrue(
            any(not shortcut.isEmpty() for shortcut in self.window.import_xml_action.shortcuts())
        )

        with mock.patch.object(
            app_module.QFileDialog,
            "getOpenFileName",
            side_effect=[("", ""), ("", "")],
        ) as get_open_file_name:
            self.window.import_xml_action.trigger()
            self.window.import_party_json_action.trigger()
            self.app.processEvents()

        first_call = get_open_file_name.mock_calls[0]
        self.assertEqual(
            first_call,
            mock.call(
                self.window,
                "Import XML",
                "",
                "XML Files (*.xml)",
            ),
        )
        second_call = get_open_file_name.mock_calls[1]
        self.assertEqual(
            second_call,
            mock.call(
                self.window,
                "Import Parties JSON",
                "",
                "JSON Files (*.json)",
            ),
        )

    def case_file_menu_groups_exchange_exports_and_saved_import_reset(self):
        file_menu = self._menu_by_text("File")
        file_texts = [action.text() for action in file_menu.actions() if action.text()]
        self.assertNotIn("Convert External Audio Files…", file_texts)
        self.assertNotIn("Inspect Forensic Watermark…", file_texts)

        export_action = next(
            action
            for action in file_menu.actions()
            if action.menu() is not None and action.text() == "Export"
        )
        export_menu = export_action.menu()
        assert export_menu is not None
        export_texts = [action.text() for action in export_menu.actions() if action.text()]
        self.assertEqual(
            export_texts,
            [
                "Master Catalog Transfer",
                "Catalog Exchange",
                "Parties",
                "Contracts and Rights",
            ],
        )

        master_transfer_action = next(
            action
            for action in export_menu.actions()
            if action.menu() is not None and action.text() == "Master Catalog Transfer"
        )
        master_transfer_menu = master_transfer_action.menu()
        assert master_transfer_menu is not None
        self.assertEqual(
            [action.text() for action in master_transfer_menu.actions() if action.text()],
            ["Export Master Transfer ZIP…"],
        )

        exchange_action = next(
            action
            for action in export_menu.actions()
            if action.menu() is not None and action.text() == "Catalog Exchange"
        )
        exchange_menu = exchange_action.menu()
        assert exchange_menu is not None
        exchange_snapshot = self._menu_snapshot(exchange_menu)
        self.assertEqual(
            list(exchange_snapshot.get("texts") or []),
            ["Current Scope", "Full Catalog"],
        )
        exchange_scope_snapshot = self._menu_snapshot_at_path(exchange_snapshot, "Current Scope")
        exchange_full_snapshot = self._menu_snapshot_at_path(exchange_snapshot, "Full Catalog")
        self.assertEqual(
            list(exchange_scope_snapshot.get("texts") or []),
            [
                "Export Selected Exchange XML…",
                "Export Selected Exchange CSV…",
                "Export Selected Exchange XLSX…",
                "Export Selected Exchange JSON…",
                "Export Selected Exchange ZIP Package…",
            ],
        )
        self.assertEqual(
            list(exchange_full_snapshot.get("texts") or []),
            [
                "Export Full Exchange XML…",
                "Export Full Exchange CSV…",
                "Export Full Exchange XLSX…",
                "Export Full Exchange JSON…",
                "Export Full Exchange ZIP Package…",
            ],
        )

        parties_action = next(
            action
            for action in export_menu.actions()
            if action.menu() is not None and action.text() == "Parties"
        )
        parties_menu = parties_action.menu()
        assert parties_menu is not None
        parties_snapshot = self._menu_snapshot(parties_menu)
        self.assertEqual(
            list(parties_snapshot.get("texts") or []),
            [
                "Selected Parties",
                "Full Party Catalog",
            ],
        )
        self.assertEqual(
            list(
                self._menu_snapshot_at_path(parties_snapshot, "Selected Parties").get("texts") or []
            ),
            [
                "Export Selected Parties CSV…",
                "Export Selected Parties XLSX…",
                "Export Selected Parties JSON…",
            ],
        )
        self.assertEqual(
            list(
                self._menu_snapshot_at_path(parties_snapshot, "Full Party Catalog").get("texts")
                or []
            ),
            [
                "Export Full Party Catalog CSV…",
                "Export Full Party Catalog XLSX…",
                "Export Full Party Catalog JSON…",
            ],
        )

        contracts_action = next(
            action
            for action in export_menu.actions()
            if action.menu() is not None and action.text() == "Contracts and Rights"
        )
        contracts_menu = contracts_action.menu()
        assert contracts_menu is not None
        contracts_texts = [action.text() for action in contracts_menu.actions() if action.text()]
        self.assertIn("Export Contracts and Rights JSON…", contracts_texts)
        self.assertIn("Export Contracts and Rights ZIP Package…", contracts_texts)

        profiles_action = next(
            action
            for action in file_menu.actions()
            if action.menu() is not None and action.text() == "Profiles"
        )
        profiles_menu = profiles_action.menu()
        assert profiles_menu is not None
        maintenance_action = next(
            action
            for action in profiles_menu.actions()
            if action.menu() is not None and action.text() == "Profile Maintenance"
        )
        maintenance_menu = maintenance_action.menu()
        assert maintenance_menu is not None
        self.assertEqual(
            [action.text() for action in maintenance_menu.actions() if action.text()],
            [
                "Backup Database",
                "Restore from Backup…",
            ],
        )

    def case_settings_view_history_help_menus_and_action_ribbon_context_menu_use_streamlined_structure(
        self,
    ):
        settings_texts = self._menu_action_texts(self._menu_by_text("Settings"))
        self.assertEqual(
            settings_texts,
            [
                "Application Settings…",
                "Audio Authenticity Keys…",
            ],
        )
        edit_texts = self._menu_action_texts(self._menu_by_text("Edit"))
        self.assertEqual(
            edit_texts,
            [
                "Undo",
                "Redo",
                "Add Track…",
                "Add Album…",
                "Edit Selected…",
                "Delete Selected Track",
                "GS1 Metadata…",
                "Copy",
                "Copy with Headers",
            ],
        )

        view_snapshot = self._menu_snapshot(self._menu_by_text("View"))
        self.assertEqual(
            list(view_snapshot.get("texts") or []),
            [
                "Columns",
                "Show Profiles Ribbon",
                "Show Action Ribbon",
                "Customize Action Ribbon…",
                "Layout",
            ],
        )
        layout_texts = list(self._menu_snapshot_at_path(view_snapshot, "Layout").get("texts") or [])
        self.assertEqual(
            layout_texts,
            [
                "Saved Layouts",
                "Add Layout",
                "Delete Layout",
                "Catalog Table",
            ],
        )
        table_layout_texts = list(
            self._menu_snapshot_at_path(view_snapshot, "Layout", "Catalog Table").get("texts") or []
        )
        self.assertEqual(
            table_layout_texts,
            [
                "Edit Column Widths",
                "Edit Row Heights",
                "Allow Column Reordering",
            ],
        )
        selector = self._saved_layout_selector_widget()
        self.assertFalse(selector.isEnabled())
        self.assertEqual(selector.itemText(0), "No Saved Layouts")
        self.assertFalse(self.window.delete_layout_action.isEnabled())

        history_texts = self._menu_action_texts(self._menu_by_text("History"))
        self.assertEqual(history_texts, ["Show Undo History…", "Create Snapshot…"])

        help_texts = self._menu_action_texts(self._menu_by_text("Help"))
        self.assertEqual(
            help_texts,
            [
                "Help Contents…",
                "About ISRC Catalog Manager…",
                "Diagnostics…",
                "Application Log…",
                "Open Logs Folder…",
                "Open Data Folder…",
            ],
        )

        ribbon_snapshot = self._action_ribbon_context_menu_snapshot()
        self.assertEqual(
            list(ribbon_snapshot.get("texts") or []),
            [
                "Customize Action Ribbon…",
                "Show Action Ribbon",
            ],
        )
        self.assertEqual(
            self.window._action_ribbon_default_ids,
            [
                "add_track",
                "add_album",
                "release_browser",
                "work_manager",
                "quality_dashboard",
                "gs1_metadata",
                "settings",
                "show_history",
                "create_snapshot",
            ],
        )

    def case_named_main_window_layouts_can_be_saved_applied_deleted_and_shared_between_menu_and_ribbon(
        self,
    ):
        self.assertEqual(self.window._saved_main_window_layout_names(), [])

        self.window.add_data_action.trigger()
        self.window.open_release_browser()
        self._drain_events()
        self.window.addDockWidget(
            app_module.Qt.LeftDockWidgetArea, self.window.release_browser_dock
        )
        self.window.tabifyDockWidget(self.window.add_data_dock, self.window.release_browser_dock)
        self.window.release_browser_dock.raise_()
        self._drain_events()

        with mock.patch.object(
            app_module.QInputDialog,
            "getText",
            return_value=("Writer Desk", True),
        ):
            self.window.add_layout_action.trigger()
        self._drain_events()

        self.assertEqual(self.window._saved_main_window_layout_names(), ["Writer Desk"])
        selector = self._saved_layout_selector_widget()
        self.assertTrue(selector.isEnabled())
        self.assertGreater(selector.findData("Writer Desk"), 0)
        self.assertTrue(self.window.delete_layout_action.isEnabled())

        menu_list = self._saved_layouts_menu_list_widget()
        self.assertEqual(
            [menu_list.item(index).text() for index in range(menu_list.count())],
            ["Writer Desk"],
        )

        self._reopen_window(skip_background_prepare=True)
        selector = self._saved_layout_selector_widget()
        self.assertEqual(self.window._saved_main_window_layout_names(), ["Writer Desk"])
        self.assertGreater(selector.findData("Writer Desk"), 0)
        menu_list = self._saved_layouts_menu_list_widget()
        self.assertEqual(
            [menu_list.item(index).text() for index in range(menu_list.count())],
            ["Writer Desk"],
        )

        self.window.addDockWidget(
            app_module.Qt.RightDockWidgetArea, self.window.release_browser_dock
        )
        self.window.catalog_table_dock.raise_()
        self._drain_events()
        self.assertEqual(
            self.window.dockWidgetArea(self.window.release_browser_dock),
            app_module.Qt.RightDockWidgetArea,
        )

        saved_index = selector.findData("Writer Desk")
        self.assertGreater(saved_index, 0)
        selector.setCurrentIndex(saved_index)
        self.window._on_saved_layout_selected(saved_index)
        self._drain_events()
        selector = self._saved_layout_selector_widget()

        self.assertEqual(
            self.window.dockWidgetArea(self.window.release_browser_dock),
            app_module.Qt.LeftDockWidgetArea,
        )
        self.assertIn(
            self.window.release_browser_dock,
            set(self.window.tabifiedDockWidgets(self.window.add_data_dock)),
        )

        with (
            mock.patch.object(
                app_module.QInputDialog,
                "getItem",
                return_value=("Writer Desk", True),
            ),
            mock.patch.object(
                app_module.QMessageBox,
                "question",
                return_value=app_module.QMessageBox.Yes,
            ),
        ):
            self.window.saved_layout_delete_button.click()
        self._drain_events()
        selector = self._saved_layout_selector_widget()

        self.assertEqual(self.window._saved_main_window_layout_names(), [])
        self.assertFalse(selector.isEnabled())
        self.assertEqual(selector.itemText(0), "No Saved Layouts")
        self.assertFalse(self.window.delete_layout_action.isEnabled())

    def case_saved_layouts_menu_uses_scrollable_picker_widget_when_needed(self):
        for index in range(10):
            self.window._save_named_main_window_layout(f"Layout {index + 1}")
        self._drain_events()

        menu_list = self._saved_layouts_menu_list_widget()
        self.assertEqual(menu_list.count(), 10)
        self.assertEqual(
            menu_list.verticalScrollMode(),
            app_module.QAbstractItemView.ScrollPerPixel,
        )
        row_height = menu_list.sizeHintForRow(0)
        if row_height <= 0:
            row_height = max(menu_list.fontMetrics().height() + 8, 24)
        self.assertLess(
            menu_list.height(),
            (row_height * menu_list.count()) + (menu_list.frameWidth() * 2),
        )

    def case_moved_and_renamed_actions_preserve_dialog_routing(self):
        self._close_window()
        routed_calls: list[tuple[str, object]] = []

        def _record(name):
            def _inner(instance, *args, **kwargs):
                routed_calls.append((name, args[0] if args else kwargs or None))
                return None

            return _inner

        with (
            mock.patch.object(
                app_module.App,
                "open_settings_dialog",
                autospec=True,
                side_effect=_record("settings"),
            ),
            mock.patch.object(
                app_module.App, "open_history_dialog", autospec=True, side_effect=_record("history")
            ),
            mock.patch.object(
                app_module.App, "open_help_dialog", autospec=True, side_effect=_record("help")
            ),
            mock.patch.object(
                app_module.App,
                "open_diagnostics_dialog",
                autospec=True,
                side_effect=_record("diagnostics"),
            ),
            mock.patch.object(
                app_module.App,
                "open_application_log_dialog",
                autospec=True,
                side_effect=_record("application_log"),
            ),
            mock.patch.object(
                app_module.App,
                "open_quality_dashboard",
                autospec=True,
                side_effect=_record("quality"),
            ),
            mock.patch.object(
                app_module.App,
                "open_track_import_repair_queue",
                autospec=True,
                side_effect=_record("repair_queue"),
            ),
            mock.patch.object(
                app_module.App, "open_gs1_dialog", autospec=True, side_effect=_record("gs1")
            ),
            mock.patch.object(
                app_module.App,
                "open_add_track_entry",
                autospec=True,
                side_effect=_record("add_track"),
            ),
            mock.patch.object(
                app_module.App,
                "open_add_album_dialog",
                autospec=True,
                side_effect=_record("add_album"),
            ),
        ):
            self.window = app_module.App()
            self.window.show()
            self._drain_events()

            self.window.add_track_action.trigger()
            self.window.add_album_action.trigger()
            self.window.settings_action.trigger()
            self.window.show_history_action.trigger()
            self.window.help_contents_action.trigger()
            self.window.diagnostics_action.trigger()
            self.window.application_log_action.trigger()
            self.window.quality_dashboard_action.trigger()
            self.window.track_import_repair_queue_action.trigger()
            self.window.gs1_metadata_action.trigger()
            self._drain_events()

        self.assertEqual(
            [name for name, _payload in routed_calls],
            [
                "add_track",
                "add_album",
                "settings",
                "history",
                "help",
                "diagnostics",
                "application_log",
                "quality",
                "repair_queue",
                "gs1",
            ],
        )
        self.assertEqual(routed_calls[-1][1], None)

    def case_main_window_shortcuts_cover_help_media_and_workspace_actions(self):
        def _shortcut_texts(action):
            return {
                shortcut.toString() for shortcut in action.shortcuts() if not shortcut.isEmpty()
            }

        self.assertEqual(_shortcut_texts(self.window.help_contents_action), {"F1"})
        self.assertEqual(
            _shortcut_texts(self.window.derivative_ledger_action),
            {"Ctrl+Alt+Shift+A", "Meta+Alt+Shift+A"},
        )
        self.assertEqual(
            _shortcut_texts(self.window.bulk_attach_audio_action),
            {"Ctrl+Alt+U", "Meta+Alt+U"},
        )
        self.assertEqual(
            _shortcut_texts(self.window.attach_album_art_action),
            {"Ctrl+Alt+Shift+U", "Meta+Alt+Shift+U"},
        )
        self.assertEqual(
            _shortcut_texts(self.window.verify_audio_authenticity_action),
            {"Ctrl+Alt+V", "Meta+Alt+V"},
        )
        self.assertEqual(
            _shortcut_texts(self.window.authenticity_keys_action),
            {"Ctrl+Alt+K", "Meta+Alt+K"},
        )
        self.assertEqual(
            _shortcut_texts(self.window.manage_fields_action),
            {"Ctrl+Alt+Shift+M", "Meta+Alt+Shift+M"},
        )
        self.assertEqual(
            _shortcut_texts(self.window.col_width_action),
            {"Ctrl+Alt+Shift+W", "Meta+Alt+Shift+W"},
        )
        self.assertEqual(
            _shortcut_texts(self.window.global_search_action),
            {"Ctrl+Alt+F", "Meta+Alt+F"},
        )
        self.assertIs(self.window.workspace_global_search_action, self.window.global_search_action)

    def case_startup_can_defer_legacy_storage_migration_and_keep_current_folder(self):
        self._close_window()
        splash = _FakeStartupSplashController()
        splash.show()
        _DeferredMigrationMessageBox.active_splash = splash
        _DeferredMigrationMessageBox.suspended_during_exec = False
        _DeferredMigrationMessageBox.messages_during_exec = []
        _DeferredMigrationMessageBox.exec_count = 0
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        if preferred_root.exists():
            for child in preferred_root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        legacy_root = self.local_appdata / APP_NAME
        (legacy_root / "history").mkdir(parents=True, exist_ok=True)
        (legacy_root / "Database").mkdir(parents=True, exist_ok=True)

        with mock.patch.object(app_module, "QMessageBox", _DeferredMigrationMessageBox):
            self.window = app_module.App(startup_feedback=splash)
            self.window.show()
            self._drain_events()

        self.assertEqual(self.window.data_root, legacy_root.resolve())
        self.assertEqual(
            self.window.settings.value("storage/active_data_root", "", str),
            str(legacy_root.resolve()),
        )
        self.assertTrue(
            str(Path(self.window.current_db_path).resolve()).startswith(str(legacy_root.resolve()))
        )
        self.assertEqual(
            self.window.settings.value("storage/migration_state", "", str),
            "deferred",
        )
        self.assertIn("legacy app-data folder", _DeferredMigrationMessageBox.last_text.lower())
        self.assertEqual(_DeferredMigrationMessageBox.exec_count, 1)
        self.assertTrue(_DeferredMigrationMessageBox.suspended_during_exec)
        self.assertNotIn(
            "Opening profile database…",
            _DeferredMigrationMessageBox.messages_during_exec,
        )
        self.assertEqual(splash.suspend_calls, 1)
        self.assertEqual(splash.resume_calls, 1)

    def case_startup_migrate_now_bootstraps_logging_and_uses_preferred_root(self):
        self._close_window()
        splash = _FakeStartupSplashController()
        splash.show()
        _AcceptMigrationMessageBox.active_splash = splash
        _AcceptMigrationMessageBox.suspended_during_exec = False
        _AcceptMigrationMessageBox.messages_during_exec = []
        _AcceptMigrationMessageBox.exec_count = 0
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        if preferred_root.exists():
            shutil.rmtree(preferred_root)

        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "legacy_startup.db"
        self._create_profile_database(legacy_db)
        self._seed_startup_settings_for_legacy_db(legacy_db)

        with mock.patch.object(app_module, "QMessageBox", _AcceptMigrationMessageBox):
            self.window = app_module.App(startup_feedback=splash)
            self.window.show()
            self._drain_events()

        self.assertEqual(self.window.data_root, preferred_root.resolve())
        self.assertEqual(
            self.window.settings.value("storage/migration_state", "", str),
            "complete",
        )
        self.assertEqual(
            self.window.settings.value("storage/active_data_root", "", str),
            str(preferred_root.resolve()),
        )
        self.assertEqual(
            self.window.settings.value("db/last_path", "", str),
            str((preferred_root / "Database" / legacy_db.name).resolve()),
        )
        self.assertEqual(
            Path(self.window.current_db_path).resolve(),
            (preferred_root / "Database" / legacy_db.name).resolve(),
        )
        log_files = sorted(preferred_root.joinpath("logs").glob("isrc_manager_*.log"))
        trace_files = sorted(preferred_root.joinpath("logs").glob("isrc_manager_trace_*.jsonl"))
        self.assertTrue(log_files)
        self.assertTrue(trace_files)
        self.assertEqual(_AcceptMigrationMessageBox.exec_count, 2)
        self.assertTrue(_AcceptMigrationMessageBox.suspended_during_exec)
        self.assertEqual(splash.suspend_calls, 2)
        self.assertEqual(splash.resume_calls, 2)

    def case_schema_migration_error_dialog_suspends_splash_during_startup(self):
        self._close_window()
        splash = _FakeStartupSplashController()
        splash.show()
        _DeferredMigrationMessageBox.active_splash = splash
        _DeferredMigrationMessageBox.suspended_during_exec = False
        _DeferredMigrationMessageBox.exec_count = 0
        _DeferredMigrationMessageBox.last_text = ""

        with (
            mock.patch.object(app_module, "QMessageBox", _DeferredMigrationMessageBox),
            mock.patch.object(
                app_module.App,
                "_prepare_database_for_open_blocking",
                return_value=False,
            ),
            mock.patch.object(app_module.App, "migrate_schema", side_effect=RuntimeError("boom")),
        ):
            self.window = app_module.App(startup_feedback=splash)
            self.window.show()
            self._drain_events()

        self.assertTrue(_DeferredMigrationMessageBox.suspended_during_exec)
        self.assertEqual(_DeferredMigrationMessageBox.exec_count, 1)
        self.assertIn("Database migration failed", _DeferredMigrationMessageBox.last_text)
        self.assertEqual(splash.suspend_calls, 1)
        self.assertEqual(splash.resume_calls, 1)

    def case_startup_adopts_valid_preferred_root_when_settings_still_pin_legacy(self):
        self._close_window()
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        if preferred_root.exists():
            shutil.rmtree(preferred_root)

        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "legacy_adopt.db"
        self._create_profile_database(legacy_db)
        self._seed_startup_settings_for_legacy_db(legacy_db)

        settings = self._settings()
        layout = app_module.resolve_app_storage_layout(settings=settings)
        app_module.StorageMigrationService(layout, settings=settings).migrate()
        settings.setValue("storage/migration_state", "failed")
        settings.setValue("storage/legacy_data_root", str(legacy_root.resolve()))
        settings.setValue("storage/active_data_root", str(legacy_root.resolve()))
        settings.setValue("db/last_path", str(legacy_db.resolve()))
        settings.setValue("paths/database_dir", str((legacy_root / "Database").resolve()))
        settings.sync()

        with mock.patch.object(app_module, "QMessageBox") as message_box:
            self.window = app_module.App()
            self.window.show()
            self._drain_events()

        migrated_db = preferred_root / "Database" / legacy_db.name
        self.assertEqual(self.window.data_root, preferred_root.resolve())
        self.assertEqual(Path(self.window.current_db_path).resolve(), migrated_db.resolve())
        self.assertEqual(
            self.window.settings.value("storage/active_data_root", "", str),
            str(preferred_root.resolve()),
        )
        self.assertEqual(
            self.window.settings.value("storage/migration_state", "", str),
            "complete",
        )
        self.assertEqual(
            self.window.settings.value("db/last_path", "", str),
            str(migrated_db.resolve()),
        )
        self.assertFalse(message_box.called)

    def case_storage_migration_reopens_active_managed_profile_in_new_root(self):
        self._close_window()
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        if preferred_root.exists():
            shutil.rmtree(preferred_root)

        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "legacy_active.db"
        self._create_profile_database(legacy_db)

        settings_path = self.qt_settings_root / "AppDataLocation" / "settings.ini"
        settings = app_module.QSettings(str(settings_path), app_module.QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        settings.setValue("storage/migration_state", "deferred")
        settings.setValue("storage/legacy_data_root", str(legacy_root.resolve()))
        settings.setValue("storage/active_data_root", str(legacy_root.resolve()))
        settings.setValue("db/last_path", str(legacy_db.resolve()))
        settings.setValue("paths/database_dir", str((legacy_root / "Database").resolve()))
        settings.sync()

        self.window = app_module.App()
        self.window.show()
        self._drain_events()

        self.assertEqual(self.window.data_root, legacy_root.resolve())
        self.assertEqual(Path(self.window.current_db_path).resolve(), legacy_db.resolve())

        track_id = self._create_track(index=404, title="Migrated Managed Profile")

        result = self.window._run_storage_layout_migration()
        self._drain_events()

        migrated_db = preferred_root / "Database" / legacy_db.name
        self.assertEqual(result.target_root, preferred_root.resolve())
        self.assertEqual(Path(self.window.current_db_path).resolve(), migrated_db.resolve())
        self.assertTrue(migrated_db.exists())
        self.assertEqual(
            self.window.settings.value("db/last_path", "", str),
            str(migrated_db.resolve()),
        )
        self.assertEqual(
            self.window.settings.value("storage/active_data_root", "", str),
            str(preferred_root.resolve()),
        )
        self.assertEqual(
            self.window.settings.value("storage/migration_state", "", str),
            "complete",
        )
        self.assertTrue((legacy_root / "Database" / legacy_db.name).exists())
        self.assertIsNotNone(self.window.track_service.fetch_track_snapshot(track_id))

    def case_manual_legacy_cleanup_after_adoption_does_not_recreate_legacy_root(self):
        self._close_window()
        preferred_root = self.qt_settings_root / "AppLocalDataLocation"
        if preferred_root.exists():
            shutil.rmtree(preferred_root)

        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "legacy_cleanup.db"
        self._create_profile_database(legacy_db)
        self._seed_startup_settings_for_legacy_db(legacy_db)

        settings = self._settings()
        layout = app_module.resolve_app_storage_layout(settings=settings)
        app_module.StorageMigrationService(layout, settings=settings).migrate()
        settings.setValue("storage/migration_state", "failed")
        settings.setValue("storage/legacy_data_root", str(legacy_root.resolve()))
        settings.setValue("storage/active_data_root", str(legacy_root.resolve()))
        settings.setValue("db/last_path", str(legacy_db.resolve()))
        settings.setValue("paths/database_dir", str((legacy_root / "Database").resolve()))
        settings.sync()

        shutil.rmtree(legacy_root)
        self.assertFalse(legacy_root.exists())

        self.window = app_module.App()
        self.window.show()
        self._drain_events()

        self.assertEqual(self.window.data_root, preferred_root.resolve())
        self.assertFalse(legacy_root.exists())
        self.assertFalse((legacy_root / "Database" / "default.db").exists())
        self.assertFalse((legacy_root / "history").exists())
        self.assertFalse((legacy_root / "help").exists())
        self.assertFalse((legacy_root / "logs").exists())

    def case_portable_mode_skips_storage_migration_and_legacy_adoption(self):
        self._close_window()
        portable_root = self.root / "portable-root"
        legacy_root = self.local_appdata / APP_NAME
        legacy_db = legacy_root / "Database" / "portable_legacy.db"
        self._create_profile_database(legacy_db)

        def _portable_layout(
            *, settings=None, app_name=APP_NAME, portable=None, active_data_root=None
        ):
            chosen_root = (
                Path(active_data_root).resolve()
                if active_data_root is not None
                else portable_root.resolve()
            )
            return AppStorageLayout(
                app_name=app_name,
                portable=True,
                settings_root=portable_root.resolve(),
                settings_path=(portable_root / "settings.ini").resolve(),
                lock_path=(portable_root / f"{app_name}.lock").resolve(),
                preferred_data_root=portable_root.resolve(),
                active_data_root=chosen_root,
                legacy_data_roots=(),
                database_dir=chosen_root / "Database",
                exports_dir=chosen_root / "exports",
                logs_dir=chosen_root / "logs",
                backups_dir=chosen_root / "backups",
                history_dir=chosen_root / "history",
                help_dir=chosen_root / "help",
            )

        with (
            mock.patch.object(
                app_module, "settings_path", return_value=portable_root / "settings.ini"
            ),
            mock.patch.object(
                app_module, "resolve_app_storage_layout", side_effect=_portable_layout
            ),
            mock.patch.object(app_module, "QMessageBox") as message_box,
        ):
            self.window = app_module.App()
            self.window.show()
            self._drain_events()

        self.assertEqual(self.window.data_root, portable_root.resolve())
        self.assertNotEqual(self.window.data_root, legacy_root.resolve())
        self.assertFalse(message_box.called)

    def case_bundled_themes_are_available_and_not_persisted_as_user_library_entries(self):
        library = self.window._load_theme_library()
        for name in starter_theme_names():
            self.assertIn(name, library)

        self.window._save_theme_library(library)
        stored_payload = json.loads(self.window.settings.value("theme/library_json", "{}", str))
        for name in starter_theme_names():
            self.assertNotIn(name, stored_payload)

    def case_create_new_profile_and_browse_profile_switch_workspace(self):
        created_path = self.window.database_dir / "Label_Test.db"
        external_path = self.root / "external-profile.db"
        self._create_profile_database(external_path)

        def _activate_now(path, **kwargs):
            prepared_path = str(Path(path))
            self.window._activate_profile(prepared_path)
            on_activated = kwargs.get("on_activated")
            if callable(on_activated):
                on_activated(prepared_path)
            return "sync-profile-activation"

        with (
            mock.patch.object(
                self.window,
                "_activate_profile_in_background",
                side_effect=_activate_now,
            ),
            mock.patch.object(
                app_module.QInputDialog,
                "getText",
                return_value=("Label Test", True),
            ),
            mock.patch.object(app_module.QMessageBox, "information", return_value=None),
        ):
            self.window.create_new_profile()

        self.assertEqual(self.window.current_db_path, str(created_path))
        self.assertTrue(created_path.exists())
        self.assertGreaterEqual(self.window.profile_combo.findData(str(created_path)), 0)

        with (
            mock.patch.object(
                self.window,
                "_activate_profile_in_background",
                side_effect=_activate_now,
            ),
            mock.patch.object(
                app_module.QFileDialog,
                "getOpenFileName",
                return_value=(str(external_path), "SQLite DB (*.db)"),
            ),
        ):
            self.window.browse_profile()

        self.assertEqual(self.window.current_db_path, str(external_path))
        self.assertGreaterEqual(self.window.profile_combo.findData(str(external_path)), 0)

    def case_profile_switch_loading_feedback_waits_for_catalog_refresh_completion(self):
        target_path = self.root / "switched-profile.db"
        self._create_profile_database(target_path)
        feedback = _FakeStartupSplashController()
        refresh_callbacks: dict[str, object] = {}
        activated: list[str] = []

        def _create_feedback():
            feedback.show()
            return feedback

        def _prepare_now(
            _window,
            path,
            *,
            on_success,
            on_finished=None,
            **kwargs,
        ):
            del kwargs
            on_success(str(Path(path)))
            if callable(on_finished):
                on_finished()
            return "prepared-profile"

        def _deferred_refresh(window, *args, **kwargs):
            del window, args
            refresh_callbacks["finished"] = kwargs.get("on_finished")
            refresh_callbacks["complete"] = kwargs.get("on_complete")
            return "deferred-profile-refresh"

        with (
            mock.patch.object(
                self.window,
                "_create_runtime_loading_feedback",
                side_effect=_create_feedback,
            ),
            mock.patch.object(
                app_module.App,
                "_prepare_profile_database_background",
                autospec=True,
                side_effect=_prepare_now,
            ),
            mock.patch.object(
                app_module.App,
                "_refresh_catalog_ui_in_background",
                autospec=True,
                side_effect=_deferred_refresh,
            ),
        ):
            self.window._activate_profile_in_background(
                str(target_path),
                on_activated=lambda prepared_path: activated.append(prepared_path),
            )
            self._drain_events()

        self.assertEqual(self.window.current_db_path, str(target_path))
        self.assertTrue(callable(refresh_callbacks.get("finished")))
        self.assertTrue(callable(refresh_callbacks.get("complete")))
        self.assertEqual(feedback.show_calls, 1)
        self.assertEqual(feedback.finish_calls, [])
        self.assertEqual(feedback.phase_updates[0][0], StartupPhase.OPENING_PROFILE_DB)
        self.assertEqual(feedback.current_phase, StartupPhase.LOADING_CATALOG)
        self.assertTrue(feedback.progress_updates)
        self.assertEqual(
            [update[0] for update in feedback.progress_updates],
            sorted(update[0] for update in feedback.progress_updates),
        )
        self.assertEqual(activated, [])

        refresh_callbacks["finished"]()
        refresh_callbacks["complete"]()
        self._drain_events()

        self.assertEqual(activated, [str(target_path)])
        self.assertEqual(feedback.current_progress, 100)
        self.assertEqual(feedback.finish_calls, [self.window])

    def case_profile_switch_reuses_prepared_database_activation_path(self):
        target_path = self.root / "prepared-profile.db"
        self._create_profile_database(target_path)
        feedback = _FakeStartupSplashController()
        open_calls: list[bool] = []
        original_open_database = app_module.App.open_database

        def _create_feedback():
            feedback.show()
            return feedback

        def _prepare_now(
            _window,
            path,
            *,
            on_success,
            on_finished=None,
            **kwargs,
        ):
            del kwargs
            on_success(str(Path(path)))
            if callable(on_finished):
                on_finished()
            return "prepared-profile"

        def _spy_open_database(window, path, *args, **kwargs):
            del args
            open_calls.append(bool(kwargs.get("schema_prepared")))
            return original_open_database(window, path, **kwargs)

        with (
            mock.patch.object(
                self.window,
                "_create_runtime_loading_feedback",
                side_effect=_create_feedback,
            ),
            mock.patch.object(
                app_module.App,
                "_prepare_profile_database_background",
                autospec=True,
                side_effect=_prepare_now,
            ),
            mock.patch.object(
                app_module.App,
                "_refresh_catalog_ui_in_background",
                autospec=True,
                side_effect=_no_catalog_background_refresh,
            ),
            mock.patch.object(
                app_module.App,
                "open_database",
                autospec=True,
                side_effect=_spy_open_database,
            ),
        ):
            self.window._activate_profile_in_background(str(target_path))
            self._drain_events()

        self.assertEqual(open_calls, [True])
        self.assertEqual(self.window.current_db_path, str(target_path))

    def case_trace_logging_sanitizes_reserved_logrecord_field_names(self):
        with mock.patch.object(self.window.trace_logger, "log") as trace_log:
            self.window._log_event(
                "party.import.zip",
                "Imported Party archive",
                created=3,
                process=12,
                warnings=["duplicate legal name"],
            )

        trace_log.assert_called_once()
        extra = trace_log.call_args.kwargs.get("extra")
        self.assertIsInstance(extra, dict)
        assert isinstance(extra, dict)
        self.assertEqual(extra.get("event"), "party.import.zip")
        self.assertEqual(extra.get("field_created"), 3)
        self.assertEqual(extra.get("field_process"), 12)
        self.assertEqual(extra.get("warnings"), ["duplicate legal name"])
        self.assertNotIn("created", extra)
        self.assertNotIn("process", extra)

    def case_prepared_database_open_skips_schema_work(self):
        target_path = self.root / "prepared-open.db"
        self._create_profile_database(target_path)

        with (
            mock.patch.object(self.window, "init_db", autospec=True) as init_db,
            mock.patch.object(self.window, "migrate_schema", autospec=True) as migrate_schema,
        ):
            self.window.open_database(str(target_path), schema_prepared=True)

        init_db.assert_not_called()
        migrate_schema.assert_not_called()
        self.assertEqual(self.window.current_db_path, str(target_path))

    def case_cancelled_profile_creation_and_restore_leave_shell_idle(self):
        initial_path = self.window.current_db_path

        with mock.patch.object(
            app_module.QInputDialog,
            "getText",
            return_value=("", False),
        ):
            self.window.create_new_profile()

        with mock.patch.object(
            app_module.QFileDialog,
            "getOpenFileName",
            return_value=("", ""),
        ):
            self.window.restore_database()

        self.assertEqual(self.window.current_db_path, initial_path)
        self.assertFalse(self.window.background_tasks.has_running_tasks())
        profiles = [
            Path(self.window.profile_combo.itemData(i)).name
            for i in range(self.window.profile_combo.count())
        ]
        self.assertEqual(profiles, [Path(initial_path).name])

    def case_filtered_select_all_counts_only_visible_tracks(self):
        titles = [
            "Crossroads of the Unwritten Self",
            "Crossroads of the Unwritten Self (Remix)",
            "Crossroads of the Unwritten Self - Live",
            "Orbit Drift",
        ]
        for index, title in enumerate(titles, start=1):
            self._create_track(index=index, title=title, album_title="Selection Test")

        self.window.refresh_table()
        self.window.search_field.setText("Crossroads of the Unwritten Self")
        self.window.apply_search_filter()
        self.app.processEvents()

        visible_rows = [
            row
            for row in range(self.window.table.rowCount())
            if not self.window.table.isRowHidden(row)
        ]
        self.assertEqual(len(visible_rows), 3)

        self.window.table.selectAll()
        self.app.processEvents()

        selected_ids = self.window._selected_track_ids()
        self.assertEqual(len(selected_ids), len(visible_rows))

    def case_delete_entry_history_stays_a_single_visible_user_action(self):
        track_id = self._create_track(index=121, title="Delete History Song")
        self.window.refresh_table()
        row = self.window._row_for_id(track_id)
        self.assertGreaterEqual(row, 0)
        self.window.table.setCurrentCell(row, 0)
        self.app.processEvents()

        original_rebuild = self.window._rebuild_table_headers

        def _rebuild_with_internal_layout_ping():
            original_rebuild()
            self.window._on_header_layout_changed()

        with (
            mock.patch.object(
                self.window,
                "_rebuild_table_headers",
                side_effect=_rebuild_with_internal_layout_ping,
            ),
            mock.patch.object(
                app_module.QMessageBox,
                "exec",
                return_value=app_module.QMessageBox.Yes,
            ),
            mock.patch.object(app_module.QMessageBox, "critical") as critical_mock,
        ):
            self.window.delete_entry()

        self.app.processEvents()
        critical_mock.assert_not_called()
        self.assertIsNone(self.window.track_service.fetch_track_snapshot(track_id))
        self.assertEqual(
            self.window.undo_action.text(),
            "Undo Delete Track: Delete History Song",
        )

        visible_history = self.window.history_manager.list_entries(limit=20)
        all_history = self.window.history_manager.list_entries(limit=20, include_hidden=True)
        self.assertEqual(
            [entry.label for entry in visible_history], ["Delete Track: Delete History Song"]
        )
        self.assertEqual(
            [entry.label for entry in all_history], ["Delete Track: Delete History Song"]
        )

        dialog = app_module.HistoryDialog(self.window, parent=self.window)
        try:
            self.assertEqual(dialog.history_table.rowCount(), 1)
            self.assertEqual(
                dialog.history_table.item(0, 2).text(), "Delete Track: Delete History Song"
            )
        finally:
            dialog.close()
            self.app.processEvents()

        self.window.history_undo()
        self.app.processEvents()
        self.assertIsNotNone(self.window.track_service.fetch_track_snapshot(track_id))
        self.assertEqual(
            self.window.redo_action.text(),
            "Redo Delete Track: Delete History Song",
        )

        self.window.history_redo()
        self.app.processEvents()
        self.assertIsNone(self.window.track_service.fetch_track_snapshot(track_id))
        self.assertEqual(
            self.window.history_manager.list_entries(limit=20)[0].label,
            "Delete Track: Delete History Song",
        )

    def case_catalog_release_browser_opens_as_tabified_dock(self):
        track_id = self._create_track(index=101, title="Release Dock Track")
        self.window.release_service.create_release(
            app_module.ReleasePayload(
                title="Release Dock Test",
                primary_artist="Moonwake",
                release_type="single",
                release_date="2026-03-17",
                placements=[
                    app_module.ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.window.refresh_table()

        self.window.open_release_browser()
        self.app.processEvents()

        dock = self.window.release_browser_dock
        panel = dock.widget()
        self.assertFalse(dock.isHidden())
        self.assertEqual(dock.objectName(), "releaseBrowserDock")
        self.assertEqual(panel.objectName(), "releaseBrowserPanel")
        self.assertIn(dock, self.window.tabifiedDockWidgets(self.window.catalog_table_dock))

        panel.release_table.selectRow(0)
        panel._emit_filter_current()
        self.app.processEvents()

        visible_rows = [
            row
            for row in range(self.window.table.rowCount())
            if not self.window.table.isRowHidden(row)
        ]
        self.assertEqual(len(visible_rows), 1)
        self.assertFalse(dock.isHidden())

    def case_release_browser_filter_replaces_active_search_filter(self):
        release_track_ids = [
            self._create_track(index=141, title="Release Filter One", album_title="Filter Release"),
            self._create_track(index=142, title="Release Filter Two", album_title="Filter Release"),
        ]
        other_track_id = self._create_track(index=143, title="Unrelated Search Match")
        self.window.release_service.create_release(
            app_module.ReleasePayload(
                title="Filter Release",
                primary_artist="Moonwake",
                release_type="album",
                release_date="2026-03-17",
                placements=[
                    app_module.ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=index + 1,
                        sequence_number=index + 1,
                    )
                    for index, track_id in enumerate(release_track_ids)
                ],
            )
        )
        self.window.refresh_table()
        self.window.search_field.setText("Unrelated Search Match")
        self.window.apply_search_filter()
        self.app.processEvents()
        visible_before = [
            int(self.window.table.item(row, 0).text())
            for row in range(self.window.table.rowCount())
            if not self.window.table.isRowHidden(row)
        ]
        self.assertEqual(visible_before, [other_track_id])

        self.window.open_release_browser()
        self.app.processEvents()
        panel = self.window.release_browser_dock.widget()
        panel.release_table.selectRow(0)
        panel._emit_filter_current()
        self.app.processEvents()

        visible_after = {
            int(self.window.table.item(row, 0).text())
            for row in range(self.window.table.rowCount())
            if not self.window.table.isRowHidden(row)
        }
        self.assertEqual(visible_after, set(release_track_ids))
        self.assertEqual(self.window.search_field.text(), "")
        self.assertEqual(set(self.window._selected_track_ids()), set(release_track_ids))

    def case_release_browser_selection_scope_tracks_catalog_selection_and_override(self):
        track_ids = [
            self._create_track(index=151, title="Selection Orbit One"),
            self._create_track(index=152, title="Selection Orbit Two"),
            self._create_track(index=153, title="Selection Orbit Three"),
        ]
        self.window.refresh_table()
        self._select_track_ids(track_ids[:2])

        self.window.open_release_browser()
        self.app.processEvents()

        panel = self.window.release_browser_dock.widget()
        state = panel.selection_scope_state()
        self.assertEqual(state.track_ids, tuple(track_ids[:2]))
        self.assertEqual(state.source_label, "Catalog selection")
        self.assertIn("Selection Orbit One", state.preview_text)
        self.assertFalse(state.override_active)

        panel._selection_override_track_ids = [track_ids[2]]
        panel.refresh_selection_scope()
        override_state = panel.selection_scope_state()
        self.assertEqual(override_state.track_ids, (track_ids[2],))
        self.assertTrue(override_state.override_active)
        self.assertEqual(panel.selection_banner.scope_label.text(), "Pinned chooser override")

    def case_work_manager_dock_uses_live_track_selection(self):
        track_ids = [
            self._create_track(index=111, title="Work Dock One"),
            self._create_track(index=112, title="Work Dock Two"),
            self._create_track(index=113, title="Work Dock Three"),
        ]
        work_id = self.window.work_service.create_work(
            app_module.WorkPayload(title="Docked Work Manager")
        )

        self.window.refresh_table()
        self._select_track_ids(track_ids[:2])

        self.window.open_work_manager()
        self.app.processEvents()

        dock = self.window.work_manager_dock
        panel = dock.widget()
        self.assertFalse(dock.isHidden())
        self.assertEqual(dock.objectName(), "workManagerDock")
        self.assertEqual(panel.objectName(), "workBrowserPanel")
        self.assertIn(dock, self.window.tabifiedDockWidgets(self.window.catalog_table_dock))
        self.assertEqual(panel.selection_scope_state().track_ids, tuple(track_ids[:2]))

        panel.table.selectRow(0)
        panel.link_selected_tracks()
        detail = self.window.work_service.fetch_work_detail(work_id)
        self.assertEqual(set(detail.track_ids), set(track_ids[:2]))

        panel._selection_override_track_ids = [track_ids[2]]
        panel.refresh_selection_scope()
        panel.link_selected_tracks()
        detail = self.window.work_service.fetch_work_detail(work_id)
        self.assertEqual(set(detail.track_ids), set(track_ids))
        self.assertTrue(panel.selection_scope_state().override_active)
        self.assertFalse(dock.isHidden())

    def case_work_manager_shows_stored_works_without_linked_track_narrowing(self):
        linked_track_id = self._create_track(index=171, title="Linked Work Track")
        linked_work_id = self.window.work_service.create_work(
            app_module.WorkPayload(title="Linked Work", track_ids=[linked_track_id])
        )
        other_work_id = self.window.work_service.create_work(
            app_module.WorkPayload(title="Standalone Stored Work")
        )
        self.window.conn.commit()

        self.window.open_work_manager(linked_track_id=linked_track_id)
        self.app.processEvents()

        panel = self.window.work_manager_dock.widget()
        displayed_ids = {
            int(panel.table.item(row, 0).text())
            for row in range(panel.table.rowCount())
            if panel.table.item(row, 0) is not None
        }
        self.assertIn(linked_work_id, displayed_ids)
        self.assertIn(other_work_id, displayed_ids)
        self.assertEqual(panel.selected_work_id(), linked_work_id)

        panel.search_edit.setText("Standalone")
        self.app.processEvents()
        self.assertEqual(panel.table.rowCount(), 1)

        self.window.open_work_manager()
        self.app.processEvents()
        self.assertEqual(panel.search_edit.text(), "")
        displayed_ids = {
            int(panel.table.item(row, 0).text())
            for row in range(panel.table.rowCount())
            if panel.table.item(row, 0) is not None
        }
        self.assertIn(linked_work_id, displayed_ids)
        self.assertIn(other_work_id, displayed_ids)

    def case_work_manager_creates_governed_child_track_in_add_panel(self):
        work_id = self.window.work_service.create_work(
            app_module.WorkPayload(
                title="Docked Parent Work",
                iswc="T-123.456.789-0",
            )
        )
        existing_parent_track_id = self.window.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-10101",
                track_title="Docked Parent Work Original",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Docked Parent Work",
                release_date="2026-03-17",
                track_length_sec=205,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
                work_id=work_id,
                relationship_type="original",
            )
        )

        panel = self.window.open_work_manager()
        self.app.processEvents()
        panel.focus_work(work_id)
        self.app.processEvents()

        self._button_by_text(panel.manage_actions_cluster, "Add Track to Work").click()
        self.app.processEvents()

        self.assertFalse(self.window.add_data_dock.isHidden())
        self.assertTrue(self.window.add_data_work_context_group.isVisible())
        self.assertEqual(self.window.add_data_title.text(), "Add Track")
        self.assertEqual(self.window.save_button.text(), "Save Governed Track")
        self.assertIn("Docked Parent Work", self.window.add_data_work_context_summary.text())
        self.assertEqual(self.window.track_title_field.text(), "Docked Parent Work")
        self.assertEqual(self.window.iswc_field.text(), "T-123.456.789-0")
        relationship_index = self.window.add_data_work_relationship_combo.findData("remix")
        self.assertGreaterEqual(relationship_index, 0)
        self.window.add_data_work_relationship_combo.setCurrentIndex(relationship_index)
        self.app.processEvents()
        self.assertEqual(self.window.add_data_work_relationship_combo.currentData(), "remix")
        self.assertTrue(self.window.add_data_work_parent_combo.isEnabled())
        parent_index = self.window.add_data_work_parent_combo.findData(existing_parent_track_id)
        self.assertGreaterEqual(parent_index, 0)
        self.window.add_data_work_parent_combo.setCurrentIndex(parent_index)
        self.app.processEvents()

        self.window.artist_field.setCurrentText("Moonwake")
        self.window.track_title_field.setText("Docked Parent Work Remix")
        with mock.patch.object(
            app_module.QMessageBox,
            "information",
            return_value=app_module.QMessageBox.Ok,
        ):
            self.window.save()
        self.app.processEvents()

        row = self.window.conn.execute(
            """
            SELECT id, work_id, parent_track_id, relationship_type
            FROM Tracks
            WHERE track_title=?
            ORDER BY id DESC
            LIMIT 1
            """,
            ("Docked Parent Work Remix",),
        ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        track_id, linked_work_id, created_parent_track_id, relationship_type = row
        self.assertEqual(linked_work_id, work_id)
        self.assertEqual(created_parent_track_id, existing_parent_track_id)
        self.assertEqual(relationship_type, "remix")
        detail = self.window.work_service.fetch_work_detail(work_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertIn(int(track_id), detail.track_ids)
        self.assertGreaterEqual(self.window.add_data_work_parent_combo.count(), 2)

    def case_create_work_offers_first_track_creation_context(self):
        panel = self.window.open_work_manager()
        self.app.processEvents()

        submitted_descriptions: list[str] = []

        def _run_bundle_task_and_capture(window, **kwargs):
            submitted_descriptions.append(str(kwargs.get("description") or ""))
            return self._run_bundle_task_inline(window, **kwargs)

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=_run_bundle_task_and_capture,
            ),
            mock.patch.object(
                self.window.work_service,
                "create_work",
                side_effect=AssertionError("main-thread create_work should not run"),
            ),
            mock.patch.object(
                app_module.WorkEditorDialog,
                "exec",
                return_value=app_module.QDialog.Accepted,
            ),
            mock.patch.object(
                app_module.WorkEditorDialog,
                "payload",
                return_value=app_module.WorkPayload(
                    title="Immediate First Track Work",
                    iswc="T-123.456.789-0",
                ),
            ),
            mock.patch.object(
                app_module.QMessageBox,
                "question",
                return_value=app_module.QMessageBox.Yes,
            ),
        ):
            self._button_by_text(panel.manage_actions_cluster, "Create Work").click()
            self.app.processEvents()

        self.assertEqual(
            submitted_descriptions,
            ["Saving work metadata, contributors, and linked tracks..."],
        )
        works = [
            record
            for record in self.window.work_service.list_works(
                search_text="Immediate First Track Work"
            )
            if record.title == "Immediate First Track Work"
        ]
        self.assertEqual(len(works), 1)
        work_id = works[0].id
        self.assertEqual(panel._selected_work_id(), work_id)
        self.assertFalse(self.window.add_data_dock.isHidden())
        self.assertTrue(self.window.add_data_work_context_group.isVisible())
        self.assertEqual(self.window.add_data_title.text(), "Add Track")
        self.assertIn(
            "Immediate First Track Work", self.window.add_data_work_context_summary.text()
        )
        self.assertEqual(self.window.track_title_field.text(), "Immediate First Track Work")
        self.assertEqual(self.window.iswc_field.text(), "T-123.456.789-0")
        context = self.window._current_work_track_context()
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["work_id"], work_id)

    def case_work_manager_update_runs_in_background_bundle_task(self):
        work_id = self.window.work_service.create_work(
            app_module.WorkPayload(
                title="Background Save Work",
                iswc="T-111.222.333-4",
            )
        )
        panel = self.window.open_work_manager()
        self.app.processEvents()
        panel.focus_work(work_id)
        self.app.processEvents()

        submitted_descriptions: list[str] = []

        def _run_bundle_task_and_capture(window, **kwargs):
            submitted_descriptions.append(str(kwargs.get("description") or ""))
            return self._run_bundle_task_inline(window, **kwargs)

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=_run_bundle_task_and_capture,
            ),
            mock.patch.object(
                self.window.work_service,
                "update_work",
                side_effect=AssertionError("main-thread update_work should not run"),
            ),
            mock.patch.object(
                app_module.WorkEditorDialog,
                "exec",
                return_value=app_module.QDialog.Accepted,
            ),
            mock.patch.object(
                app_module.WorkEditorDialog,
                "payload",
                return_value=app_module.WorkPayload(
                    title="Background Save Work Updated",
                    iswc="T-999.888.777-6",
                ),
            ),
        ):
            self._button_by_text(panel.manage_actions_cluster, "Edit").click()
            self.app.processEvents()

        self.assertEqual(
            submitted_descriptions,
            ["Updating work metadata, contributors, and linked tracks..."],
        )
        detail = self.window.work_service.fetch_work_detail(work_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.work.title, "Background Save Work Updated")
        self.assertEqual(detail.work.iswc, "T-999.888.777-6")
        self.assertEqual(panel._selected_work_id(), work_id)

    def case_work_manager_opens_album_dialog_for_selected_work(self):
        work_id = self.window.work_service.create_work(
            app_module.WorkPayload(title="Album Parent Work")
        )
        panel = self.window.open_work_manager()
        self.app.processEvents()
        panel.focus_work(work_id)
        self.app.processEvents()

        def _save_album_in_dialog(dialog):
            self.assertEqual(dialog.windowTitle(), "Add Album")
            dialog.album_title.setCurrentText("Unified Governed Album")
            first_section = dialog._track_sections[0]
            second_section = dialog._track_sections[1]
            self.assertEqual(first_section.selected_governance_mode(), "link_existing_work")
            self.assertEqual(first_section.selected_work_id(), work_id)
            self.assertEqual(second_section.selected_governance_mode(), "link_existing_work")
            self.assertEqual(second_section.selected_work_id(), work_id)
            first_relationship_index = first_section.relationship_type.findData("alternate_master")
            second_relationship_index = second_section.relationship_type.findData(
                "alternate_master"
            )
            first_section.relationship_type.setCurrentIndex(first_relationship_index)
            second_section.relationship_type.setCurrentIndex(second_relationship_index)
            first_section.track_title.setText("Unified Governed Mix")
            first_section.artist_name.setCurrentText("Moonwake")
            second_section.track_title.setText("Unified Governed Dub")
            second_section.artist_name.setCurrentText("Moonwake")
            dialog.save_album()
            return dialog.result()

        with mock.patch.object(
            app_module.AlbumEntryDialog,
            "exec",
            new=_save_album_in_dialog,
        ):
            self._button_by_text(panel.manage_actions_cluster, "Add Album to Work").click()
            self.app.processEvents()

        created_rows = self.window.conn.execute(
            """
            SELECT track_title, work_id, relationship_type
            FROM Tracks
            WHERE album_id = (
                SELECT id FROM Albums WHERE title=? ORDER BY id DESC LIMIT 1
            )
            ORDER BY track_title
            """,
            ("Unified Governed Album",),
        ).fetchall()
        self.assertEqual(
            created_rows,
            [
                ("Unified Governed Dub", work_id, "alternate_master"),
                ("Unified Governed Mix", work_id, "alternate_master"),
            ],
        )

    def case_unified_creation_workflow_opens_auto_governed_album_fallback(self):
        def _save_album_in_dialog(dialog):
            self.assertEqual(dialog.windowTitle(), "Add Album")
            dialog.album_title.setCurrentText("Unified Auto Governed Album")
            first_section = dialog._track_sections[0]
            second_section = dialog._track_sections[1]
            self.assertEqual(first_section.selected_governance_mode(), "create_new_work")
            self.assertEqual(second_section.selected_governance_mode(), "create_new_work")
            first_section.track_title.setText("Unified Auto Governed One")
            first_section.artist_name.setCurrentText("Moonwake")
            first_section.iswc.setText("T-123.456.789-0")
            second_section.track_title.setText("Unified Auto Governed Two")
            second_section.artist_name.setCurrentText("Moonwake")
            second_section.iswc.setText("T-123.456.780-0")
            dialog.save_album()
            return dialog.result()

        with mock.patch.object(
            app_module.AlbumEntryDialog,
            "exec",
            new=_save_album_in_dialog,
        ):
            self.window.add_album_action.trigger()
            self.app.processEvents()

        rows = self.window.conn.execute(
            """
            SELECT t.track_title, t.work_id, t.relationship_type, w.title, w.iswc
            FROM Tracks t
            JOIN Works w ON w.id = t.work_id
            WHERE t.album_id = (
                SELECT id FROM Albums WHERE title=? ORDER BY id DESC LIMIT 1
            )
            ORDER BY t.track_title
            """,
            ("Unified Auto Governed Album",),
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "Unified Auto Governed One")
        self.assertEqual(
            rows[0][2:],
            ("original", "Unified Auto Governed One", "T-123.456.789-0"),
        )
        self.assertEqual(rows[1][0], "Unified Auto Governed Two")
        self.assertEqual(
            rows[1][2:],
            ("original", "Unified Auto Governed Two", "T-123.456.780-0"),
        )

    def case_relationship_search_work_entity_focuses_requested_work_manager_row(self):
        first_work_id = self.window.work_service.create_work(
            app_module.WorkPayload(title="Search Focus Work One")
        )
        second_work_id = self.window.work_service.create_work(
            app_module.WorkPayload(title="Search Focus Work Two")
        )
        self.assertGreater(first_work_id, 0)

        panel = self.window.open_work_manager()
        self.app.processEvents()
        panel.search_edit.setText("No Matching Work")
        self.app.processEvents()
        self.assertEqual(panel.table.rowCount(), 0)

        self.window._open_entity_from_relationship_search("work", second_work_id)
        self.app.processEvents()

        panel = self.window.work_manager_dock.widget()
        self.assertEqual(panel.search_edit.text(), "")
        self.assertEqual(panel._selected_work_id(), second_work_id)

    def case_quality_governance_issue_routes_track_scope_to_work_manager(self):
        self.window.work_service.create_work(app_module.WorkPayload(title="Quality Routing Work"))
        track_id = self._create_track(index=171, title="Quality Routed Track")

        issue = app_module.QualityIssue(
            issue_type="track_missing_linked_work",
            severity="warning",
            title="Track Missing Linked Work",
            details="Track should be assigned to a parent work.",
            entity_type="track",
            entity_id=track_id,
            track_id=track_id,
        )
        self.window._open_issue_from_dashboard(issue)
        self.app.processEvents()

        panel = self.window.work_manager_dock.widget()
        state = panel.selection_scope_state()
        self.assertEqual(state.track_ids, (track_id,))
        self.assertTrue(state.override_active)
        self.assertEqual(panel.selection_banner.scope_label.text(), "Pinned chooser override")
        self.assertIsNone(panel.linked_track_id)
        self.assertFalse(self.window.work_manager_dock.isHidden())

    def case_global_search_opens_as_dock_and_keeps_entity_navigation_live(self):
        track_id = self._create_track(index=121, title="Searchable Dock Track")
        self.window.refresh_table()

        self.window.open_global_search()
        self.app.processEvents()

        dock = self.window.global_search_dock
        panel = dock.widget()
        self.assertFalse(dock.isHidden())
        self.assertEqual(dock.objectName(), "globalSearchDock")
        self.assertEqual(panel.objectName(), "globalSearchPanel")
        self.assertIn(dock, self.window.tabifiedDockWidgets(self.window.catalog_table_dock))
        self.assertGreaterEqual(panel.results_table.rowCount(), 1)
        self.assertEqual(panel.results_table.currentRow(), -1)
        self.assertIn("catalog overview", panel.results_status_label.text().lower())

        panel.entity_combo.setCurrentText("Tracks")
        panel.search_edit.setText("Searchable Dock Track")
        panel.refresh_results()
        self.app.processEvents()
        self.assertGreaterEqual(panel.results_table.rowCount(), 1)
        panel.results_table.selectRow(0)

        with mock.patch.object(self.window, "open_selected_editor") as open_selected_editor:
            panel.open_selected_result()

        open_selected_editor.assert_called_once_with(track_id)
        self.assertTrue(dock.isVisible())

    def case_workspace_docks_use_north_tabs_and_remain_tabified_across_fullscreen_cycle(self):
        track_id = self._create_track(index=166, title="Dock Tab Visibility Track")
        self.window.release_service.create_release(
            app_module.ReleasePayload(
                title="Dock Tab Visibility Release",
                primary_artist="Moonwake",
                release_type="single",
                release_date="2026-03-17",
                placements=[
                    app_module.ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.window.refresh_table()

        self.window.open_release_browser()
        self.app.processEvents()
        self.assertEqual(
            self.window.tabPosition(app_module.Qt.RightDockWidgetArea),
            app_module.QTabWidget.North,
        )
        self.assertTrue(self.window.release_browser_dock.widget().isVisible())

        self.window.open_work_manager()
        self.app.processEvents()
        self.assertTrue(self.window.work_manager_dock.widget().isVisible())
        self.assertIn(
            self.window.work_manager_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )

        self.window.open_global_search()
        self.app.processEvents()
        self.assertTrue(self.window.global_search_dock.widget().isVisible())
        self.assertIn(
            self.window.global_search_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )

        self.window.showFullScreen()
        self.app.processEvents()
        self.window.showNormal()
        self.app.processEvents()

        self.assertEqual(
            self.window.tabPosition(app_module.Qt.RightDockWidgetArea),
            app_module.QTabWidget.North,
        )
        self.assertIn(
            self.window.release_browser_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )
        self.assertIn(
            self.window.work_manager_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )
        self.assertIn(
            self.window.global_search_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )
        self.assertTrue(self.window.global_search_dock.widget().isVisible())

    def case_top_chrome_boundary_persists_across_ribbon_visibility_and_window_state_changes(self):
        track_id = self._create_track(index=168, title="Boundary Validation Track")
        self.window.release_service.create_release(
            app_module.ReleasePayload(
                title="Boundary Validation Release",
                primary_artist="Moonwake",
                release_type="single",
                release_date="2026-03-17",
                placements=[
                    app_module.ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.window.refresh_table()
        self.window.open_release_browser()
        self.app.processEvents()

        tab_bar = self._workspace_dock_tab_bar()
        self.assertEqual(self.window.toolbar.contentsMargins().bottom(), 5)
        self.assertGreaterEqual(tab_bar.geometry().top(), self.window.toolbar.geometry().bottom())
        self.assertEqual(self.window.action_ribbon_toolbar.property("role"), "actionRibbonToolbar")

        self.window.showFullScreen()
        self.app.processEvents()
        self.window.showNormal()
        self.app.processEvents()
        self.assertEqual(self.window.toolbar.contentsMargins().bottom(), 5)
        self.assertGreaterEqual(tab_bar.geometry().top(), self.window.toolbar.geometry().bottom())

        self.window.action_ribbon_visibility_action.trigger()
        self.app.processEvents()
        self.assertFalse(self.window.action_ribbon_toolbar.isVisible())
        self.assertEqual(self.window.toolbar.contentsMargins().bottom(), 5)

        self.window.action_ribbon_visibility_action.trigger()
        self.app.processEvents()
        self.assertTrue(self.window.action_ribbon_toolbar.isVisible())
        self.assertEqual(self.window.toolbar.contentsMargins().bottom(), 5)

        self.window.open_global_search()
        self.app.processEvents()
        self.window.global_search_dock.raise_()
        self.app.processEvents()
        self.window.release_browser_dock.raise_()
        self.app.processEvents()
        self.assertEqual(self.window.toolbar.contentsMargins().bottom(), 5)

    def case_workspace_panels_keep_actions_and_saved_search_controls_inside_scroll_safe_surfaces(
        self,
    ):
        track_id = self._create_track(index=167, title="Reachable Action Track")
        self.window.release_service.create_release(
            app_module.ReleasePayload(
                title="Reachable Action Release",
                primary_artist="Moonwake",
                release_type="single",
                release_date="2026-03-17",
                placements=[
                    app_module.ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.window.refresh_table()

        self.window.resize(980, 620)
        self.window.open_release_browser()
        self.app.processEvents()
        release_panel = self.window.release_browser_dock.widget()
        self.assertEqual(release_panel.overview_tab.property("role"), "workspaceCanvas")
        self.assertEqual(release_panel.tracks_tab.property("role"), "workspaceCanvas")
        self.assertTrue(
            self._is_within_scroll_content(
                release_panel.detail_scroll_area, release_panel.actions_cluster
            )
        )

        self.window.open_global_search()
        self.app.processEvents()
        search_panel = self.window.global_search_dock.widget()
        self.assertEqual(search_panel.right_container.property("role"), "workspaceCanvas")
        self.assertEqual(search_panel.results_tab.property("role"), "workspaceCanvas")
        self.assertEqual(search_panel.relationships_tab.property("role"), "workspaceCanvas")
        self.assertTrue(
            self._is_within_scroll_content(
                search_panel.saved_searches_scroll_area, search_panel.delete_saved_button
            )
        )

        self.window.open_work_manager()
        self.app.processEvents()
        work_panel = self.window.work_manager_dock.widget()
        create_button = self._button_by_text(work_panel.manage_actions_cluster, "Create Work")
        add_track_button = self._button_by_text(
            work_panel.manage_actions_cluster, "Add Track to Work"
        )
        add_album_button = self._button_by_text(
            work_panel.manage_actions_cluster, "Add Album to Work"
        )
        edit_button = self._button_by_text(work_panel.manage_actions_cluster, "Edit")
        duplicate_button = self._button_by_text(work_panel.manage_actions_cluster, "Duplicate")
        link_button = self._button_by_text(
            work_panel.manage_actions_cluster, "Link Selected Tracks"
        )
        delete_button = self._button_by_text(work_panel.manage_actions_cluster, "Delete")

        self.assertGreater(edit_button.geometry().left() - create_button.geometry().right(), 0)
        self.assertGreater(duplicate_button.geometry().top() - create_button.geometry().bottom(), 0)
        self.assertGreater(link_button.geometry().left() - duplicate_button.geometry().right(), 0)
        self.assertGreater(delete_button.geometry().top() - edit_button.geometry().bottom(), 0)
        for button in (
            create_button,
            add_track_button,
            add_album_button,
            edit_button,
            duplicate_button,
            link_button,
            delete_button,
        ):
            self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())

        cluster_texts = [
            button.text()
            for button in work_panel.manage_actions_cluster.findChildren(app_module.QPushButton)
        ]
        self.assertIn("Add Track to Work", cluster_texts)
        self.assertIn("Add Album to Work", cluster_texts)

    def case_diagnostics_catalog_cleanup_uses_tabs_and_focus_requested_tab(self):
        dialog = app_module.DiagnosticsDialog(self.window)
        try:
            self.assertEqual(
                [
                    dialog.surface_tabs.tabText(index)
                    for index in range(dialog.surface_tabs.count())
                ],
                ["Health", "Catalog Cleanup"],
            )
            cleanup_panel = dialog.catalog_cleanup_panel
            self.assertIsNotNone(cleanup_panel)
            assert cleanup_panel is not None
            self.assertEqual(
                [cleanup_panel.tabs.tabText(index) for index in range(cleanup_panel.tabs.count())],
                ["Artists", "Albums"],
            )
            dialog.focus_cleanup_tab("albums")
            self.assertIs(dialog.surface_tabs.currentWidget(), cleanup_panel)
            self.assertIs(cleanup_panel.tabs.currentWidget(), cleanup_panel.albums_tab)
        finally:
            dialog.close()

    def case_catalog_cleanup_legacy_route_opens_diagnostics_cleanup_tab(self):
        captured_dialog = {}

        def _capture_exec(dialog):
            captured_dialog["dialog"] = dialog
            return app_module.QDialog.Accepted

        with mock.patch.object(app_module.DiagnosticsDialog, "exec", new=_capture_exec):
            self.window.open_catalog_managers_dialog(initial_tab="albums")

        dialog = captured_dialog.get("dialog")
        self.assertIsNotNone(dialog)
        assert dialog is not None
        cleanup_panel = dialog.catalog_cleanup_panel
        self.assertIsNotNone(cleanup_panel)
        assert cleanup_panel is not None
        self.assertIs(dialog.surface_tabs.currentWidget(), cleanup_panel)
        self.assertIs(cleanup_panel.tabs.currentWidget(), cleanup_panel.albums_tab)
        dialog.close()

    def case_diagnostics_catalog_cleanup_tabs_keep_bottom_actions_inside_themed_scroll_surfaces(
        self,
    ):
        dialog = app_module.DiagnosticsDialog(self.window)
        try:
            cleanup_panel = dialog.catalog_cleanup_panel
            self.assertIsNotNone(cleanup_panel)
            assert cleanup_panel is not None
            for pane, controls in (
                (
                    cleanup_panel.artists_tab,
                    (cleanup_panel.artists_tab.refresh_btn, cleanup_panel.artists_tab.delete_btn),
                ),
                (
                    cleanup_panel.albums_tab,
                    (cleanup_panel.albums_tab.refresh_btn, cleanup_panel.albums_tab.delete_btn),
                ),
            ):
                cleanup_panel.tabs.setCurrentWidget(pane)
                self.app.processEvents()
                self.assertIs(cleanup_panel.tabs.currentWidget(), pane)
                self.assertEqual(pane.property("role"), "workspaceCanvas")
                self.assertEqual(pane.scroll_area.property("role"), "workspaceCanvas")
                self.assertEqual(pane.scroll_area.viewport().property("role"), "workspaceCanvas")
                self.assertEqual(pane.scroll_content.property("role"), "workspaceCanvas")
                for control in controls:
                    self.assertTrue(self._is_within_scroll_content(pane.scroll_area, control))
        finally:
            dialog.close()

    def case_catalog_menu_hides_top_level_release_creation_and_removes_legacy_tools(self):
        catalog_action = next(
            action for action in self.window.menuBar().actions() if action.text() == "Catalog"
        )
        catalog_menu = catalog_action.menu()
        catalog_snapshot = self._menu_snapshot(catalog_menu)
        menu_texts = list(catalog_snapshot.get("texts") or [])
        self.assertNotIn("Create Release from Selection…", menu_texts)
        self.assertNotIn("Add Selected Tracks to Release…", menu_texts)
        self.assertEqual(
            menu_texts,
            [
                "Workspace",
                "Metadata & Standards",
                "Audio",
                "Quality & Repair",
            ],
        )
        catalog_quality_snapshot = self._menu_snapshot_at_path(catalog_snapshot, "Quality & Repair")
        self.assertEqual(
            list(catalog_quality_snapshot.get("texts") or []),
            ["Data Quality Dashboard…", "Track Import Repair Queue…"],
        )
        metadata_snapshot = self._menu_snapshot_at_path(catalog_snapshot, "Metadata & Standards")
        audio_snapshot = self._menu_snapshot_at_path(catalog_snapshot, "Audio")
        self.assertEqual(list(metadata_snapshot.get("texts") or []), ["GS1 Metadata…"])
        self.assertEqual(
            list(audio_snapshot.get("texts") or []),
            ["Import & Attach", "Delivery & Conversion", "Authenticity & Provenance"],
        )
        self.assertNotIn("create_release", self.window._action_ribbon_specs_by_id)
        self.assertNotIn("add_selected_to_release", self.window._action_ribbon_specs_by_id)

    def case_catalog_workspace_menu_groups_intent_actions_and_preserves_workspace_routes(self):
        catalog_action = next(
            action for action in self.window.menuBar().actions() if action.text() == "Catalog"
        )
        view_action = next(
            action for action in self.window.menuBar().actions() if action.text() == "View"
        )
        catalog_menu = catalog_action.menu()
        view_menu = view_action.menu()
        catalog_snapshot = self._menu_snapshot(catalog_menu)
        workspace_snapshot = self._menu_snapshot_at_path(catalog_snapshot, "Workspace")
        workspace_texts = list(workspace_snapshot.get("texts") or [])
        workspace_flat_texts = self._flatten_menu_snapshot(workspace_snapshot)
        view_texts = self._menu_action_texts(view_menu)

        self.assertEqual(workspace_texts, ["Create / Maintain", "Browse / Review"])
        create_texts = list(
            self._menu_snapshot_at_path(workspace_snapshot, "Create / Maintain").get("texts") or []
        )
        browse_texts = list(
            self._menu_snapshot_at_path(workspace_snapshot, "Browse / Review").get("texts") or []
        )
        quality_texts = list(
            self._menu_snapshot_at_path(catalog_snapshot, "Quality & Repair").get("texts") or []
        )

        self.assertEqual(
            create_texts,
            [
                "Add Track",
                "Work Manager…",
                "Party Manager…",
                "Contract Manager…",
                "Contract Template Workspace…",
                "Rights Matrix…",
            ],
        )
        self.assertEqual(
            browse_texts,
            [
                "Catalog",
                "Release Browser…",
                "Deliverables & Asset Versions…",
                "Derivative Ledger…",
                "Global Search and Relationships…",
            ],
        )
        self.assertNotIn("Show Catalog Table", workspace_flat_texts)
        self.assertNotIn("Show Add Track Panel", workspace_flat_texts)
        self.assertNotIn("Catalog Managers…", workspace_flat_texts)
        self.assertNotIn("catalog_managers", self.window._action_ribbon_specs_by_id)
        self.assertNotIn("Show Add Track Panel", view_texts)
        self.assertNotIn("Show Catalog Table", view_texts)
        self.assertIn("Track Import Repair Queue…", quality_texts)
        self.assertEqual(
            self.window._action_ribbon_specs_by_id["show_add_data"]["category"], "View"
        )
        self.assertEqual(
            self.window._action_ribbon_specs_by_id["show_catalog_table"]["category"], "Catalog"
        )
        self.assertFalse(self.window.workspace_add_track_action.isCheckable())
        self.assertFalse(self.window.workspace_catalog_action.isCheckable())
        self.assertFalse(self.window.workspace_global_search_action.isCheckable())

        self.assertFalse(self.window.add_data_dock.isVisible())
        self.window.workspace_add_track_action.trigger()
        wait_for(
            lambda: self.window.add_data_dock.isVisible(),
            timeout_ms=1000,
            interval_ms=10,
            app=self.app,
            description="add track dock to become visible",
        )
        wait_for(
            lambda: self.window.track_title_field.isVisible(),
            timeout_ms=1000,
            interval_ms=10,
            app=self.app,
            description="add track title field to become visible",
        )
        wait_for(
            lambda: self.window.settings.value("display/add_data_panel", False, bool),
            timeout_ms=1000,
            interval_ms=10,
            app=self.app,
            description="add track dock preference to persist",
        )

        self.assertTrue(self.window.catalog_table_dock.isVisible())
        self.window.catalog_table_action.trigger()
        self.app.processEvents()
        self.assertFalse(self.window.catalog_table_dock.isVisible())
        self.assertFalse(self.window.settings.value("display/catalog_table_panel", True, bool))
        self.window.workspace_catalog_action.trigger()
        wait_for(
            lambda: self.window.catalog_table_dock.isVisible(),
            timeout_ms=1000,
            interval_ms=10,
            app=self.app,
            description="catalog dock to become visible",
        )
        wait_for(
            lambda: self.window.table.hasFocus(),
            timeout_ms=1000,
            interval_ms=10,
            app=self.app,
            description="catalog table to receive focus",
        )
        self.assertTrue(self.window.catalog_table_dock.isVisible())
        self.assertTrue(self.window.settings.value("display/catalog_table_panel", False, bool))

    def case_profiles_toolbar_visibility_persists_in_view_preferences(self):
        view_action = next(
            action for action in self.window.menuBar().actions() if action.text() == "View"
        )
        view_menu = view_action.menu()
        view_texts = [action.text() for action in view_menu.actions() if action.text()]

        self.assertIn("Show Profiles Ribbon", view_texts)
        self.assertTrue(self.window.toolbar.isVisible())

        self.window.profiles_toolbar_visibility_action.trigger()
        self.app.processEvents()
        self.assertFalse(self.window.toolbar.isVisible())
        self.assertFalse(self.window.settings.value("display/profiles_toolbar_visible", True, bool))

        self._reopen_window(skip_background_prepare=True)
        self.assertFalse(self.window.toolbar.isVisible())

        self.window.profiles_toolbar_visibility_action.trigger()
        self.app.processEvents()
        self.assertTrue(self.window.toolbar.isVisible())
        self.assertTrue(self.window.settings.value("display/profiles_toolbar_visible", False, bool))

    def case_album_art_export_uses_album_title_and_bulk_export_stays_on_focused_column(self):
        track_one = self._create_track(
            index=151, title="Comet Signal", album_title="Aurora Heights"
        )
        track_two = self._create_track(index=152, title="Harbor Glow", album_title="Neon Tides")
        cover_one = self._create_media_file("aurora.png", b"\x89PNG\r\n\x1a\naurora")
        cover_two = self._create_media_file("neon.png", b"\x89PNG\r\n\x1a\nneon")
        audio_one = self._create_media_file("aurora.wav", b"RIFFaurora")
        audio_two = self._create_media_file("neon.wav", b"RIFFneon")

        self.window.track_service.set_media_path(
            track_one,
            "album_art",
            cover_one,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
            cursor=self.window.cursor,
        )
        self.window.track_service.set_media_path(
            track_two,
            "album_art",
            cover_two,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
            cursor=self.window.cursor,
        )
        self.window.track_service.set_media_path(
            track_one,
            "audio_file",
            audio_one,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
            cursor=self.window.cursor,
        )
        self.window.track_service.set_media_path(
            track_two,
            "audio_file",
            audio_two,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
            cursor=self.window.cursor,
        )
        self.window.refresh_table_preserve_view(focus_id=track_one)
        self.app.processEvents()

        with mock.patch.object(
            app_module.QFileDialog,
            "getSaveFileName",
            return_value=("", ""),
        ) as get_save_file_name:
            self.window._export_standard_media_for_track(track_one, "album_art")

        suggested_filename = get_save_file_name.call_args.args[2]
        self.assertTrue(suggested_filename.startswith("Aurora Heights"))
        self.assertFalse(suggested_filename.startswith("Comet Signal"))

        self._select_track_ids([track_one, track_two])
        album_art_col = self.window._column_index_by_header("Album Art")
        self.assertGreaterEqual(album_art_col, 0)
        self.assertEqual(
            self.window._focused_media_export_spec(album_art_col),
            {
                "kind": "standard",
                "column_label": "Album Art",
                "media_key": "album_art",
            },
        )
        track_title_col = self.window._column_index_by_header("Track Title")
        self.assertIsNone(self.window._focused_media_export_spec(track_title_col))

        output_dir = self.root / "album-art-export"
        output_dir.mkdir()
        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getExistingDirectory",
                return_value=str(output_dir),
            ),
            mock.patch.object(app_module.QMessageBox, "information"),
        ):
            self.window._export_focused_media_column(
                album_art_col,
                track_ids=[track_one, track_two],
            )

        exported_names = sorted(path.name for path in output_dir.iterdir() if path.is_file())
        self.assertEqual(
            exported_names,
            [
                "Aurora Heights.png",
                "Neon Tides.png",
            ],
        )
        self.assertFalse(any(name.endswith(".wav") for name in exported_names))

    def case_bulk_audio_attach_workflow_matches_files_updates_artists_and_records_history(self):
        track_one = self._create_track(index=401, title="Orbit Lines")
        track_two = self._create_track(index=402, title="Aurora Bloom")
        self.window.refresh_table_preserve_view(focus_id=track_one)
        self.app.processEvents()

        audio_one = self._create_media_file("Orbit Lines.wav", b"RIFForbit")
        audio_two = self._create_media_file("Aurora Bloom.wav", b"RIFFaurora")

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=self._run_bundle_task_inline,
            ),
            mock.patch.object(
                app_module.QFileDialog,
                "getOpenFileNames",
                return_value=([str(audio_one), str(audio_two)], ""),
            ),
            mock.patch.object(
                app_module.AudioTagService,
                "read_tags",
                return_value=SimpleNamespace(title=None, artist=None),
            ),
            mock.patch.object(
                app_module.BulkAudioAttachDialog,
                "exec",
                return_value=app_module.QDialog.Accepted,
            ),
            mock.patch.object(
                app_module.BulkAudioAttachDialog,
                "selected_artist_name",
                return_value="Synth Unit",
            ),
            mock.patch.object(
                app_module.BulkAudioAttachDialog,
                "selected_storage_mode",
                return_value=app_module.STORAGE_MODE_DATABASE,
            ),
            mock.patch.object(app_module.QMessageBox, "information") as info_mock,
        ):
            self.window.bulk_attach_audio_files(track_ids=[track_one, track_two])

        audio_one_bytes, _mime_one = self.window.track_service.fetch_media_bytes(
            track_one, "audio_file"
        )
        audio_two_bytes, _mime_two = self.window.track_service.fetch_media_bytes(
            track_two, "audio_file"
        )
        self.assertEqual(audio_one_bytes, b"RIFForbit")
        self.assertEqual(audio_two_bytes, b"RIFFaurora")

        snapshot_one = self.window.track_service.fetch_track_snapshot(track_one)
        snapshot_two = self.window.track_service.fetch_track_snapshot(track_two)
        self.assertEqual(snapshot_one.artist_name, "Synth Unit")
        self.assertEqual(snapshot_two.artist_name, "Synth Unit")

        visible_history = self.window.history_manager.list_entries(limit=5)
        self.assertEqual(visible_history[0].label, "Bulk Attach Audio Files (2 files)")
        info_mock.assert_called_once()
        self.assertIn("Attached audio to 2 track(s).", info_mock.call_args.args[2])
        self.assertIn("Updated the main artist on 2 matched track(s).", info_mock.call_args.args[2])

    def case_audio_attach_unique_match_requires_confirmation_before_write(self):
        track_id = self._create_track(index=411, title="Orbit Lines")
        self.window.refresh_table_preserve_view(focus_id=track_id)
        self.app.processEvents()

        audio_path = self._create_wav_file("Orbit Lines.wav")
        history_before = len(self.window.history_manager.list_entries(limit=50))
        captured_dialog: dict[str, object] = {}

        class _RejectingReviewDialog:
            def __init__(self, *args, **kwargs):
                del args
                captured_dialog.update(kwargs)

            def exec(self):
                return app_module.QDialog.Rejected

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=self._run_bundle_task_inline,
            ),
            mock.patch.object(app_module, "BulkAudioAttachDialog", _RejectingReviewDialog),
        ):
            self.window.bulk_attach_audio_files(
                track_ids=[track_id],
                file_paths=[str(audio_path)],
                title="Attach Audio",
            )

        snapshot = self.window.track_service.fetch_track_snapshot(track_id)
        self.assertIsNone(snapshot.audio_file_storage_mode)
        self.assertFalse(self.window.track_service.has_media(track_id, "audio_file"))
        self.assertEqual(len(self.window.history_manager.list_entries(limit=50)), history_before)
        self.assertEqual(captured_dialog["items"][0]["status"], "matched")
        self.assertEqual(captured_dialog["items"][0]["matched_track_id"], track_id)
        self.assertEqual(captured_dialog["media_label"], "audio file")

    def case_audio_attach_creates_primary_track_asset_after_confirmation(self):
        track_id = self._create_track(index=415, title="Asset Orbit")
        self.window.refresh_table_preserve_view(focus_id=track_id)
        self.app.processEvents()

        audio_path = self._create_wav_file("Asset Orbit.wav")

        class _AcceptingReviewDialog:
            def __init__(self, *args, **kwargs):
                del args, kwargs

            def exec(self):
                return app_module.QDialog.Accepted

            def create_track_requested(self):
                return False

            def selected_matches(self):
                return [
                    {
                        "source_path": str(audio_path),
                        "source_name": audio_path.name,
                        "track_id": track_id,
                        "detected_artist": "",
                        "detected_album": "",
                    }
                ]

            def selected_storage_mode(self):
                return app_module.STORAGE_MODE_DATABASE

            def selected_artist_name(self):
                return None

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=self._run_bundle_task_inline,
            ),
            mock.patch.object(app_module, "BulkAudioAttachDialog", _AcceptingReviewDialog),
            mock.patch.object(app_module.QMessageBox, "information"),
        ):
            self.window.bulk_attach_audio_files(
                track_ids=[track_id],
                file_paths=[str(audio_path)],
                title="Attach Audio",
            )

        assets = self.window.asset_service.list_assets(track_id=track_id)
        self.assertEqual(len(assets), 1)
        asset = assets[0]
        self.assertEqual(asset.asset_type, "main_master")
        self.assertTrue(asset.primary_flag)
        self.assertTrue(asset.approved_for_use)
        self.assertEqual(asset.storage_mode, app_module.STORAGE_MODE_DATABASE)

    def case_audio_attach_unmatched_and_ambiguous_files_open_manual_resolution_dialog(self):
        orbit_track = self._create_track(index=412, title="Orbit")
        echo_track = self._create_track(index=413, title="Orbit")
        self.window.refresh_table_preserve_view(focus_id=orbit_track)
        self.app.processEvents()

        unmatched_audio = self._create_wav_file("Unknown Passage.wav")
        ambiguous_audio = self._create_wav_file("Orbit.wav")
        captured_dialogs: list[dict[str, object]] = []

        class _CapturingReviewDialog:
            def __init__(self, *args, **kwargs):
                del args
                captured_dialogs.append(kwargs)

            def exec(self):
                return app_module.QDialog.Rejected

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=self._run_bundle_task_inline,
            ),
            mock.patch.object(app_module, "BulkAudioAttachDialog", _CapturingReviewDialog),
        ):
            self.window.bulk_attach_audio_files(
                track_ids=[orbit_track, echo_track],
                file_paths=[str(unmatched_audio)],
                title="Attach Audio",
            )
            self.window.bulk_attach_audio_files(
                track_ids=[orbit_track, echo_track],
                file_paths=[str(ambiguous_audio)],
                title="Attach Audio",
            )

        self.assertEqual(captured_dialogs[0]["items"][0]["status"], "unmatched")
        self.assertEqual(captured_dialogs[1]["items"][0]["status"], "ambiguous")
        self.assertCountEqual(
            captured_dialogs[1]["items"][0]["candidate_track_ids"],
            [orbit_track, echo_track],
        )

    def case_album_art_attach_requires_confirmation_and_honors_storage_mode(self):
        track_id = self._create_track(index=414, title="Night Bloom", album_title="Moon Atlas")
        self.window.refresh_table_preserve_view(focus_id=track_id)
        self.app.processEvents()

        cover_path = self._create_png_file("Moon Atlas.png")
        rejected_dialog: dict[str, object] = {}

        class _RejectingArtworkDialog:
            def __init__(self, *args, **kwargs):
                del args
                rejected_dialog.update(kwargs)

            def exec(self):
                return app_module.QDialog.Rejected

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=self._run_bundle_task_inline,
            ),
            mock.patch.object(app_module, "BulkAudioAttachDialog", _RejectingArtworkDialog),
        ):
            self.window.attach_album_art_file_to_catalog(
                track_ids=[track_id],
                file_paths=[str(cover_path)],
                title="Attach Artwork",
            )

        rejected_snapshot = self.window.track_service.fetch_track_snapshot(track_id)
        self.assertIsNone(rejected_snapshot.album_art_storage_mode)
        self.assertFalse(self.window.track_service.has_media(track_id, "album_art"))
        self.assertEqual(rejected_dialog["items"][0]["status"], "matched")
        self.assertEqual(rejected_dialog["media_label"], "album art file")

        class _AcceptingArtworkDialog:
            def __init__(self, *args, **kwargs):
                del args, kwargs

            def exec(self):
                return app_module.QDialog.Accepted

            def create_track_requested(self):
                return False

            def selected_matches(self):
                return [
                    {
                        "source_path": str(cover_path),
                        "source_name": cover_path.name,
                        "track_id": track_id,
                        "detected_artist": "",
                        "detected_album": "Moon Atlas",
                    }
                ]

            def selected_storage_mode(self):
                return app_module.STORAGE_MODE_DATABASE

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=self._run_bundle_task_inline,
            ),
            mock.patch.object(app_module, "BulkAudioAttachDialog", _AcceptingArtworkDialog),
            mock.patch.object(app_module.QMessageBox, "information"),
        ):
            self.window.attach_album_art_file_to_catalog(
                track_ids=[track_id],
                file_paths=[str(cover_path)],
                title="Attach Artwork",
            )

        accepted_snapshot = self.window.track_service.fetch_track_snapshot(track_id)
        self.assertEqual(accepted_snapshot.album_art_storage_mode, STORAGE_MODE_DATABASE)
        art_bytes, _mime_type = self.window.track_service.fetch_media_bytes(track_id, "album_art")
        self.assertEqual(art_bytes, cover_path.read_bytes())

    def case_media_attach_drop_targets_and_routing_reuse_the_same_workflows(self):
        audio_path = self._create_wav_file("Dropped Orbit.wav")
        image_path = self._create_png_file("Dropped Cover.png")
        image_path_two = self._create_png_file("Dropped Cover 2.png", color="#7A3AFE")
        text_path = self._create_media_file("notes.txt", b"not supported")

        self.assertTrue(self.window.acceptDrops())
        self.assertTrue(self.window.centralWidget().acceptDrops())
        self.assertTrue(self.window.table.acceptDrops())
        self.assertTrue(self.window.table.viewport().acceptDrops())

        with (
            mock.patch.object(self.window, "bulk_attach_audio_files") as bulk_attach,
            mock.patch.object(self.window, "attach_album_art_file_to_catalog") as attach_art,
            mock.patch.object(app_module.QMessageBox, "information") as info_mock,
        ):
            self.assertTrue(self.window._route_dropped_media_paths([str(audio_path)]))
            bulk_attach.assert_called_once_with(
                file_paths=[str(audio_path)],
                title="Attach Dropped Audio File",
            )
            attach_art.assert_not_called()
            info_mock.assert_not_called()

        with (
            mock.patch.object(self.window, "bulk_attach_audio_files") as bulk_attach,
            mock.patch.object(self.window, "attach_album_art_file_to_catalog") as attach_art,
            mock.patch.object(app_module.QMessageBox, "information") as info_mock,
        ):
            self.assertTrue(self.window._route_dropped_media_paths([str(image_path)]))
            attach_art.assert_called_once_with(
                file_paths=[str(image_path)],
                title="Attach Dropped Album Art",
            )
            bulk_attach.assert_not_called()
            info_mock.assert_not_called()

        with (
            mock.patch.object(self.window, "bulk_attach_audio_files") as bulk_attach,
            mock.patch.object(self.window, "attach_album_art_file_to_catalog") as attach_art,
            mock.patch.object(app_module.QMessageBox, "information") as info_mock,
        ):
            dropped_paths = [str(audio_path), str(text_path), str(image_path)]
            self.assertTrue(self.window._route_dropped_media_paths(dropped_paths))
            bulk_attach.assert_called_once_with(
                file_paths=dropped_paths,
                title="Attach Dropped Audio Files",
            )
            attach_art.assert_not_called()
            info_mock.assert_not_called()

        with (
            mock.patch.object(self.window, "bulk_attach_audio_files") as bulk_attach,
            mock.patch.object(self.window, "attach_album_art_file_to_catalog") as attach_art,
            mock.patch.object(app_module.QMessageBox, "information") as info_mock,
        ):
            self.assertTrue(
                self.window._route_dropped_media_paths([str(image_path), str(image_path_two)])
            )
            bulk_attach.assert_not_called()
            attach_art.assert_not_called()
            info_mock.assert_called_once()
            self.assertIn(
                "Only audio files are accepted in multi-file drops.", info_mock.call_args.args[2]
            )

        with (
            mock.patch.object(self.window, "bulk_attach_audio_files") as bulk_attach,
            mock.patch.object(self.window, "attach_album_art_file_to_catalog") as attach_art,
            mock.patch.object(app_module.QMessageBox, "information") as info_mock,
        ):
            self.assertTrue(self.window._route_dropped_media_paths([str(text_path)]))
            bulk_attach.assert_not_called()
            attach_art.assert_not_called()
            info_mock.assert_called_once()
            self.assertIn("not a supported audio or image file", info_mock.call_args.args[2])

    def case_history_budget_preflight_can_open_cleanup_dialog(self):
        self.window.settings_mutations.set_history_retention_mode("lean")
        self.window.settings_mutations.set_history_storage_budget_mb(1)

        class _CleanupPromptBox:
            Warning = object()
            AcceptRole = object()
            ActionRole = object()
            Cancel = object()
            last_text = ""

            def __init__(self, *_args, **_kwargs):
                self._cleanup_button = None
                self._clicked_button = None

            def setIcon(self, _icon):
                return None

            def setWindowTitle(self, _title):
                return None

            def setText(self, text):
                type(self).last_text = str(text)

            def addButton(self, label, _role=None):
                button = object()
                if label == "Open Cleanup":
                    self._cleanup_button = button
                return button

            def setDefaultButton(self, _button):
                return None

            def exec(self):
                self._clicked_button = self._cleanup_button

            def clickedButton(self):
                return self._clicked_button

        with (
            mock.patch.object(app_module, "QMessageBox", _CleanupPromptBox),
            mock.patch.object(self.window, "open_history_cleanup_dialog") as open_cleanup,
        ):
            allowed = self.window._prepare_history_storage_for_projected_growth(
                trigger_label="manual snapshot",
                additional_bytes=256 * 1024 * 1024,
                interactive=True,
            )

        self.assertFalse(allowed)
        open_cleanup.assert_called_once_with()
        self.assertIn("Projected usage", _CleanupPromptBox.last_text)
        self.assertIn(
            "Continue anyway, or review History Cleanup first?",
            _CleanupPromptBox.last_text,
        )

    def case_hidden_catalog_table_does_not_block_workspace_dock_access_or_peer_tabifying(self):
        self.assertTrue(self.window.catalog_table_dock.isVisible())
        self.window.catalog_table_action.trigger()
        self.app.processEvents()
        self.assertFalse(self.window.catalog_table_dock.isVisible())

        self.window.open_release_browser()
        self.app.processEvents()
        self.assertTrue(self.window.release_browser_dock.isVisible())
        self.assertFalse(self.window.release_browser_dock.isHidden())

        self.window.open_work_manager()
        self.app.processEvents()
        self.window.open_global_search()
        self.app.processEvents()

        peer_tabs = set(self.window.tabifiedDockWidgets(self.window.release_browser_dock))
        self.assertIn(self.window.work_manager_dock, peer_tabs)
        self.assertIn(self.window.global_search_dock, peer_tabs)
        self.assertTrue(self.window.work_manager_dock.isVisible())
        self.assertTrue(self.window.global_search_dock.isVisible())

    def case_add_track_and_catalog_table_docks_can_close_from_their_titlebar_controls(self):
        self.assertTrue(
            bool(self.window.add_data_dock.features() & app_module.QDockWidget.DockWidgetClosable)
        )
        self.assertTrue(
            bool(
                self.window.catalog_table_dock.features()
                & app_module.QDockWidget.DockWidgetClosable
            )
        )

        self.window.open_add_track_workspace()
        self.app.processEvents()
        self.assertTrue(self.window.add_data_dock.isVisible())
        self.assertTrue(self.window.add_data_action.isChecked())
        self.assertTrue(self.window.add_data_dock.close())
        self.app.processEvents()
        self.assertFalse(self.window.add_data_dock.isVisible())
        self.assertFalse(self.window.add_data_action.isChecked())

        self.assertTrue(self.window.catalog_table_dock.isVisible())
        self.assertTrue(self.window.catalog_table_action.isChecked())
        self.assertTrue(self.window.catalog_table_dock.close())
        self.app.processEvents()
        self.assertFalse(self.window.catalog_table_dock.isVisible())
        self.assertFalse(self.window.catalog_table_action.isChecked())

        self.window.open_add_track_workspace()
        self.window.open_catalog_workspace()
        self.app.processEvents()
        self.assertTrue(self.window.add_data_dock.isVisible())
        self.assertTrue(self.window.catalog_table_dock.isVisible())
        self.assertTrue(self.window.add_data_action.isChecked())
        self.assertTrue(self.window.catalog_table_action.isChecked())

    def case_workspace_layout_round_trip_restores_tabified_non_floating_docks(self):
        self.window.open_release_browser()
        self.window.open_work_manager()
        self.window.open_global_search()
        self._drain_events()

        self._reopen_window(skip_background_prepare=True)

        tabified = set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock))
        self.assertIn(self.window.release_browser_dock, tabified)
        self.assertIn(self.window.work_manager_dock, tabified)
        self.assertIn(self.window.global_search_dock, tabified)
        self.assertFalse(self.window.release_browser_dock.isFloating())
        self.assertFalse(self.window.work_manager_dock.isFloating())
        self.assertFalse(self.window.global_search_dock.isFloating())

    def case_layout_change_persists_latest_arrangement_not_default_arrangement(self):
        self.assertFalse(self.window.add_data_dock.isVisible())
        self.window.add_data_action.trigger()
        self.window.open_release_browser()
        self._drain_events()

        self.window.addDockWidget(
            app_module.Qt.LeftDockWidgetArea, self.window.release_browser_dock
        )
        self.window.tabifyDockWidget(self.window.add_data_dock, self.window.release_browser_dock)
        self.window.release_browser_dock.raise_()
        self._drain_events()

        self._reopen_window(skip_background_prepare=True)

        self.assertEqual(
            self.window.dockWidgetArea(self.window.release_browser_dock),
            app_module.Qt.LeftDockWidgetArea,
        )
        self.assertIn(
            self.window.release_browser_dock,
            set(self.window.tabifiedDockWidgets(self.window.add_data_dock)),
        )
        self.assertNotIn(
            self.window.release_browser_dock,
            set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock)),
        )

    def case_hidden_catalog_table_round_trip_preserves_peer_tab_group(self):
        self.window.catalog_table_action.trigger()
        self.window.open_release_browser()
        self.window.open_work_manager()
        self.window.open_global_search()
        self._drain_events()

        self._reopen_window()

        self.assertFalse(self.window.catalog_table_dock.isVisible())
        peer_tabs = set(self.window.tabifiedDockWidgets(self.window.release_browser_dock))
        self.assertIn(self.window.work_manager_dock, peer_tabs)
        self.assertIn(self.window.global_search_dock, peer_tabs)
        self.assertFalse(self.window.release_browser_dock.isFloating())

    def case_startup_restore_is_not_overwritten_by_post_init_visibility_sync(self):
        self.window.open_release_browser()
        self._drain_events()

        settings_path = self._close_window()
        settings = app_module.QSettings(str(settings_path), app_module.QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        settings.setValue("display/catalog_table_panel", False)
        settings.sync()
        settings.deleteLater() if hasattr(settings, "deleteLater") else None
        self._drain_events()

        self._open_window(skip_background_prepare=True)

        self.assertTrue(self.window.catalog_table_dock.isVisible())
        self.assertIn(
            self.window.release_browser_dock,
            set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock)),
        )

    def case_close_reopen_round_trip_preserves_core_panel_visibility_without_shutdown_corruption(
        self,
    ):
        self.window.add_data_action.trigger()
        self._drain_events()
        self.assertTrue(self.window.add_data_dock.isVisible())
        self.assertTrue(self.window.catalog_table_dock.isVisible())

        settings_path = self._close_window()
        settings = app_module.QSettings(str(settings_path), app_module.QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        self.assertTrue(settings.value("display/add_data_panel", False, bool))
        self.assertTrue(settings.value("display/catalog_table_panel", False, bool))
        settings.deleteLater() if hasattr(settings, "deleteLater") else None
        self._drain_events()

        self._open_window(skip_background_prepare=True)

        self.assertTrue(self.window.add_data_dock.isVisible())
        self.assertTrue(self.window.catalog_table_dock.isVisible())

    def case_main_window_geometry_round_trip_restores_non_default_outer_state(self):
        self.window.showNormal()
        self.window.resize(1111, 777)
        self._drain_events()

        self._reopen_window(skip_background_prepare=True)

        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.window.width(), 1111)
        self.assertEqual(self.window.height(), 777)

    def case_legacy_license_browser_is_not_exposed_in_workspace(self):
        self.assertFalse(hasattr(self.window, "license_browser_action"))
        self.assertFalse(hasattr(self.window, "legacy_license_migration_action"))
        self.assertFalse(hasattr(self.window, "license_browser_dock"))

    def case_party_contract_rights_and_asset_windows_open_as_tabified_docks(self):
        track_id = self._create_track(index=141, title="Docked Rights Track")
        party_id = self.window.party_service.create_party(
            PartyPayload(
                legal_name="North Star Music",
                display_name="North Star",
                party_type="label",
            )
        )
        contract_id = self.window.contract_service.create_contract(
            ContractPayload(
                title="North Star Agreement",
                contract_type="license",
                status="active",
                track_ids=[track_id],
            )
        )
        right_id = self.window.rights_service.create_right(
            RightPayload(
                title="North Star Master Rights",
                right_type="master",
                track_id=track_id,
                granted_to_party_id=party_id,
                source_contract_id=contract_id,
            )
        )
        asset_id = self.window.asset_service.create_asset(
            AssetVersionPayload(
                asset_type="main_master",
                filename="north-star-master.wav",
                track_id=track_id,
                approved_for_use=True,
                primary_flag=True,
                version_status="approved",
            )
        )
        ledger_service = DerivativeLedgerService(self.window.conn)
        batch_id = ledger_service.create_batch(
            batch_public_id="AEX-TEST-LEDGER-0001",
            track_count=1,
            output_format="mp3",
            workflow_kind="managed_audio_derivative",
            derivative_kind="lossy_derivative",
            authenticity_basis="catalog_lineage_only",
            profile_name=Path(self.window.current_db_path).name,
        )
        ledger_service.create_derivative(
            source_track_id=track_id,
            export_batch_id=batch_id,
            workflow_kind="managed_audio_derivative",
            derivative_kind="lossy_derivative",
            authenticity_basis="catalog_lineage_only",
            output_format="mp3",
            watermark_applied=False,
            metadata_embedded=True,
            final_sha256="f" * 64,
            output_filename="north-star-master--ledger.mp3",
            source_lineage_ref="track-audio:north-star-master.wav",
            source_sha256="a" * 64,
            source_storage_mode=STORAGE_MODE_DATABASE,
            authenticity_manifest_id="manifest-test-001",
            output_size_bytes=2_097_152,
            filename_hash_suffix="ledgerhash001",
            output_mime_type="audio/mpeg",
        )
        self.window.conn.commit()

        self.window.open_party_manager(party_id)
        self.app.processEvents()
        party_panel = self._assert_tabified_workspace_dock(
            self.window.party_manager_dock,
            dock_name="partyManagerDock",
            panel_name="partyManagerPanel",
        )
        self.assertEqual(party_panel._selected_party_ids(), [party_id])
        self.assertEqual(
            party_panel.manage_actions_cluster.objectName(), "partyManagerActionsCluster"
        )

        self.window.open_contract_manager(contract_id)
        self.app.processEvents()
        contract_panel = self._assert_tabified_workspace_dock(
            self.window.contract_manager_dock,
            dock_name="contractManagerDock",
            panel_name="contractBrowserPanel",
        )
        self.assertEqual(contract_panel._selected_contract_id(), contract_id)

        self.window.open_rights_matrix(right_id)
        self.app.processEvents()
        rights_panel = self._assert_tabified_workspace_dock(
            self.window.rights_matrix_dock,
            dock_name="rightsMatrixDock",
            panel_name="rightsBrowserPanel",
        )
        self.assertEqual(rights_panel._selected_right_id(), right_id)
        self.assertEqual(
            rights_panel.manage_actions_cluster.objectName(), "rightsMatrixActionsCluster"
        )

        self.window.open_asset_registry(asset_id)
        self.app.processEvents()
        asset_panel = self._assert_tabified_workspace_dock(
            self.window.asset_registry_dock,
            dock_name="assetRegistryDock",
            panel_name="assetBrowserPanel",
        )
        self.assertEqual(asset_panel._selected_asset_id(), asset_id)
        self.assertEqual(
            asset_panel.asset_actions_cluster.objectName(), "assetRegistryActionsCluster"
        )
        self.assertEqual(
            [
                asset_panel.workspace_tabs.tabText(index)
                for index in range(asset_panel.workspace_tabs.count())
            ],
            ["Asset Registry", "Derivative Ledger"],
        )
        self.assertIs(asset_panel.workspace_tabs.currentWidget(), asset_panel.asset_registry_tab)

        derivative_panel = self.window.open_derivative_ledger(batch_id)
        self.app.processEvents()
        self.assertIs(derivative_panel, asset_panel)
        self.assertIs(
            asset_panel.workspace_tabs.currentWidget(),
            asset_panel.derivative_ledger_tab,
        )
        self.assertEqual(
            asset_panel.derivative_ledger_tab.workspace_splitter.objectName(),
            "derivativeLedgerWorkspaceSplitter",
        )
        self.assertEqual(
            asset_panel.derivative_ledger_tab.workspace_splitter.orientation(),
            app_module.Qt.Horizontal,
        )
        self.assertEqual(
            [
                asset_panel.derivative_ledger_tab.batch_workspace_tabs.tabText(index)
                for index in range(asset_panel.derivative_ledger_tab.batch_workspace_tabs.count())
            ],
            ["Derivatives", "Details", "Lineage", "Admin"],
        )
        self.assertEqual(
            asset_panel.derivative_ledger_tab.derivative_actions_cluster.objectName(),
            "derivativeLedgerActionsCluster",
        )
        self.assertEqual(
            asset_panel.derivative_ledger_tab.admin_actions_cluster.objectName(),
            "derivativeLedgerAdminActionsCluster",
        )
        self.assertEqual(
            asset_panel.derivative_ledger_tab.format_filter_combo.objectName(),
            "derivativeLedgerFormatFilter",
        )
        self.assertEqual(
            asset_panel.derivative_ledger_tab.kind_filter_combo.objectName(),
            "derivativeLedgerKindFilter",
        )
        self.assertEqual(
            asset_panel.derivative_ledger_tab.status_filter_combo.objectName(),
            "derivativeLedgerStatusFilter",
        )
        self.assertEqual(
            asset_panel.derivative_ledger_tab.details_scroll_area.objectName(),
            "derivativeLedgerDetailsScrollArea",
        )
        self.assertEqual(
            asset_panel.derivative_ledger_tab.lineage_scroll_area.objectName(),
            "derivativeLedgerLineageScrollArea",
        )
        self.assertEqual(asset_panel.derivative_ledger_tab.batch_id_value.text(), batch_id)
        self.assertIn(
            batch_id,
            asset_panel.derivative_ledger_tab.selected_batch_heading.text(),
        )
        self.assertIn(
            "database",
            asset_panel.derivative_ledger_tab.admin_summary_label.text().lower(),
        )
        self.assertIn(
            "files on disk",
            asset_panel.derivative_ledger_tab.admin_summary_label.text().lower(),
        )
        self.assertGreaterEqual(asset_panel.derivative_ledger_tab.batch_table.rowCount(), 1)
        self.assertGreaterEqual(asset_panel.derivative_ledger_tab.derivative_table.rowCount(), 1)

        tabified = set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock))
        self.assertIn(self.window.party_manager_dock, tabified)
        self.assertIn(self.window.contract_manager_dock, tabified)
        self.assertIn(self.window.rights_matrix_dock, tabified)
        self.assertIn(self.window.asset_registry_dock, tabified)

    def case_party_export_selected_uses_live_selection_when_menu_payload_is_empty(self):
        party_id = self.window.party_service.create_party(
            PartyPayload(
                legal_name="Selected Export Party",
                display_name="Selected Export Party",
                party_type="person",
            )
        )
        self.window.conn.commit()

        self.window.open_party_manager(party_id)
        self.app.processEvents()
        party_panel = self._assert_tabified_workspace_dock(
            self.window.party_manager_dock,
            dock_name="partyManagerDock",
            panel_name="partyManagerPanel",
        )
        self.assertEqual(party_panel.selected_party_ids(), [party_id])

        export_path = self.root / "selected-party-export.csv"
        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getSaveFileName",
                return_value=(str(export_path), "CSV Files (*.csv)"),
            ) as get_save_file_name,
            mock.patch.object(self.window, "_submit_background_bundle_task") as submit_task,
            mock.patch.object(app_module.QMessageBox, "information") as information_mock,
        ):
            party_panel.export_selected_button.menu().actions()[0].trigger()
            self.app.processEvents()

        get_save_file_name.assert_called_once()
        submit_task.assert_called_once()
        information_mock.assert_not_called()
        self.assertEqual(submit_task.call_args.kwargs["title"], "Export Parties CSV")

    def case_file_menu_party_export_uses_dock_panel_selection_without_panel_attr(self):
        party_id = self.window.party_service.create_party(
            PartyPayload(
                legal_name="File Menu Export Party",
                display_name="File Menu Export Party",
                party_type="person",
            )
        )
        self.window.conn.commit()

        self.window.open_party_manager(party_id)
        self.app.processEvents()
        party_panel = self._assert_tabified_workspace_dock(
            self.window.party_manager_dock,
            dock_name="partyManagerDock",
            panel_name="partyManagerPanel",
        )
        self.assertEqual(party_panel.selected_party_ids(), [party_id])

        self.window.party_manager_panel = None
        self.window.party_manager_dialog = None

        export_path = self.root / "file-menu-selected-party-export.csv"
        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getSaveFileName",
                return_value=(str(export_path), "CSV Files (*.csv)"),
            ) as get_save_file_name,
            mock.patch.object(self.window, "_submit_background_bundle_task") as submit_task,
            mock.patch.object(app_module.QMessageBox, "information") as information_mock,
        ):
            self.window.export_selected_parties_csv_action.trigger()
            self.app.processEvents()

        get_save_file_name.assert_called_once()
        submit_task.assert_called_once()
        information_mock.assert_not_called()
        self.assertEqual(submit_task.call_args.kwargs["title"], "Export Parties CSV")

    def case_repertoire_export_uses_background_task_instead_of_direct_sync_write(self):
        export_path = self.root / "repertoire-export.json"

        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getSaveFileName",
                return_value=(str(export_path), "JSON Files (*.json)"),
            ) as get_save_file_name,
            mock.patch.object(self.window, "_submit_background_bundle_task") as submit_task,
            mock.patch.object(
                self.window.repertoire_exchange_service, "export_json"
            ) as direct_export,
        ):
            self.window.export_repertoire_exchange("json")
            self.app.processEvents()

        get_save_file_name.assert_called_once()
        submit_task.assert_called_once()
        direct_export.assert_not_called()
        self.assertEqual(
            submit_task.call_args.kwargs["title"],
            "Export Contracts and Rights JSON",
        )

    def case_master_transfer_export_uses_background_task(self):
        export_path = self.root / "master-transfer.zip"

        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getSaveFileName",
                return_value=(str(export_path), "ZIP Files (*.zip)"),
            ) as get_save_file_name,
            mock.patch.object(self.window, "_submit_background_bundle_task") as submit_task,
        ):
            self.window.export_master_transfer_package()
            self.app.processEvents()

        get_save_file_name.assert_called_once()
        submit_task.assert_called_once()
        self.assertEqual(
            submit_task.call_args.kwargs["title"],
            "Export Master Catalog Transfer",
        )

    def case_repertoire_export_resolves_directory_selection_to_file_target(self):
        export_dir = self.root / "repertoire-export-target"
        export_dir.mkdir(parents=True, exist_ok=True)
        captured_targets: list[Path] = []
        original_run_file_history_action = app_module.run_file_history_action

        def _capture_file_history(*args, **kwargs):
            captured_targets.append(Path(kwargs["target_path"]))
            return original_run_file_history_action(*args, **kwargs)

        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getSaveFileName",
                return_value=(str(export_dir), "JSON Files (*.json)"),
            ),
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=self._run_bundle_task_inline,
            ),
            mock.patch.object(
                app_module,
                "run_file_history_action",
                side_effect=_capture_file_history,
            ),
        ):
            self.window.export_repertoire_exchange("json")
            self.app.processEvents()

        self.assertEqual(len(captured_targets), 1)
        self.assertEqual(captured_targets[0].parent, export_dir)
        self.assertEqual(captured_targets[0].suffix, ".json")
        self.assertTrue(captured_targets[0].name.startswith("contracts_and_rights_json_"))
        self.assertTrue(captured_targets[0].exists())

    def case_repertoire_csv_bundle_uses_snapshot_history_for_directory_targets(self):
        export_root = self.root / "repertoire-bundles"
        export_root.mkdir(parents=True, exist_ok=True)
        recorded_paths: list[str] = []
        original_run_snapshot_history_action = app_module.run_snapshot_history_action

        def _capture_snapshot_history(*args, **kwargs):
            recorded_paths.append(str((kwargs.get("payload") or {}).get("path") or ""))
            return original_run_snapshot_history_action(*args, **kwargs)

        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getExistingDirectory",
                return_value=str(export_root),
            ),
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=self._run_bundle_task_inline,
            ),
            mock.patch.object(
                app_module,
                "run_file_history_action",
                side_effect=AssertionError("CSV bundle export should not use file history"),
            ),
            mock.patch.object(
                app_module,
                "run_snapshot_history_action",
                side_effect=_capture_snapshot_history,
            ),
        ):
            self.window.export_repertoire_exchange("csv")
            self.app.processEvents()

        created_dirs = [path for path in export_root.iterdir() if path.is_dir()]
        self.assertEqual(len(created_dirs), 1)
        self.assertTrue(created_dirs[0].name.startswith("contracts_and_rights_csv_bundle_"))
        self.assertEqual(recorded_paths, [str(created_dirs[0])])

    def case_party_import_write_mode_runs_dry_run_review_before_apply(self):
        json_path = self.root / "party-review.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "rows": [
                        {
                            "legal_name": "Preview Party B.V.",
                            "display_name": "Preview Party",
                            "email": "preview@party.test",
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        submitted_titles: list[str] = []
        captured_modes: list[tuple[str, str | None]] = []
        original_import_json = app_module.PartyExchangeService.import_json

        def _run_bundle_task_and_capture(window, **kwargs):
            submitted_titles.append(str(kwargs.get("title") or ""))
            return self._run_bundle_task_inline(window, **kwargs)

        def _capture_import(service, *args, **kwargs):
            options = kwargs.get("options")
            captured_modes.append(
                (
                    str(getattr(options, "mode", "")),
                    getattr(options, "preview_apply_mode", None),
                )
            )
            return original_import_json(service, *args, **kwargs)

        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getOpenFileName",
                return_value=(str(json_path), "JSON Files (*.json)"),
            ),
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=_run_bundle_task_and_capture,
            ),
            mock.patch.object(
                app_module.PartyImportDialog,
                "exec",
                return_value=app_module.QDialog.Accepted,
            ),
            mock.patch.object(
                app_module.PartyImportDialog,
                "mapping",
                return_value={
                    "legal_name": "legal_name",
                    "display_name": "display_name",
                    "email": "email",
                },
            ),
            mock.patch.object(
                app_module.PartyImportDialog,
                "import_options",
                return_value=app_module.PartyImportOptions(mode="upsert"),
            ),
            mock.patch.object(
                app_module.PartyImportDialog,
                "resolved_csv_delimiter",
                return_value=None,
            ),
            mock.patch.object(
                app_module.ImportReviewDialog,
                "exec",
                return_value=app_module.QDialog.Rejected,
            ),
            mock.patch.object(
                app_module.PartyExchangeService,
                "import_json",
                autospec=True,
                side_effect=_capture_import,
            ),
        ):
            self.window.import_party_exchange_file("json")
            self.app.processEvents()

        self.assertEqual(submitted_titles, ["Inspect Parties JSON", "Review Parties JSON"])
        self.assertEqual(captured_modes, [("dry_run", "upsert")])
        self.assertEqual(self.window.party_service.list_parties(), [])

    def case_catalog_import_write_mode_runs_dry_run_review_before_apply(self):
        json_path = self.root / "catalog-review.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "rows": [
                        {
                            "track_title": "Preview Orbit",
                            "artist_name": "Moonwake",
                            "isrc": "NL-TST-26-90101",
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        submitted_titles: list[str] = []
        captured_modes: list[tuple[str, str | None]] = []
        original_import_json = app_module.ExchangeService.import_json

        def _run_bundle_task_and_capture(window, **kwargs):
            submitted_titles.append(str(kwargs.get("title") or ""))
            return self._run_bundle_task_inline(window, **kwargs)

        def _capture_import(service, *args, **kwargs):
            options = kwargs.get("options")
            captured_modes.append(
                (
                    str(getattr(options, "mode", "")),
                    getattr(options, "preview_apply_mode", None),
                )
            )
            return original_import_json(service, *args, **kwargs)

        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getOpenFileName",
                return_value=(str(json_path), "JSON Files (*.json)"),
            ),
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=_run_bundle_task_and_capture,
            ),
            mock.patch.object(
                app_module.ExchangeImportDialog,
                "exec",
                return_value=app_module.QDialog.Accepted,
            ),
            mock.patch.object(
                app_module.ExchangeImportDialog,
                "mapping",
                return_value={
                    "track_title": "track_title",
                    "artist_name": "artist_name",
                    "isrc": "isrc",
                },
            ),
            mock.patch.object(
                app_module.ExchangeImportDialog,
                "import_options",
                return_value=app_module.ExchangeImportOptions(mode="create"),
            ),
            mock.patch.object(
                app_module.ExchangeImportDialog,
                "resolved_csv_delimiter",
                return_value=None,
            ),
            mock.patch.object(
                app_module.ImportReviewDialog,
                "exec",
                return_value=app_module.QDialog.Rejected,
            ),
            mock.patch.object(
                app_module.ExchangeService,
                "import_json",
                autospec=True,
                side_effect=_capture_import,
            ),
        ):
            self.window.import_exchange_file("json")
            self.app.processEvents()

        self.assertEqual(submitted_titles, ["Inspect JSON", "Review JSON"])
        self.assertEqual(captured_modes, [("dry_run", "create")])
        self.assertEqual(self.window.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 0)

    def case_repertoire_import_requires_review_before_apply(self):
        json_path = self.root / "repertoire-review.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "parties": [{"legal_name": "Preview Label"}],
                    "works": [],
                    "contracts": [],
                    "rights": [],
                    "assets": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        submitted_titles: list[str] = []

        def _run_bundle_task_and_capture(window, **kwargs):
            submitted_titles.append(str(kwargs.get("title") or ""))
            return self._run_bundle_task_inline(window, **kwargs)

        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getOpenFileName",
                return_value=(str(json_path), "JSON Files (*.json)"),
            ),
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=_run_bundle_task_and_capture,
            ),
            mock.patch.object(
                app_module.ImportReviewDialog,
                "exec",
                return_value=app_module.QDialog.Rejected,
            ),
            mock.patch.object(
                app_module.RepertoireExchangeService,
                "import_json",
                autospec=True,
                side_effect=AssertionError(
                    "repertoire apply should not run before review acceptance"
                ),
            ),
        ):
            self.window.import_repertoire_exchange("json")
            self.app.processEvents()

        self.assertEqual(submitted_titles, ["Inspect Contracts and Rights JSON"])

    def case_master_transfer_import_requires_review_before_apply(self):
        package_path = self.root / "master-transfer.zip"
        package_path.write_bytes(b"placeholder")

        submitted_titles: list[str] = []

        def _capture_submission(_window, **kwargs):
            submitted_titles.append(str(kwargs.get("title") or ""))
            if str(kwargs.get("title") or "") == "Inspect Master Catalog Transfer":
                kwargs["on_success_after_cleanup"](
                    SimpleNamespace(
                        summary_lines=["Package format version: 1"],
                        warnings=[],
                        preview_rows=[],
                        catalog_dry_run=SimpleNamespace(
                            would_create_tracks=1,
                            would_update_tracks=0,
                            failed=0,
                        ),
                        repertoire_inspection=SimpleNamespace(
                            existing_parties=0,
                            new_parties=1,
                        ),
                    )
                )
                return None
            raise AssertionError("master transfer apply should not run before review acceptance")

        with (
            mock.patch.object(
                app_module.QFileDialog,
                "getOpenFileName",
                return_value=(str(package_path), "ZIP Files (*.zip)"),
            ),
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=_capture_submission,
            ),
            mock.patch.object(
                app_module.ImportReviewDialog,
                "exec",
                return_value=app_module.QDialog.Rejected,
            ),
        ):
            self.window.import_master_transfer_package()
            self.app.processEvents()

        self.assertEqual(submitted_titles, ["Inspect Master Catalog Transfer"])

    def case_contract_template_workspace_opens_as_tabified_dock(self):
        self.window.open_contract_template_workspace()
        self.app.processEvents()

        panel = self._assert_tabified_workspace_dock(
            self.window.contract_template_workspace_dock,
            dock_name="contractTemplateWorkspaceDock",
            panel_name="contractTemplateWorkspacePanel",
        )
        self.assertEqual(
            self.window.contract_template_workspace_action.text(),
            "Contract Template Workspace…",
        )
        self.assertEqual(panel.workspace_tabs.tabText(0), "Symbol Generator")
        self.assertGreater(panel.table.rowCount(), 0)
        self.assertTrue(panel.selected_symbol_edit.text().startswith("{{db."))
        self.assertEqual(
            panel.symbol_actions_cluster.objectName(),
            "contractTemplateSymbolActionsCluster",
        )
        tabified = set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock))
        self.assertIn(self.window.contract_template_workspace_dock, tabified)

    def case_contract_template_workspace_opens_fill_tab_as_tabified_dock(self):
        self._create_track(index=151, title="Fill Draft Track")
        template = self.window.contract_template_service.create_template(
            ContractTemplatePayload(
                name="Shell Fill Template",
                description="App shell draft workflow coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "shell-fill-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Track ", "{{db.track.track_title}}"),
                    ("Date ", "{{manual.license_date}}"),
                )
            )
        )
        self.window.contract_template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        )

        self.window.open_contract_template_workspace(initial_tab="fill")
        self.app.processEvents()

        panel = self._assert_tabified_workspace_dock(
            self.window.contract_template_workspace_dock,
            dock_name="contractTemplateWorkspaceDock",
            panel_name="contractTemplateWorkspacePanel",
        )
        tab_texts = [
            panel.workspace_tabs.tabText(index).lower()
            for index in range(panel.workspace_tabs.count())
        ]
        if not any("fill" in text for text in tab_texts):
            self.skipTest("Fill tab not yet exposed by ContractTemplateWorkspacePanel")
        fill_index = next(index for index, text in enumerate(tab_texts) if "fill" in text)
        self.assertGreaterEqual(panel.workspace_tabs.count(), 2)
        self.assertEqual(panel.workspace_tabs.currentIndex(), fill_index)
        self.assertIn("fill", panel.workspace_tabs.tabText(fill_index).lower())
        self.assertGreaterEqual(panel.fill_template_combo.count(), 2)
        self.assertGreaterEqual(panel.fill_revision_combo.count(), 2)
        self.assertGreaterEqual(panel.fill_draft_storage_combo.count(), 2)
        self.assertEqual(
            panel.fill_draft_actions_cluster.objectName(),
            "contractTemplateDraftActionsCluster",
        )
        self.assertIn(
            self.window.contract_template_workspace_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )

    def case_contract_template_workspace_fill_tab_can_save_and_resume_drafts(self):
        self._create_track(index=152, title="Fill Resume Track")
        template = self.window.contract_template_service.create_template(
            ContractTemplatePayload(
                name="Shell Resume Template",
                description="App shell save and resume coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "shell-resume-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Track ", "{{db.track.track_title}}"),
                    ("Date ", "{{manual.license_date}}"),
                )
            )
        )
        revision = self.window.contract_template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision

        self.window.open_contract_template_workspace(initial_tab="fill")
        self.app.processEvents()
        panel = self._assert_tabified_workspace_dock(
            self.window.contract_template_workspace_dock,
            dock_name="contractTemplateWorkspaceDock",
            panel_name="contractTemplateWorkspacePanel",
        )

        selector = panel.selector_widgets["{{db.track.track_title}}"]
        date_widget = panel.manual_widgets["{{manual.license_date}}"]
        selector.setCurrentIndex(1)
        selected_track_value = selector.currentData()
        draft_date = QDate.currentDate().addDays(1)
        date_widget.setDate(draft_date)
        panel.fill_draft_name_edit.setText("Shell Resume Draft")
        panel.fill_draft_storage_combo.setCurrentIndex(1)
        self.app.processEvents()

        panel.save_new_draft()
        self.app.processEvents()

        drafts = self.window.contract_template_service.list_drafts(revision_id=revision.revision_id)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(panel.fill_draft_combo.count(), 2)
        self.assertEqual(panel.fill_draft_combo.currentData(), drafts[0].draft_id)
        self.assertEqual(panel.fill_draft_name_edit.text(), "Shell Resume Draft")
        self.assertEqual(panel.fill_draft_storage_combo.currentData(), STORAGE_MODE_MANAGED_FILE)

        panel.reset_fill_form()
        self.app.processEvents()
        self.assertEqual(
            panel.current_fill_state(),
            {
                "revision_id": revision.revision_id,
                "db_selections": {},
                "manual_values": {},
                "type_overrides": {},
            },
        )

        for index in range(panel.fill_draft_combo.count()):
            if panel.fill_draft_combo.itemData(index) == drafts[0].draft_id:
                panel.fill_draft_combo.setCurrentIndex(index)
                break
        self.app.processEvents()

        panel.load_selected_draft()
        self.app.processEvents()
        self.assertEqual(
            panel.current_fill_state(),
            {
                "revision_id": revision.revision_id,
                "db_selections": {"{{db.track.track_title}}": selected_track_value},
                "manual_values": {"{{manual.license_date}}": draft_date.toString("yyyy-MM-dd")},
                "type_overrides": {},
            },
        )
        self.assertEqual(panel.fill_draft_name_edit.text(), "Shell Resume Draft")
        self.assertEqual(panel.fill_draft_storage_combo.currentData(), STORAGE_MODE_MANAGED_FILE)
        self.assertIn(
            self.window.contract_template_workspace_dock,
            self.window.tabifiedDockWidgets(self.window.catalog_table_dock),
        )

    def case_contract_template_workspace_fill_tab_can_export_pdf(self):
        self._create_track(index=153, title="Fill Export Track")
        self.window.contract_template_export_service.html_adapter = FakeDocxHtmlAdapter()
        self.window.contract_template_export_service.pages_adapter = FakePagesAdapter()
        template = self.window.contract_template_service.create_template(
            ContractTemplatePayload(
                name="Shell Export Template",
                description="App shell export coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "shell-export-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Track ", "{{db.track.track_title}}"),
                    ("Date ", "{{manual.license_date}}"),
                )
            )
        )
        revision = self.window.contract_template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision

        self.window.open_contract_template_workspace(initial_tab="fill")
        self.app.processEvents()
        panel = self._assert_tabified_workspace_dock(
            self.window.contract_template_workspace_dock,
            dock_name="contractTemplateWorkspaceDock",
            panel_name="contractTemplateWorkspacePanel",
        )

        selector = panel.selector_widgets["{{db.track.track_title}}"]
        date_widget = panel.manual_widgets["{{manual.license_date}}"]
        selector.setCurrentIndex(1)
        date_widget.setDate(QDate(2026, 3, 30))
        panel.fill_draft_name_edit.setText("Shell Export Draft")
        self.app.processEvents()

        panel.export_current_pdf()
        self.app.processEvents()

        drafts = self.window.contract_template_service.list_drafts(revision_id=revision.revision_id)
        self.assertEqual(len(drafts), 1)
        updated = self.window.contract_template_service.fetch_draft(drafts[0].draft_id)
        self.assertIsNotNone(updated.last_resolved_snapshot_id)
        artifacts = self.window.contract_template_service.list_output_artifacts(
            snapshot_id=updated.last_resolved_snapshot_id
        )
        self.assertEqual(
            sorted(artifact.artifact_type for artifact in artifacts),
            ["pdf", "resolved_docx"],
        )
        self.assertIn("Exported PDF", panel.fill_export_status_label.text())
        self.assertTrue(Path(artifacts[0].output_path).exists())

    def case_asset_workspace_rejoins_tabbed_dock_strip_when_reopened(self):
        track_id = self._create_track(index=142, title="Docked Deliverables Track")
        asset_id = self.window.asset_service.create_asset(
            AssetVersionPayload(
                asset_type="main_master",
                filename="deliverables-master.wav",
                track_id=track_id,
                approved_for_use=True,
                primary_flag=True,
                version_status="approved",
            )
        )

        self.window.open_release_browser()
        self.window.open_asset_registry(asset_id)
        self.app.processEvents()

        asset_panel = self.window.asset_registry_dock.widget()
        self.assertIsNotNone(asset_panel)
        self.assertIn(
            self.window.asset_registry_dock,
            set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock)),
        )

        self.window.removeDockWidget(self.window.asset_registry_dock)
        self.window.addDockWidget(
            app_module.Qt.RightDockWidgetArea, self.window.asset_registry_dock
        )
        self.app.processEvents()
        self.assertNotIn(
            self.window.asset_registry_dock,
            set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock)),
        )

        self.window.asset_registry_dock.hide()
        self.app.processEvents()

        reopened_panel = self.window.open_asset_registry(asset_id)
        self.app.processEvents()

        self.assertIs(reopened_panel, asset_panel)
        self.assertIn(
            self.window.asset_registry_dock,
            set(self.window.tabifiedDockWidgets(self.window.catalog_table_dock)),
        )
        self.assertEqual(reopened_panel._selected_asset_id(), asset_id)

    def case_add_data_panel_uses_tabbed_sections(self):
        tabs = self.window.findChild(app_module.QTabWidget, "addDataTabs")
        self.assertIsNotNone(tabs)
        self.assertEqual(
            [tabs.tabText(index) for index in range(tabs.count())],
            [
                "Track",
                "Release",
                "Codes",
                "Media",
            ],
        )
        self.assertEqual(self.window.left_widget_container.property("role"), "workspaceCanvas")
        self.assertEqual(self.window.table_panel_widget.property("role"), "workspaceCanvas")
        self.assertEqual(self.window.centralWidget().property("role"), "workspaceCanvas")
        lossy_audio = self._create_media_file("add-warning.mp3", b"ID3add-warning")
        self.window.audio_file_field.setText(str(lossy_audio))
        self.app.processEvents()
        self.assertFalse(self.window.audio_file_warning_label.isHidden())
        self.assertIn("MP3", self.window.audio_file_warning_label.text())

    def case_track_editor_uses_tabbed_sections(self):
        track_id = self._create_track(
            index=9001, title="Tabbed Editor", album_title="Editor Layout"
        )

        dialog = app_module.EditDialog(track_id, self.window)
        try:
            tabs = dialog.findChild(app_module.QTabWidget, "editDialogTabs")
            self.assertIsNotNone(tabs)
            self.assertEqual(
                [tabs.tabText(index) for index in range(tabs.count())],
                [
                    "Track",
                    "Release",
                    "Codes",
                    "Media",
                ],
            )
            self.assertEqual(tabs.currentWidget().property("role"), "workspaceCanvas")
            scroll_areas = dialog.findChildren(QScrollArea)
            self.assertTrue(scroll_areas)
            self.assertTrue(
                any(area.property("role") == "workspaceCanvas" for area in scroll_areas)
            )
            self.assertIsInstance(dialog.upc, app_module.QComboBox)
            self.assertTrue(dialog.upc.isEditable())
            lossy_audio = self._create_media_file("editor-warning.mp3", b"ID3editor-warning")
            dialog.audio_file.setText(str(lossy_audio))
            self.app.processEvents()
            self.assertFalse(dialog.audio_file_warning_label.isHidden())
            self.assertIn("MP3", dialog.audio_file_warning_label.text())
        finally:
            dialog.close()

    def case_track_editor_disables_album_art_upload_for_shared_art_slave(self):
        lead_track = self._create_track(
            index=189,
            title="Lead Shared Track",
            album_title="Shared Editor Album",
        )
        peer_track = self._create_track(
            index=190,
            title="Peer Shared Track",
            album_title="Shared Editor Album",
        )
        cover_path = self._create_media_file("shared-editor-cover.png", b"\x89PNGshared-editor")
        self.window.track_service.set_media_path(
            lead_track,
            "album_art",
            cover_path,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
        )

        dialog = app_module.EditDialog(peer_track, self.window)
        try:
            self.assertEqual(
                dialog.album_art.text(),
                "shared-editor-cover.png (stored in database)",
            )
            self.assertFalse(dialog.album_art_browse_button.isEnabled())
            self.assertTrue(dialog.album_art_clear_button.isEnabled())
            self.assertFalse(dialog.album_art_hint_label.isHidden())
            self.assertFalse(dialog.album_art_open_master_button.isHidden())
            self.assertEqual(dialog.album_art_open_master_button.text(), "Open Master Record")
            self.assertIn(f"Track #{lead_track}", dialog.album_art_hint_label.text())
            self.assertIn("Lead Shared Track", dialog.album_art_hint_label.text())
        finally:
            dialog.close()

    def case_track_editor_keeps_album_art_upload_enabled_for_shared_art_master(self):
        lead_track = self._create_track(
            index=191,
            title="Lead Shared Track",
            album_title="Shared Editor Album",
        )
        self._create_track(
            index=192,
            title="Peer Shared Track",
            album_title="Shared Editor Album",
        )
        cover_path = self._create_media_file("shared-editor-master.png", b"\x89PNGmaster-editor")
        self.window.track_service.set_media_path(
            lead_track,
            "album_art",
            cover_path,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
        )

        dialog = app_module.EditDialog(lead_track, self.window)
        try:
            self.assertTrue(dialog.album_art_browse_button.isEnabled())
            self.assertTrue(dialog.album_art_clear_button.isEnabled())
            self.assertTrue(dialog.album_art_hint_label.isHidden())
            self.assertEqual(dialog.album_art_hint_label.text(), "")
            self.assertTrue(dialog.album_art_open_master_button.isHidden())
        finally:
            dialog.close()

    def case_bulk_track_editor_disables_album_art_upload_when_selection_includes_slave(self):
        lead_track = self._create_track(
            index=193,
            title="Lead Shared Track",
            album_title="Shared Bulk Album",
        )
        peer_track = self._create_track(
            index=194,
            title="Peer Shared Track",
            album_title="Shared Bulk Album",
        )
        cover_path = self._create_media_file("shared-bulk-cover.png", b"\x89PNGshared-bulk")
        self.window.track_service.set_media_path(
            lead_track,
            "album_art",
            cover_path,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
        )

        dialog = app_module.EditDialog(
            lead_track, self.window, batch_track_ids=[lead_track, peer_track]
        )
        try:
            self.assertFalse(dialog.album_art_browse_button.isEnabled())
            self.assertTrue(dialog.album_art_clear_button.isEnabled())
            self.assertFalse(dialog.album_art_hint_label.isHidden())
            self.assertFalse(dialog.album_art_open_master_button.isHidden())
            self.assertEqual(dialog.album_art_open_master_button.text(), "Open Master Record")
            self.assertIn(f"Track #{lead_track}", dialog.album_art_hint_label.text())
            self.assertIn("Lead Shared Track", dialog.album_art_hint_label.text())
        finally:
            dialog.close()

    def case_track_editor_open_master_action_opens_owner_editor(self):
        lead_track = self._create_track(
            index=197,
            title="Lead Shared Track",
            album_title="Shared Action Album",
        )
        peer_track = self._create_track(
            index=198,
            title="Peer Shared Track",
            album_title="Shared Action Album",
        )
        cover_path = self._create_media_file("shared-action-cover.png", b"\x89PNGshared-action")
        self.window.track_service.set_media_path(
            lead_track,
            "album_art",
            cover_path,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
        )

        dialog = app_module.EditDialog(peer_track, self.window)
        try:
            with (
                mock.patch.object(self.window, "refresh_table_preserve_view") as refresh_table,
                mock.patch.object(self.window, "open_track_editor") as open_track_editor,
            ):
                dialog.album_art_open_master_button.click()
                self.app.processEvents()

            refresh_table.assert_called_once_with(focus_id=lead_track)
            open_track_editor.assert_called_once_with(
                lead_track,
                batch_track_ids=[lead_track],
            )
        finally:
            dialog.close()

    def case_track_editor_save_succeeds_without_album_propagation(self):
        track_id = self._create_track(
            index=188, title="Single Edit Source", album_title="Solo Album"
        )
        lossy_audio = self._create_media_file("single-edit-lossy.mp3", b"ID3single-edit-lossy")

        dialog = app_module.EditDialog(track_id, self.window)
        try:
            dialog.track_title.setText("Single Edit Updated")
            dialog.audio_file.setText(str(lossy_audio))
            self.app.processEvents()
            self.assertFalse(dialog.audio_file_warning_label.isHidden())
            with (
                mock.patch.object(
                    app_module,
                    "_prompt_storage_mode_choice",
                    return_value=app_module.STORAGE_MODE_DATABASE,
                ),
                mock.patch.object(
                    app_module.QMessageBox,
                    "question",
                    return_value=app_module.QMessageBox.Yes,
                ) as confirm_mock,
            ):
                dialog.save_changes()
            wait_for(
                lambda: (
                    not self.window.background_tasks.has_running_tasks()
                    and self.window.track_service.fetch_track_snapshot(track_id).track_title
                    == "Single Edit Updated"
                ),
                timeout_ms=5000,
                interval_ms=25,
                app=self.app,
                description="single-track edit save to finish",
            )
            snapshot = self.window.track_service.fetch_track_snapshot(track_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.track_title, "Single Edit Updated")
            self.assertTrue(self.window.track_media_meta(track_id, "audio_file")["is_lossy"])
            confirm_mock.assert_called_once()
            self.assertIn("lossy audio", confirm_mock.call_args.args[2].lower())
        finally:
            dialog.close()

    def case_export_catalog_audio_copies_exports_managed_and_database_wav_sources(self):
        managed_track = self._create_track(
            index=195,
            title="Managed Export Track",
            album_title="Single",
        )
        database_track = self._create_track(
            index=196,
            title="Database Export Track",
            album_title="Single",
        )
        managed_audio = self._create_wav_file("managed-export.wav")
        database_audio = self._create_wav_file("database-export.wav")
        managed_cover = self._create_media_file("managed-export-cover.png", b"\x89PNGmanaged-cover")
        database_cover = self._create_media_file(
            "database-export-cover.png",
            b"\x89PNGdatabase-cover",
        )
        self.window.track_service.set_media_path(managed_track, "audio_file", managed_audio)
        self.window.track_service.set_media_path(
            database_track,
            "audio_file",
            database_audio,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
        )
        self.window.track_service.set_media_path(
            managed_track,
            "album_art",
            managed_cover,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
        )
        self.window.track_service.set_media_path(
            database_track,
            "album_art",
            database_cover,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
        )

        export_dir = self.root / "catalog-audio-exports"
        export_dir.mkdir()
        managed_snapshot = self.window.track_service.fetch_track_snapshot(managed_track)
        database_snapshot = self.window.track_service.fetch_track_snapshot(database_track)
        self.assertIsNotNone(managed_snapshot)
        self.assertIsNotNone(database_snapshot)
        assert managed_snapshot is not None
        assert database_snapshot is not None

        submitted_tasks: list[dict[str, object]] = []

        def _run_bundle_task_and_capture(window, **kwargs):
            submitted_tasks.append(dict(kwargs))
            return self._run_bundle_task_inline(window, **kwargs)

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=_run_bundle_task_and_capture,
            ),
            mock.patch.object(
                app_module.TagPreviewDialog,
                "exec",
                return_value=app_module.QDialog.Accepted,
            ),
            mock.patch.object(
                app_module.QFileDialog,
                "getExistingDirectory",
                return_value=str(export_dir),
            ),
            mock.patch.object(app_module.QMessageBox, "information"),
        ):
            self.window.export_catalog_audio_copies([managed_track, database_track])

        exported_paths = sorted(export_dir.glob("*.wav"))
        self.assertEqual(len(exported_paths), 2)

        exported_tags = {
            self.window.audio_tag_service.read_tags(
                path
            ).title: self.window.audio_tag_service.read_tags(path)
            for path in exported_paths
        }
        self.assertIn("Managed Export Track", exported_tags)
        self.assertIn("Database Export Track", exported_tags)
        self.assertEqual(
            [str(task.get("description") or "") for task in submitted_tasks],
            [
                "Preparing the catalog audio copy export preview...",
                "Copying selected catalog audio in its current source format and embedding catalog metadata when it is available...",
            ],
        )
        self.assertEqual(len(submitted_tasks), 2)
        self.assertIsNone(submitted_tasks[0].get("worker_completion_progress"))
        self.assertIsNone(submitted_tasks[0].get("on_success_before_cleanup"))
        self.assertIsNone(submitted_tasks[0].get("on_success"))
        self.assertTrue(callable(submitted_tasks[0].get("on_success_after_cleanup")))
        self.assertEqual(
            submitted_tasks[1].get("worker_completion_progress"),
            (96, "Finalizing catalog audio copy export results..."),
        )
        self.assertTrue(callable(submitted_tasks[1].get("on_success_before_cleanup")))
        self.assertIsNone(submitted_tasks[1].get("on_success"))
        self.assertTrue(callable(submitted_tasks[1].get("on_success_after_cleanup")))
        self.assertEqual(exported_tags["Managed Export Track"].isrc, managed_snapshot.isrc)
        self.assertEqual(exported_tags["Database Export Track"].isrc, database_snapshot.isrc)
        self.assertIsNotNone(exported_tags["Managed Export Track"].artwork)
        self.assertEqual(
            exported_tags["Managed Export Track"].artwork.data,
            managed_cover.read_bytes(),
        )
        self.assertIsNotNone(exported_tags["Database Export Track"].artwork)
        self.assertEqual(
            exported_tags["Database Export Track"].artwork.data,
            database_cover.read_bytes(),
        )

    def case_export_standard_audio_file_embeds_catalog_metadata_on_export(self):
        track_id = self._create_track(
            index=197,
            title="Direct Audio Export Track",
            album_title="Direct Export Album",
        )
        audio_path = self._create_wav_file("direct-export.wav")
        self.window.track_service.set_media_path(track_id, "audio_file", audio_path)
        export_path = self.root / "direct-audio-export.wav"
        submitted_tasks: list[dict[str, object]] = []

        def _run_bundle_task_and_capture(window, **kwargs):
            submitted_tasks.append(dict(kwargs))
            return self._run_bundle_task_inline(window, **kwargs)

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=_run_bundle_task_and_capture,
            ),
            mock.patch.object(
                app_module.QFileDialog,
                "getSaveFileName",
                return_value=(str(export_path), "All files (*)"),
            ),
            mock.patch.object(app_module.QMessageBox, "information"),
        ):
            self.window._export_standard_media_for_track(track_id, "audio_file")

        self.assertEqual(len(submitted_tasks), 1)
        self.assertEqual(
            submitted_tasks[0].get("worker_completion_progress"), (100, "Export complete.")
        )
        self.assertIsNone(submitted_tasks[0].get("on_success"))
        self.assertTrue(callable(submitted_tasks[0].get("on_success_after_cleanup")))
        exported_tags = self.window.audio_tag_service.read_tags(export_path)
        snapshot = self.window.track_service.fetch_track_snapshot(track_id)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(exported_tags.title, "Direct Audio Export Track")
        self.assertEqual(exported_tags.artist, snapshot.artist_name)
        self.assertEqual(exported_tags.album, "Direct Export Album")
        self.assertEqual(exported_tags.isrc, snapshot.isrc)

    def case_bulk_audio_column_export_uses_background_task_and_embeds_catalog_metadata(self):
        managed_track = self._create_track(
            index=198,
            title="Bulk Managed Export Track",
            album_title="Bulk Export Album",
        )
        database_track = self._create_track(
            index=199,
            title="Bulk Database Export Track",
            album_title="Bulk Export Album",
        )
        managed_audio = self._create_wav_file("bulk-managed-export.wav")
        database_audio = self._create_wav_file("bulk-database-export.wav")
        self.window.track_service.set_media_path(managed_track, "audio_file", managed_audio)
        self.window.track_service.set_media_path(
            database_track,
            "audio_file",
            database_audio,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
        )
        output_dir = self.root / "bulk-audio-column-export"
        output_dir.mkdir()
        audio_col = self.window._column_index_by_header("Audio File")
        if audio_col < 0:
            audio_col = self.window._column_index_by_header("Audio")
        self.assertGreaterEqual(audio_col, 0)
        submitted_tasks: list[dict[str, object]] = []

        def _run_bundle_task_and_capture(window, **kwargs):
            submitted_tasks.append(dict(kwargs))
            return self._run_bundle_task_inline(window, **kwargs)

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=_run_bundle_task_and_capture,
            ),
            mock.patch.object(
                app_module.QFileDialog,
                "getExistingDirectory",
                return_value=str(output_dir),
            ),
            mock.patch.object(app_module.QMessageBox, "information"),
        ):
            self.window._export_focused_media_column(
                audio_col,
                track_ids=[managed_track, database_track],
            )

        self.assertEqual(len(submitted_tasks), 1)
        self.assertEqual(
            submitted_tasks[0].get("worker_completion_progress"),
            (100, "Export Audio File complete."),
        )
        self.assertIsNone(submitted_tasks[0].get("on_success"))
        self.assertTrue(callable(submitted_tasks[0].get("on_success_after_cleanup")))
        exported_paths = sorted(output_dir.glob("*.wav"))
        self.assertEqual(len(exported_paths), 2)
        exported_tags = {
            self.window.audio_tag_service.read_tags(
                path
            ).title: self.window.audio_tag_service.read_tags(path)
            for path in exported_paths
        }
        self.assertEqual(
            {title for title in exported_tags},
            {"Bulk Managed Export Track", "Bulk Database Export Track"},
        )
        self.assertEqual(
            exported_tags["Bulk Managed Export Track"].album,
            "Bulk Export Album",
        )
        self.assertEqual(
            exported_tags["Bulk Database Export Track"].album,
            "Bulk Export Album",
        )

    def case_album_entry_track_sections_use_internal_tabs(self):
        dialog = app_module.AlbumEntryDialog(self.window)
        try:
            section_tabs = dialog.findChildren(app_module.QTabWidget, "albumTrackSectionTabs")
            self.assertGreaterEqual(len(section_tabs), 1)
            self.assertEqual(
                [section_tabs[0].tabText(index) for index in range(section_tabs[0].count())],
                [
                    "Governance",
                    "Details",
                    "Codes",
                    "Media",
                ],
            )
            self.assertEqual(section_tabs[0].currentWidget().property("role"), "tabPaneCanvas")
            section_widget = dialog.findChild(app_module.QWidget, "albumTrackSection")
            self.assertIsNotNone(section_widget)
            self.assertEqual(section_widget.property("role"), "tabPaneCanvas")
            compact_groups = [
                frame
                for frame in dialog.findChildren(app_module.QFrame)
                if frame.property("role") == "compactControlGroup"
            ]
            self.assertTrue(compact_groups)
            self.assertTrue(
                any(
                    group.testAttribute(app_module.Qt.WA_StyledBackground)
                    for group in compact_groups
                )
            )
            current_page = dialog.primary_tabs.currentWidget()
            self.assertEqual(current_page.property("role"), "workspaceCanvas")
            self.assertIsInstance(dialog.catalog_number, app_module.QComboBox)
            self.assertTrue(dialog.catalog_number.isEditable())
        finally:
            dialog.close()

    def case_album_entry_can_create_tracks_under_selected_work(self):
        work_id = self.window.work_service.create_work(
            app_module.WorkPayload(title="Governed Album Work", iswc="T-123.456.789-0")
        )
        dialog = app_module.AlbumEntryDialog(
            self.window,
            work_id=work_id,
            lock_work=True,
            relationship_type="alternate_master",
        )
        try:
            self.assertEqual(dialog.windowTitle(), "Add Album")

            dialog.album_title.setCurrentText("Governed Album")
            first_section = dialog._track_sections[0]
            second_section = dialog._track_sections[1]
            self.assertEqual(first_section.selected_governance_mode(), "link_existing_work")
            self.assertEqual(first_section.selected_work_id(), work_id)
            self.assertEqual(second_section.selected_governance_mode(), "link_existing_work")
            self.assertEqual(second_section.selected_work_id(), work_id)
            first_relationship_index = first_section.relationship_type.findData("alternate_master")
            second_relationship_index = second_section.relationship_type.findData(
                "alternate_master"
            )
            first_section.relationship_type.setCurrentIndex(first_relationship_index)
            second_section.relationship_type.setCurrentIndex(second_relationship_index)
            first_section.track_title.setText("Governed Album Mix")
            first_section.artist_name.setCurrentText("Moonwake")
            second_section.track_title.setText("Governed Album Dub")
            second_section.artist_name.setCurrentText("Moonwake")
            dialog.save_album()
            self.app.processEvents()

            created_rows = self.window.conn.execute(
                """
                SELECT track_title, work_id, relationship_type
                FROM Tracks
                WHERE album_id = (
                    SELECT id FROM Albums WHERE title=? ORDER BY id DESC LIMIT 1
                )
                ORDER BY track_title
                """,
                ("Governed Album",),
            ).fetchall()
            self.assertEqual(
                created_rows,
                [
                    ("Governed Album Dub", work_id, "alternate_master"),
                    ("Governed Album Mix", work_id, "alternate_master"),
                ],
            )
        finally:
            dialog.close()

    def case_album_entry_creates_parent_work_per_track_when_no_work_selected(self):
        dialog = app_module.AlbumEntryDialog(self.window)
        try:
            self.assertEqual(dialog.windowTitle(), "Add Album")
            dialog.album_title.setCurrentText("Auto Governed Album")
            first_section = dialog._track_sections[0]
            second_section = dialog._track_sections[1]
            self.assertEqual(first_section.selected_governance_mode(), "create_new_work")
            self.assertEqual(second_section.selected_governance_mode(), "create_new_work")
            first_section.track_title.setText("Auto Governed One")
            first_section.artist_name.setCurrentText("Moonwake")
            first_section.iswc.setText("T-123.456.789-0")
            second_section.track_title.setText("Auto Governed Two")
            second_section.artist_name.setCurrentText("Moonwake")
            second_section.iswc.setText("T-123.456.780-0")
            dialog.save_album()
            self.app.processEvents()

            rows = self.window.conn.execute(
                """
                SELECT t.track_title, t.work_id, t.relationship_type, w.title, w.iswc
                FROM Tracks t
                JOIN Works w ON w.id = t.work_id
                WHERE t.album_id = (
                    SELECT id FROM Albums WHERE title=? ORDER BY id DESC LIMIT 1
                )
                ORDER BY t.track_title
                """,
                ("Auto Governed Album",),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], "Auto Governed One")
            self.assertEqual(rows[0][2:], ("original", "Auto Governed One", "T-123.456.789-0"))
            self.assertEqual(rows[1][0], "Auto Governed Two")
            self.assertEqual(rows[1][2:], ("original", "Auto Governed Two", "T-123.456.780-0"))
            linked_track_ids = {
                int(issue.track_id)
                for issue in self.window.quality_service.scan().issues
                if issue.issue_type == "track_missing_linked_work" and issue.track_id is not None
            }
            for track_title, work_id, _relationship_type, _work_title, _work_iswc in rows:
                self.assertIsNotNone(work_id, track_title)
                track_id = self.window.conn.execute(
                    "SELECT id FROM Tracks WHERE track_title=? ORDER BY id DESC LIMIT 1",
                    (track_title,),
                ).fetchone()[0]
                self.assertNotIn(int(track_id), linked_track_ids)
        finally:
            dialog.close()

    def case_save_recording_without_work_context_redirects_to_governed_creation(self):
        existing_count = self.window.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0]

        self.window.open_add_track_entry()
        mode_index = self.window.add_data_work_mode_combo.findData("link_existing_work")
        self.window.add_data_work_mode_combo.setCurrentIndex(mode_index)
        self.app.processEvents()
        self.window.track_title_field.setText("Ungoverned Track Attempt")
        self.window.artist_field.setCurrentText("Moonwake")

        with mock.patch.object(
            app_module.QMessageBox,
            "warning",
            return_value=app_module.QMessageBox.Ok,
        ) as warning:
            self.window.save()
            self.app.processEvents()

        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[1], "Missing Work")
        current_count = self.window.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0]
        self.assertEqual(current_count, existing_count)

    def case_add_track_creates_new_work_from_track_with_seeded_work_metadata_and_party_artist(self):
        party_id = self.window.party_service.create_party(
            PartyPayload(
                legal_name="Lyra Moonwake",
                artist_name="Aeonium Official",
                party_type="person",
            )
        )
        self.window.populate_all_comboboxes()
        self.window.add_track_action.trigger()
        self.app.processEvents()

        self.assertEqual(self.window.add_data_title.text(), "Add Track")
        self.assertEqual(
            self.window._current_work_track_context().get("mode"),
            "create_new_work",
        )
        artist_index = self.window.artist_field.findData(party_id)
        self.assertGreaterEqual(artist_index, 0)
        self.window.artist_field.setCurrentIndex(artist_index)
        self.window.track_title_field.setText("Party Governed Origin")
        self.window.iswc_field.setText("T-123.456.700-0")
        self.window.buma_work_number_field.setText("WRK-700")
        self.window.album_title_field.setCurrentText("Party Governed Album")

        with mock.patch.object(
            app_module.QMessageBox,
            "information",
            return_value=app_module.QMessageBox.Ok,
        ):
            self.window.save()
            self.app.processEvents()

        track_id = self.window.conn.execute(
            "SELECT id FROM Tracks WHERE track_title=? ORDER BY id DESC LIMIT 1",
            ("Party Governed Origin",),
        ).fetchone()[0]
        snapshot = self.window.track_service.fetch_track_snapshot(track_id)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.artist_name, "Aeonium Official")
        work_row = self.window.conn.execute(
            """
            SELECT t.work_id, t.relationship_type, w.title, w.iswc, w.registration_number
            FROM Tracks t
            JOIN Works w ON w.id = t.work_id
            WHERE t.id=?
            """,
            (track_id,),
        ).fetchone()
        self.assertIsNotNone(work_row)
        assert work_row is not None
        work_id, relationship_type, work_title, work_iswc, work_registration = work_row
        self.assertIsNotNone(work_id)
        self.assertEqual(relationship_type, "original")
        self.assertEqual(work_title, "Party Governed Origin")
        self.assertEqual(work_iswc, "T-123.456.700-0")
        self.assertEqual(work_registration, "WRK-700")
        linked_track_ids = {
            int(issue.track_id)
            for issue in self.window.quality_service.scan().issues
            if issue.issue_type == "track_missing_linked_work" and issue.track_id is not None
        }
        self.assertNotIn(int(track_id), linked_track_ids)

    def case_album_entry_can_mix_existing_and_new_work_governance_per_row(self):
        existing_work_id = self.window.work_service.create_work(
            app_module.WorkPayload(title="Existing Batch Work", iswc="T-123.456.710-0")
        )
        dialog = app_module.AlbumEntryDialog(self.window)
        try:
            dialog.album_title.setCurrentText("Mixed Governance Album")
            first_section = dialog._track_sections[0]
            second_section = dialog._track_sections[1]
            first_mode_index = first_section.governance_mode.findData("link_existing_work")
            first_section.governance_mode.setCurrentIndex(first_mode_index)
            first_work_index = first_section.parent_work.findData(existing_work_id)
            first_section.parent_work.setCurrentIndex(first_work_index)
            first_relationship_index = first_section.relationship_type.findData("remix")
            first_section.relationship_type.setCurrentIndex(first_relationship_index)
            first_section.track_title.setText("Existing Work Remix")
            first_section.artist_name.setCurrentText("Moonwake")

            self.assertEqual(second_section.selected_governance_mode(), "create_new_work")
            second_section.track_title.setText("Fresh Batch Original")
            second_section.artist_name.setCurrentText("Moonwake")
            second_section.iswc.setText("T-123.456.711-0")
            second_section.buma_work_number.setText("WRK-711")

            dialog.save_album()
            self.app.processEvents()

            rows = self.window.conn.execute(
                """
                SELECT t.track_title, t.work_id, t.relationship_type, w.title, w.iswc, w.registration_number
                FROM Tracks t
                JOIN Works w ON w.id = t.work_id
                WHERE t.album_id = (
                    SELECT id FROM Albums WHERE title=? ORDER BY id DESC LIMIT 1
                )
                ORDER BY t.track_title
                """,
                ("Mixed Governance Album",),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                rows[0],
                (
                    "Existing Work Remix",
                    existing_work_id,
                    "remix",
                    "Existing Batch Work",
                    "T-123.456.710-0",
                    None,
                ),
            )
            self.assertEqual(rows[1][0], "Fresh Batch Original")
            self.assertNotEqual(rows[1][1], existing_work_id)
            self.assertEqual(
                rows[1][2:],
                ("original", "Fresh Batch Original", "T-123.456.711-0", "WRK-711"),
            )
        finally:
            dialog.close()

    def case_add_data_comboboxes_include_release_level_catalog_values(self):
        with self.window.conn:
            self.window.conn.execute(
                """
                INSERT INTO Releases(title, release_type, upc, catalog_number)
                VALUES (?, ?, ?, ?)
                """,
                ("Overview Release", "album", "8720892724990", "CAT-REL-900"),
            )

        self.window.populate_all_comboboxes()

        upc_values = [
            self.window.upc_field.itemText(index) for index in range(self.window.upc_field.count())
        ]
        catalog_values = [
            self.window.catalog_number_field.itemText(index)
            for index in range(self.window.catalog_number_field.count())
        ]
        self.assertIn("8720892724990", upc_values)
        self.assertIn("CAT-REL-900", catalog_values)

    def case_gs1_dialog_uses_top_level_workflow_tabs(self):
        track_id = self._create_track(index=9002, title="GS1 Layout", album_title="GS1 Layout")
        self.window.track_service.update_track(
            TrackUpdatePayload(
                track_id=track_id,
                isrc="NL-TST-26-09002",
                track_title="GS1 Layout",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="GS1 Layout",
                release_date="2026-03-17",
                track_length_sec=185,
                iswc=None,
                upc="8720892724649",
                genre="Ambient",
                catalog_number=None,
            )
        )

        with mock.patch.object(
            app_module.GS1MetadataDialog, "_refresh_template_status", return_value=False
        ):
            dialog = app_module.GS1MetadataDialog(
                app=self.window,
                track_id=track_id,
                batch_track_ids=[track_id],
                parent=self.window,
            )
        try:
            tabs = dialog.findChild(app_module.QTabWidget, "gs1MetadataDialogTabs")
            self.assertIsNotNone(tabs)
            self.assertEqual(
                [tabs.tabText(index) for index in range(tabs.count())],
                [
                    "Overview",
                    "Workbook",
                    "Product Groups",
                    "Readiness",
                ],
            )
        finally:
            dialog.close()

    def case_authenticity_actions_are_present_in_catalog_and_settings_menus(self):
        self.assertEqual(
            self.window.write_tags_to_exported_audio_action.text(),
            "Export Catalog Audio Copies…",
        )
        self.assertEqual(
            self.window.convert_selected_audio_action.text(),
            "Export Audio Derivatives…",
        )
        self.assertEqual(
            self.window.export_forensic_watermarked_audio_action.text(),
            "Export Forensic Watermarked Audio…",
        )
        self.assertEqual(
            self.window.convert_external_audio_files_action.text(),
            "Convert External Audio Files…",
        )
        self.assertEqual(
            self.window.export_authenticity_watermarked_audio_action.text(),
            "Export Authentic Masters…",
        )
        self.assertEqual(
            self.window.export_authenticity_provenance_audio_action.text(),
            "Export Provenance Copies…",
        )
        self.assertIn(
            "Direct watermark master export",
            self.window.export_authenticity_watermarked_audio_action.toolTip(),
        )
        self.assertIn(
            "No managed derivative registration",
            self.window.export_authenticity_provenance_audio_action.toolTip(),
        )
        self.assertIn(
            "Recipient-specific lossy delivery export",
            self.window.export_forensic_watermarked_audio_action.toolTip(),
        )
        self.assertIn(
            "automatic catalog metadata embedding",
            self.window.write_tags_to_exported_audio_action.toolTip(),
        )
        self.assertIn(
            "Source metadata is stripped".lower(),
            self.window.convert_external_audio_files_action.toolTip().lower(),
        )
        self.assertEqual(
            self.window.inspect_forensic_watermark_action.text(),
            "Inspect Forensic Watermark…",
        )
        self.assertEqual(
            self.window.verify_audio_authenticity_action.text(),
            "Verify Audio Authenticity…",
        )
        self.assertEqual(
            self.window.authenticity_keys_action.text(),
            "Audio Authenticity Keys…",
        )
        action_ids = {entry["id"] for entry in self.window._action_ribbon_specs}
        self.assertIn("convert_selected_audio", action_ids)
        self.assertIn("forensic_export_audio", action_ids)
        self.assertIn("convert_external_audio", action_ids)
        self.assertIn("authenticity_export_audio", action_ids)
        self.assertIn("authenticity_export_provenance_audio", action_ids)
        self.assertIn("authenticity_verify_audio", action_ids)
        self.assertIn("forensic_inspect_audio", action_ids)
        self.assertIn("authenticity_keys", action_ids)

    def case_authenticity_table_context_menu_exposes_export_actions(self):
        lossy_track_id = self._create_track(
            index=303,
            title="Context Auth Track",
            album_title="Single",
        )
        lossless_track_id = self._create_track(
            index=304,
            title="Context WAV Track",
            album_title="Single",
        )
        lossy_audio = self._create_media_file("context-auth.mp3", b"ID3context-auth")
        lossless_audio = self._create_wav_file("context-auth.wav")
        self.window.track_service.set_media_path(lossy_track_id, "audio_file", lossy_audio)
        self.window.track_service.set_media_path(lossless_track_id, "audio_file", lossless_audio)
        self.window.release_service.create_release(
            app_module.ReleasePayload(
                title="Context Auth Release",
                primary_artist="Context Artist",
                release_type="single",
                release_date="2026-03-23",
                placements=[
                    app_module.ReleaseTrackPlacement(
                        track_id=lossy_track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.window.refresh_table()
        row = self._table_row_for_track_id(lossy_track_id)

        snapshot = self._table_context_menu_snapshot(row, 0)
        top_level_texts = list(snapshot.get("texts") or [])
        licenses_snapshot = (snapshot.get("submenus") or {}).get("Licenses") or {}
        license_texts = self._flatten_menu_snapshot(licenses_snapshot)
        audio_snapshot = (snapshot.get("submenus") or {}).get("Audio") or {}
        audio_texts = self._flatten_menu_snapshot(audio_snapshot)

        self.assertIn("Edit Track", top_level_texts)
        self.assertIn("GS1 Metadata…", top_level_texts)
        self.assertIn("Open Primary Release…", top_level_texts)
        self.assertIn("Link Selected Track(s) to Work…", top_level_texts)
        self.assertIn("Delete Track", top_level_texts)
        self.assertIn("Audio", top_level_texts)

        self.assertNotIn("Import Metadata from Audio Files…", top_level_texts)
        self.assertNotIn("Export Audio Derivatives…", top_level_texts)
        self.assertNotIn("Export Catalog Audio Copies…", top_level_texts)
        self.assertNotIn("Convert External Audio Files…", top_level_texts)
        self.assertFalse(licenses_snapshot)
        self.assertEqual(license_texts, [])

        self.assertIn("Import Metadata from Audio Files…", audio_texts)
        self.assertIn("Export Audio Derivatives…", audio_texts)
        self.assertIn("Export Authentic Masters…", audio_texts)
        self.assertIn("Export Provenance Copies…", audio_texts)
        self.assertIn("Export Forensic Watermarked Audio…", audio_texts)
        self.assertIn("Export Catalog Audio Copies…", audio_texts)
        self.assertIn("Inspect Forensic Watermark…", audio_texts)
        self.assertIn("Verify Audio Authenticity…", audio_texts)
        self.assertNotIn("Convert External Audio Files…", audio_texts)
        audio_col = self.window._column_index_by_header("Audio File")
        self.assertGreaterEqual(audio_col, 0)
        lossy_item = self.window.table.item(row, audio_col)
        self.assertIsNotNone(lossy_item)
        assert lossy_item is not None
        self.assertIn("Lossy primary audio", lossy_item.toolTip())
        self.assertIn("MP3", lossy_item.toolTip())
        lossless_row = self._table_row_for_track_id(lossless_track_id)
        lossless_item = self.window.table.item(lossless_row, audio_col)
        self.assertIsNotNone(lossless_item)
        assert lossless_item is not None
        self.assertIn("Primary audio", lossless_item.toolTip())
        self.assertNotIn("Lossy primary audio", lossless_item.toolTip())
        self.assertNotEqual(lossy_item.icon().cacheKey(), lossless_item.icon().cacheKey())

    def case_table_context_menu_keeps_multi_selection_when_right_clicking_selected_row(self):
        first_track_id = self._create_track(index=330, title="Selection A")
        second_track_id = self._create_track(index=331, title="Selection B")
        self.window.refresh_table()
        self._select_track_ids([first_track_id, second_track_id])
        first_row = self._table_row_for_track_id(first_track_id)

        snapshot = self._table_context_menu_snapshot(first_row, 0)
        self.assertIn("Bulk Edit 2 Selected Tracks…", list(snapshot.get("texts") or []))
        self.assertEqual(
            sorted(self.window._selected_track_ids()), [first_track_id, second_track_id]
        )

    def case_audioless_row_context_menu_omits_audio_submenu(self):
        track_id = self._create_track(index=332, title="Metadata Only Track")
        self.window.refresh_table()
        row = self._table_row_for_track_id(track_id)

        snapshot = self._table_context_menu_snapshot(row, 0)
        self.assertNotIn("Audio", list(snapshot.get("texts") or []))

    def case_standard_media_context_menu_groups_file_and_storage_actions(self):
        track_id = self._create_track(index=333, title="Managed Media Track")
        audio_path = self._create_wav_file("standard-media.wav")
        self.window.track_service.set_media_path(track_id, "audio_file", audio_path)
        self.window.refresh_table()
        row = self._table_row_for_track_id(track_id)
        audio_col = self.window._column_index_by_header("Audio File")

        snapshot = self._table_context_menu_snapshot(row, audio_col)
        file_snapshot = (snapshot.get("submenus") or {}).get("File") or {}
        storage_snapshot = (snapshot.get("submenus") or {}).get("Storage") or {}
        self.assertIn("File", list(snapshot.get("texts") or []))
        self.assertIn("Storage", list(snapshot.get("texts") or []))
        self.assertEqual(
            list(file_snapshot.get("texts") or []),
            [
                "Preview File…",
                "Attach/Replace File…",
                "Export 'Managed Media Track'…",
                "Delete File…",
            ],
        )
        self.assertEqual(list(storage_snapshot.get("texts") or []), ["Store in Database"])

    def case_custom_blob_context_menu_groups_file_and_storage_actions(self):
        track_id = self._create_track(index=334, title="Blob Custom Track")
        self.assertTrue(
            self.window._apply_custom_field_configuration(
                [
                    {
                        "id": None,
                        "name": "Session Artwork",
                        "field_type": "blob_image",
                        "options": None,
                        "blob_icon_payload": {"mode": "inherit"},
                    }
                ],
                action_label="Add Custom Column: Session Artwork",
                action_type="fields.add",
            )
        )
        field = next(
            field
            for field in self.window.active_custom_fields
            if field.get("name") == "Session Artwork"
        )
        image_path = self._create_media_file("session-artwork.png", b"\x89PNG\r\n\x1a\ncustom")
        self.window.cf_save_value(
            track_id,
            int(field["id"]),
            blob_path=str(image_path),
            storage_mode=STORAGE_MODE_DATABASE,
        )
        self.window.refresh_table()
        row = self._table_row_for_track_id(track_id)
        col = self.window._column_index_by_header("Session Artwork")

        snapshot = self._table_context_menu_snapshot(row, col)
        file_snapshot = (snapshot.get("submenus") or {}).get("File") or {}
        storage_snapshot = (snapshot.get("submenus") or {}).get("Storage") or {}
        self.assertIn("File", list(snapshot.get("texts") or []))
        self.assertIn("Storage", list(snapshot.get("texts") or []))
        self.assertEqual(
            list(file_snapshot.get("texts") or []),
            [
                "Preview File…",
                "Attach/Replace File…",
                "Export 'Blob Custom Track'…",
                "Delete File…",
            ],
        )
        self.assertEqual(list(storage_snapshot.get("texts") or []), ["Store as Managed File"])

    def case_text_custom_field_table_edit_saves_without_attachment_state(self):
        track_id = self._create_track(index=335, title="Text Custom Track")
        self.assertTrue(
            self.window._apply_custom_field_configuration(
                [
                    {
                        "id": None,
                        "name": "Mood Notes",
                        "field_type": "text",
                        "options": None,
                    }
                ],
                action_label="Add Custom Column: Mood Notes",
                action_type="fields.add",
            )
        )
        self.window.refresh_table_preserve_view(focus_id=track_id)
        self.app.processEvents()

        row = self._table_row_for_track_id(track_id)
        col = self.window._column_index_by_header("Mood Notes")
        history_before = len(self.window.history_manager.list_entries(limit=50))

        with (
            mock.patch.object(
                app_module.QInputDialog,
                "getMultiLineText",
                return_value=("Dreamy and spacious", True),
            ),
            mock.patch.object(app_module.QMessageBox, "critical") as critical_mock,
        ):
            self.window._on_item_double_clicked(self.window.table.item(row, col))

        critical_mock.assert_not_called()
        stored = self.window.conn.execute(
            """
            SELECT value, blob_value, managed_file_path, storage_mode, filename, mime_type, size_bytes
            FROM CustomFieldValues cfv
            JOIN CustomFieldDefs cfd ON cfd.id = cfv.field_def_id
            WHERE cfv.track_id=? AND cfd.name='Mood Notes'
            """,
            (track_id,),
        ).fetchone()
        self.assertEqual(stored, ("Dreamy and spacious", None, "", "", "", "", 0))
        history_after = self.window.history_manager.list_entries(limit=50)
        self.assertEqual(len(history_after), history_before + 1)
        self.assertEqual(history_after[0].label, "Update Custom Field: Mood Notes")

    def case_verify_audio_authenticity_can_choose_external_file_when_track_is_selected(self):
        track_id = self._create_track(index=301, title="Catalog Verify Track", album_title="Single")
        selected_audio = self._create_wav_file("catalog-verify.wav")
        external_audio = self._create_wav_file("external-verify.wav")
        self.window.track_service.set_media_path(track_id, "audio_file", selected_audio)
        self.window.refresh_table()
        self._select_track_ids([track_id])

        captured_paths: list[Path] = []

        def _fake_verify(_service, path):
            resolved = Path(path).resolve()
            captured_paths.append(resolved)
            return SimpleNamespace(
                status="no_watermark_detected",
                message="No watermark was detected in the inspected audio.",
                inspected_path=str(resolved),
                key_id=None,
                manifest_id=None,
                watermark_id=None,
                resolution_source=None,
                signature_valid=None,
                exact_hash_match=None,
                fingerprint_similarity=None,
                extraction_confidence=None,
                sidecar_path=None,
                details=[],
            )

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=self._run_bundle_task_inline,
            ),
            mock.patch.object(
                app_module.App,
                "_prompt_audio_authenticity_verification_source",
                autospec=True,
                return_value="external",
            ) as source_prompt_mock,
            mock.patch.object(
                app_module.QFileDialog,
                "getOpenFileName",
                return_value=(
                    str(external_audio),
                    "Audio Files (*.wav *.flac *.aif *.aiff *.mp3 *.ogg *.oga *.opus *.m4a *.mp4 *.aac)",
                ),
            ) as picker_mock,
            mock.patch.object(
                app_module.AudioAuthenticityService,
                "verify_file",
                autospec=True,
                side_effect=_fake_verify,
            ),
            mock.patch.object(
                app_module.AuthenticityVerificationDialog,
                "exec",
                return_value=app_module.QDialog.Accepted,
            ),
        ):
            self.window.verify_audio_authenticity()

        self.assertEqual(captured_paths, [external_audio.resolve()])
        source_prompt_mock.assert_called_once()
        picker_mock.assert_called_once()

    def case_verify_audio_authenticity_can_use_selected_database_audio(self):
        track_id = self._create_track(
            index=302, title="Database Verify Track", album_title="Single"
        )
        source_audio = self._create_wav_file("database-verify.wav")
        expected_bytes = source_audio.read_bytes()
        self.window.track_service.set_media_path(
            track_id,
            "audio_file",
            source_audio,
            storage_mode=app_module.STORAGE_MODE_DATABASE,
        )
        self.window.refresh_table()
        self._select_track_ids([track_id])

        captured: dict[str, object] = {}

        def _fake_verify(_service, path):
            resolved = Path(path).resolve()
            captured["path"] = resolved
            captured["exists_during_verify"] = resolved.exists()
            captured["bytes_during_verify"] = resolved.read_bytes()
            return SimpleNamespace(
                status="no_watermark_detected",
                message="No watermark was detected in the inspected audio.",
                inspected_path=str(resolved),
                key_id=None,
                manifest_id=None,
                watermark_id=None,
                resolution_source=None,
                signature_valid=None,
                exact_hash_match=None,
                fingerprint_similarity=None,
                extraction_confidence=None,
                sidecar_path=None,
                details=[],
            )

        with (
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                autospec=True,
                side_effect=self._run_bundle_task_inline,
            ),
            mock.patch.object(
                app_module.App,
                "_prompt_audio_authenticity_verification_source",
                autospec=True,
                return_value="selected",
            ) as source_prompt_mock,
            mock.patch.object(
                app_module.QFileDialog,
                "getOpenFileName",
            ) as picker_mock,
            mock.patch.object(
                app_module.AudioAuthenticityService,
                "verify_file",
                autospec=True,
                side_effect=_fake_verify,
            ),
            mock.patch.object(
                app_module.AuthenticityVerificationDialog,
                "exec",
                return_value=app_module.QDialog.Accepted,
            ),
        ):
            self.window.verify_audio_authenticity()

        source_prompt_mock.assert_called_once()
        picker_mock.assert_not_called()
        self.assertTrue(bool(captured.get("exists_during_verify")))
        self.assertEqual(captured.get("bytes_during_verify"), expected_bytes)
        temp_path = captured.get("path")
        self.assertIsInstance(temp_path, Path)
        assert isinstance(temp_path, Path)
        self.assertFalse(temp_path.exists())

    def case_audio_preview_media_layout_uses_now_playing_header_and_artwork(self):
        primary_track = self._create_track(
            index=9101,
            title="Aurora Signal",
            album_title="Preview Layout A",
        )
        secondary_track = self._create_track(
            index=9102,
            title="Bare Echo",
            album_title="Preview Layout B",
        )
        self._attach_standard_media(
            primary_track,
            audio_path=self._create_wav_file("aurora-signal.wav"),
            album_art_path=self._create_png_file("aurora-signal.png"),
        )
        self._attach_standard_media(
            secondary_track,
            audio_path=self._create_wav_file("bare-echo.wav"),
        )

        dialog = self._open_audio_preview_dialog(primary_track)

        self.assertEqual(dialog.title_label.text(), "Aurora Signal")
        self.assertEqual(dialog.artist_label.text(), "Moonwake")
        self.assertEqual(dialog.album_label.text(), "Album · Preview Layout A")
        self.assertTrue(dialog.artwork_container.isVisible())

        for object_name, symbol in (
            ("audioPreviewPreviousButton", "|◀"),
            ("audioPreviewRewindButton", "◀◀"),
            ("audioPreviewPlayButton", "▶"),
            ("audioPreviewPauseButton", "▌▌"),
            ("audioPreviewStopButton", "■"),
            ("audioPreviewForwardButton", "▶▶"),
            ("audioPreviewNextButton", "▶|"),
        ):
            button = dialog.findChild(app_module.QToolButton, object_name)
            self.assertIsNotNone(button)
            self.assertEqual(button.text(), symbol)
            self.assertEqual(button.property("role"), "mediaTransportButton")

        label_texts = self._label_texts(dialog)
        for obsolete_text in (
            "Audio Preview",
            "Waveform Preview",
            "Playback Controls",
            "Listen back to the stored audio media for Aurora Signal and inspect its waveform when available.",
            "The waveform is generated from the stored audio file when supported by the current runtime.",
            "Use the transport buttons or the keyboard shortcuts to play, pause, stop, and scrub through the preview.",
        ):
            self.assertNotIn(obsolete_text, label_texts)

        dialog.open_track_preview(
            secondary_track,
            self.window._audio_preview_source_spec_for_standard_media("audio_file"),
            autoplay=False,
        )
        pump_events()
        self.assertTrue(dialog.artwork_container.isHidden())

    def case_audio_preview_layout_groups_and_theme_surfaces_are_exposed(self):
        track_id = self._create_track(
            index=9110,
            title="Grouped Preview",
            album_title="Layout Followup",
        )
        self._attach_standard_media(
            track_id,
            audio_path=self._create_wav_file("grouped-preview.wav"),
            album_art_path=self._create_png_file("grouped-preview.png"),
        )

        dialog = self._open_audio_preview_dialog(track_id)
        metadata_group = dialog.findChild(app_module.QGroupBox, "audioPreviewMetadataGroup")
        waveform_panel = dialog.findChild(app_module.QFrame, "audioPreviewWaveformPanel")
        playback_group = dialog.findChild(app_module.QGroupBox, "audioPreviewPlaybackGroup")
        export_group = dialog.findChild(app_module.QGroupBox, "audioPreviewExportGroup")

        self.assertIsNotNone(metadata_group)
        self.assertIsNotNone(waveform_panel)
        self.assertIsNotNone(playback_group)
        self.assertIsNotNone(export_group)
        self.assertIs(dialog.layout().itemAt(0).widget(), metadata_group)
        self.assertEqual(dialog.width(), dialog.DEFAULT_WINDOW_WIDTH)
        self.assertEqual(dialog.height(), dialog.DEFAULT_WINDOW_HEIGHT)
        self.assertEqual(dialog.wave.minimumHeight(), 100)
        self.assertEqual(dialog.wave.maximumHeight(), 100)
        self.assertEqual(dialog.artwork_label.height(), 200)
        self.assertEqual(dialog.artwork_label.width(), 200)
        self.assertTrue(playback_group.isAncestorOf(dialog.auto_advance_check))
        self.assertEqual(dialog.album_label.text(), "Album · Layout Followup")
        self.assertEqual(dialog.play_button.styleSheet(), "")
        self.assertEqual(dialog.play_button.font().family(), dialog.font().family())

        self.assertIs(dialog.layout().itemAt(2).widget(), dialog.playback_status_panel)
        status_geom = dialog.playback_status_panel.geometry()
        waveform_geom = waveform_panel.geometry()
        self.assertGreaterEqual(status_geom.top(), waveform_geom.bottom())
        self.assertEqual(dialog._label_time.parentWidget(), dialog.playback_status_panel)
        self.assertEqual(dialog._slider.parentWidget(), dialog.playback_status_panel)

        playback_layout = playback_group.layout()
        self.assertIsNotNone(playback_layout)
        transport_row = playback_layout.itemAt(0).layout()
        self.assertIsNotNone(transport_row)
        self.assertIs(transport_row.itemAt(0).widget(), dialog.previous_button)
        footer_row = playback_layout.itemAt(1).layout()
        self.assertIsNotNone(footer_row)
        self.assertIs(footer_row.itemAt(0).widget(), dialog.auto_advance_check)

        dialog.resize(1600, 1000)
        pump_events()
        self.assertLessEqual(
            playback_group.height(),
            playback_group.sizeHint().height() + 24,
        )
        self.assertLessEqual(
            export_group.height(),
            export_group.sizeHint().height() + 24,
        )
        self.assertLessEqual(
            abs(playback_group.geometry().top() - export_group.geometry().top()),
            2,
        )
        self.assertFalse(waveform_panel.geometry().intersects(playback_group.geometry()))
        self.assertFalse(waveform_panel.geometry().intersects(export_group.geometry()))
        self.assertFalse(dialog.artwork_container.geometry().intersects(playback_group.geometry()))
        self.assertFalse(dialog.artwork_container.geometry().intersects(export_group.geometry()))
        wave_center = dialog.wave.mapTo(dialog, dialog.wave.rect().center())
        artwork_center = dialog.artwork_label.mapTo(dialog, dialog.artwork_label.rect().center())
        self.assertLessEqual(abs(wave_center.y() - artwork_center.y()), 2)

        dialog.resize(dialog.minimumWidth(), dialog.minimumHeight())
        pump_events()
        self.assertFalse(waveform_panel.geometry().intersects(playback_group.geometry()))
        self.assertFalse(waveform_panel.geometry().intersects(export_group.geometry()))
        self.assertFalse(dialog.artwork_container.geometry().intersects(playback_group.geometry()))
        self.assertFalse(dialog.artwork_container.geometry().intersects(export_group.geometry()))

        selectors = {entry.selector for entry in collect_qss_reference_entries([dialog])}
        for selector in (
            "#audioPreviewDialog",
            "#audioPreviewMetadataGroup",
            "#audioPreviewWaveformPanel",
            "#audioPreviewPlaybackStatusPanel",
            "#audioPreviewPlaybackGroup",
            "#audioPreviewExportGroup",
            "#audioPreviewArtworkContainer",
            "#audioPreviewAlbumLabel",
            "#audioPreviewTimeLabel",
            "#audioPreviewAutoAdvanceCheck",
            '[role="mediaTransportButton"]',
            'QToolButton[role="mediaTransportButton"]',
            '[role="mediaToggle"]',
            'QCheckBox[role="mediaToggle"]',
            '[role="mediaExportButton"]',
            'QToolButton[role="mediaExportButton"]',
        ):
            self.assertIn(selector, selectors)

    def case_audio_preview_navigation_follows_visible_catalog_order_and_auto_advance(self):
        first_track = self._create_track(index=9103, title="Zulu Drift", album_title="Order Tests")
        middle_track = self._create_track(index=9104, title="Echo Bloom", album_title="Order Tests")
        last_track = self._create_track(index=9105, title="Aurora Fade", album_title="Order Tests")
        for track_id, filename in (
            (first_track, "zulu-drift.wav"),
            (middle_track, "echo-bloom.wav"),
            (last_track, "aurora-fade.wav"),
        ):
            self._attach_standard_media(
                track_id,
                audio_path=self._create_wav_file(filename),
            )

        title_column = self.window._column_index_by_header("Track Title")
        self.window.table.sortItems(title_column, Qt.AscendingOrder)
        pump_events()

        source_spec = self.window._audio_preview_source_spec_for_standard_media("audio_file")
        expected_order = self.window._audio_preview_navigation_track_ids(source_spec)
        dialog = self._open_audio_preview_dialog(expected_order[1])

        self.assertEqual(dialog._track_order, expected_order)
        self.assertTrue(dialog.auto_advance_check.isChecked())

        dialog._go_to_previous_track()
        self.assertEqual(dialog._current_track_id, expected_order[0])
        self.assertFalse(dialog.previous_button.isEnabled())
        self.assertTrue(dialog.next_button.isEnabled())

        dialog._go_to_next_track()
        self.assertEqual(dialog._current_track_id, expected_order[1])

        dialog.open_track_preview(expected_order[-1], source_spec, autoplay=False)
        pump_events()
        self.assertFalse(dialog.next_button.isEnabled())

        end_status = getattr(
            app_module.QMediaPlayer,
            "MediaStatus",
            app_module.QMediaPlayer,
        ).EndOfMedia

        dialog.open_track_preview(expected_order[1], source_spec, autoplay=False)
        pump_events()
        dialog._on_media_status_changed(end_status)
        self.assertEqual(dialog._current_track_id, expected_order[2])

        dialog.open_track_preview(expected_order[1], source_spec, autoplay=False)
        dialog.auto_advance_check.setChecked(False)
        pump_events()
        dialog._on_media_status_changed(end_status)
        self.assertEqual(dialog._current_track_id, expected_order[1])

    def case_audio_preview_waveform_wheel_scrub_and_shortcuts_are_wired(self):
        track_id = self._create_track(
            index=9106,
            title="Wheel Logic",
            album_title="Input Tests",
        )
        self._attach_standard_media(
            track_id,
            audio_path=self._create_wav_file("wheel-logic.wav"),
        )
        dialog = self._open_audio_preview_dialog(track_id)

        captured_deltas: list[int] = []
        wave = app_module.WaveformWidget()
        wave.scrubRequested.connect(captured_deltas.append)

        forward_event = _FakeWheelEvent(angle_y=-120)
        wave.wheelEvent(forward_event)
        self.assertTrue(forward_event.accepted)
        self.assertEqual(captured_deltas[-1], 1000)

        backward_event = _FakeWheelEvent(angle_y=120)
        wave.wheelEvent(backward_event)
        self.assertTrue(backward_event.accepted)
        self.assertEqual(captured_deltas[-1], -1000)

        shortcut_texts = {
            shortcut.key().toString() for shortcut in dialog.findChildren(app_module.QShortcut)
        }
        for expected in (
            "Space",
            "Left",
            "Right",
            "Shift+Left",
            "Shift+Right",
            "Meta+Left",
            "Meta+Right",
        ):
            self.assertIn(expected, shortcut_texts)

    def case_audio_preview_export_controls_route_to_existing_methods(self):
        track_id = self._create_track(
            index=9107,
            title="Export Controls",
            album_title="Export Controls",
        )
        self._attach_standard_media(
            track_id,
            audio_path=self._create_wav_file("export-controls.wav"),
        )

        for action_name in (
            "write_tags_to_exported_audio_action",
            "convert_selected_audio_action",
            "export_authenticity_watermarked_audio_action",
            "export_authenticity_provenance_audio_action",
            "export_forensic_watermarked_audio_action",
        ):
            action = getattr(self.window, action_name, None)
            if action is not None:
                action.setEnabled(True)

        with (
            mock.patch.object(
                self.window, "_export_standard_media_for_track"
            ) as export_current_mock,
            mock.patch.object(self.window, "export_catalog_audio_copies") as export_copies_mock,
            mock.patch.object(self.window, "convert_selected_audio") as export_derivatives_mock,
            mock.patch.object(
                self.window,
                "export_authenticity_watermarked_audio",
            ) as authentic_mock,
            mock.patch.object(
                self.window,
                "export_authenticity_provenance_audio",
            ) as provenance_mock,
            mock.patch.object(
                self.window,
                "export_forensic_watermarked_audio",
            ) as forensic_mock,
        ):
            dialog = self._open_audio_preview_dialog(track_id)

            actions = {action.text(): action for action in dialog.export_menu.actions()}
            self.assertIn("Export Current Audio…", actions)
            self.assertIn("Export Catalog Audio Copies…", actions)
            self.assertIn("Export Audio Derivatives…", actions)
            self.assertIn("Export Authentic Masters…", actions)
            self.assertIn("Export Provenance Copies…", actions)
            self.assertIn("Export Forensic Watermarked Audio…", actions)

            actions["Export Current Audio…"].trigger()
            export_current_mock.assert_called_once_with(track_id, "audio_file")

            actions["Export Catalog Audio Copies…"].trigger()
            export_copies_mock.assert_called_once_with([track_id])

            actions["Export Audio Derivatives…"].trigger()
            export_derivatives_mock.assert_called_once_with([track_id])

            actions["Export Authentic Masters…"].trigger()
            authentic_mock.assert_called_once_with([track_id])

            actions["Export Provenance Copies…"].trigger()
            provenance_mock.assert_called_once_with([track_id])

            actions["Export Forensic Watermarked Audio…"].trigger()
            forensic_mock.assert_called_once_with([track_id])

    def case_media_preview_windows_are_singleton_top_level_windows(self):
        audio_track_one = self._create_track(
            index=9108,
            title="Singleton One",
            album_title="Singleton Tests One",
        )
        audio_track_two = self._create_track(
            index=9109,
            title="Singleton Two",
            album_title="Singleton Tests Two",
        )
        for track_id, audio_name, art_name, color in (
            (audio_track_one, "singleton-one.wav", "singleton-one.png", "#C75B39"),
            (audio_track_two, "singleton-two.wav", "singleton-two.png", "#2C9A73"),
        ):
            self._attach_standard_media(
                track_id,
                audio_path=self._create_wav_file(audio_name),
                album_art_path=self._create_png_file(art_name, color=color),
            )

        audio_dialog = self._open_audio_preview_dialog(audio_track_one)
        audio_dialog.showMinimized()
        pump_events()
        reopened_audio_dialog = self._open_audio_preview_dialog(audio_track_two)
        self.assertIs(audio_dialog, reopened_audio_dialog)
        self.assertTrue(reopened_audio_dialog.isWindow())
        self.assertFalse(reopened_audio_dialog.isModal())
        self.assertIsNone(reopened_audio_dialog.parentWidget())
        self.assertTrue(bool(reopened_audio_dialog.windowFlags() & Qt.Window))
        self.assertTrue(bool(reopened_audio_dialog.windowFlags() & Qt.WindowMinimizeButtonHint))
        self.assertIsNotNone(reopened_audio_dialog.windowHandle())
        self.assertEqual(reopened_audio_dialog._current_track_id, audio_track_two)
        self.assertEqual(reopened_audio_dialog.title_label.text(), "Singleton Two")

        audio_dialog.close()
        pump_events()
        reopened_after_close = self._open_audio_preview_dialog(audio_track_one)
        self.assertIs(audio_dialog, reopened_after_close)
        self.assertFalse(reopened_after_close.isHidden())

        image_dialog = self._open_image_preview_dialog(audio_track_one)
        image_dialog.showMinimized()
        pump_events()
        reopened_image_dialog = self._open_image_preview_dialog(audio_track_two)
        self.assertIs(image_dialog, reopened_image_dialog)
        self.assertTrue(reopened_image_dialog.isWindow())
        self.assertFalse(reopened_image_dialog.isModal())
        self.assertIsNone(reopened_image_dialog.parentWidget())
        self.assertTrue(bool(reopened_image_dialog.windowFlags() & Qt.Window))
        self.assertTrue(bool(reopened_image_dialog.windowFlags() & Qt.WindowMinimizeButtonHint))
        self.assertIsNotNone(reopened_image_dialog.windowHandle())
        self.assertIn("Singleton Two", reopened_image_dialog.windowTitle())

    def case_image_preview_supports_zoom_gestures_fit_reset_and_export(self):
        track_id = self._create_track(
            index=9110,
            title="Image Controls",
            album_title="Image Controls Album",
        )
        self._attach_standard_media(
            track_id,
            album_art_path=self._create_png_file("image-controls.png", color="#8D53E2", size=320),
        )

        with mock.patch.object(self.window, "_export_bytes_with_picker") as export_mock:
            dialog = self._open_image_preview_dialog(track_id)

            fit_percent = dialog._fit_percent()
            self.assertEqual(dialog._zoom_slider.value(), fit_percent)

            wheel_event = _FakeWheelEvent(angle_y=120, modifiers=Qt.ControlModifier)
            handled = dialog.eventFilter(dialog._image_label, wheel_event)
            self.assertTrue(handled)
            self.assertTrue(wheel_event.accepted)
            self.assertGreater(dialog._zoom_slider.value(), fit_percent)

            native_zoom = _FakeNativeGestureEvent(Qt.ZoomNativeGesture, 0.2)
            handled = dialog.eventFilter(dialog._image_label, native_zoom)
            self.assertTrue(handled)
            self.assertTrue(native_zoom.accepted)
            self.assertTrue(dialog._user_zoomed)

            dialog._set_zoom_percent(175, user_initiated=True)
            double_click = _FakeMouseDoubleClickEvent()
            handled = dialog.eventFilter(dialog._image_label, double_click)
            self.assertTrue(handled)
            self.assertTrue(double_click.accepted)
            self.assertEqual(dialog._zoom_slider.value(), dialog._fit_percent())
            self.assertFalse(dialog._user_zoomed)

            self.assertEqual(dialog._export_button.text(), "Export Image…")
            dialog._export_button.click()
            export_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite()
