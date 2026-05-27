from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QByteArray, QRect
from PySide6.QtWidgets import QApplication, QComboBox, QMenu, QPushButton

from isrc_manager import main_window_layout
from isrc_manager.catalog_table import CATALOG_ZOOM_LAYOUT_KEY


class _Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.synced = 0

    def value(self, key, default=None, *args):
        del args
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.synced += 1


def _settings_app(values=None):
    app = SimpleNamespace(settings=_Settings(values))
    app._saved_main_window_layouts_setting_key = (
        main_window_layout._saved_main_window_layouts_setting_key
    )
    app._workspace_panels_setting_key = main_window_layout._workspace_panels_setting_key
    return app


def _ensure_qapp():
    return QApplication.instance() or QApplication([])


def test_main_window_layout_setting_serializers_and_loaders_handle_stale_payloads():
    encoded = main_window_layout._serialize_qbytearray_setting(QByteArray(b"dock-state"))

    assert encoded
    assert bytes(main_window_layout._deserialize_qbytearray_setting(encoded)) == b"dock-state"
    assert main_window_layout._serialize_qbytearray_setting(QByteArray()) == ""
    assert main_window_layout._serialize_qbytearray_setting(None) == ""
    assert main_window_layout._deserialize_qbytearray_setting("").isEmpty()
    assert main_window_layout._deserialize_qbytearray_setting("\u2603").isEmpty()
    assert main_window_layout._serialize_rect_setting(QRect(1, 2, 300, 400)) == {
        "x": 1,
        "y": 2,
        "width": 300,
        "height": 400,
    }
    assert main_window_layout._serialize_rect_setting(QRect()) is None
    assert main_window_layout._deserialize_rect_setting(
        {"x": 1, "y": 2, "width": 3, "height": 4}
    ) == QRect(1, 2, 3, 4)
    assert main_window_layout._deserialize_rect_setting("bad") is None
    assert main_window_layout._deserialize_rect_setting({"width": "bad"}) is None

    app = _settings_app(
        {
            main_window_layout._saved_main_window_layouts_setting_key(): (
                '{"Writer": {"dock": true}, "": {"ignored": true}, "Bad": []}'
            ),
            main_window_layout._workspace_panels_setting_key(): (
                '{"release": {"tab": 1}, "": {"ignored": true}, "bad": []}'
            ),
        }
    )

    assert main_window_layout._load_saved_main_window_layouts(app) == {"Writer": {"dock": True}}
    assert main_window_layout._load_workspace_panel_layouts(app) == {"release": {"tab": 1}}

    app.settings.values[main_window_layout._saved_main_window_layouts_setting_key()] = "not-json"
    app.settings.values[main_window_layout._workspace_panels_setting_key()] = []
    assert main_window_layout._load_saved_main_window_layouts(app) == {}
    assert main_window_layout._load_workspace_panel_layouts(app) == {}

    main_window_layout._write_saved_main_window_layouts(
        app,
        {"b": {"order": 2}, "A": {"order": 1}},
        sync=True,
    )
    main_window_layout._write_workspace_panel_layouts(app, {"z": {}, "a": {}}, sync=False)

    assert app.settings.synced == 1
    assert '"A"' in app.settings.values[main_window_layout._saved_main_window_layouts_setting_key()]
    assert app.settings.values[main_window_layout._workspace_panels_setting_key()].startswith(
        '{"a"'
    )


def test_saved_layout_request_preparation_validates_names_and_restores_payload_types():
    geometry = main_window_layout._serialize_qbytearray_setting(QByteArray(b"geometry"))
    dock_state = main_window_layout._serialize_qbytearray_setting(QByteArray(b"dock"))
    snapshot = {
        "geometry_b64": geometry,
        "normal_geometry": {"x": 10, "y": 20, "width": 300, "height": 200},
        "window_state": "normal",
        "dock_state_b64": dock_state,
        "workspace_panels": {"release": {"visible": True}},
        "add_data_panel": True,
        "catalog_table_panel": False,
        "profiles_toolbar_visible": False,
        CATALOG_ZOOM_LAYOUT_KEY: {"percent": 125},
        "action_ribbon": {"visible": False, "action_ids": ["save"]},
    }

    assert main_window_layout._prepare_named_main_window_layout_switch_request({}) is None
    assert (
        main_window_layout._prepare_named_main_window_layout_switch_request(
            {"layouts": [], "requested_name": "Desk"}
        )
        is None
    )
    assert (
        main_window_layout._prepare_named_main_window_layout_switch_request(
            {"layouts": {"Desk": snapshot}, "requested_name": ""}
        )
        is None
    )
    assert (
        main_window_layout._prepare_named_main_window_layout_switch_request(
            {"layouts": {"Desk": []}, "requested_name": "Desk"}
        )
        is None
    )

    prepared = main_window_layout._prepare_named_main_window_layout_switch_request(
        {
            "layouts": {"Desk": snapshot},
            "requested_name": "desk",
            "known_action_ids": ["save", "open"],
            "default_action_ids": ["open"],
            "current_action_ids": ["open"],
            "current_visible": True,
        }
    )

    assert prepared["name"] == "Desk"
    assert bytes(prepared["geometry"]) == b"geometry"
    assert prepared["normal_geometry"] == QRect(10, 20, 300, 200)
    assert bytes(prepared["dock_state"]) == b"dock"
    assert prepared["workspace_panels"] == {"release": {"visible": True}}
    assert prepared["add_data_panel"] is True
    assert prepared["catalog_table_panel"] is False
    assert prepared["profiles_toolbar_visible"] is False
    assert prepared[CATALOG_ZOOM_LAYOUT_KEY] == {"percent": 125}
    assert prepared["ribbon_action_ids"] == ["save"]
    assert prepared["ribbon_visible"] is False


def test_main_window_geometry_snapshot_handles_state_markers_and_restore_failures():
    calls: list[tuple[str, object]] = []
    app = SimpleNamespace(
        restoreGeometry=lambda geometry: calls.append(("restore", bytes(geometry))) or True,
        showFullScreen=lambda: calls.append(("fullscreen", None)),
        showMaximized=lambda: calls.append(("maximized", None)),
        showNormal=lambda: calls.append(("normal", None)),
        setGeometry=lambda rect: calls.append(("set_geometry", rect)),
        logger=SimpleNamespace(warning=lambda *args: calls.append(("warning", args))),
    )

    assert (
        main_window_layout._apply_main_window_geometry_snapshot(
            app,
            geometry=QByteArray(),
            normal_geometry=None,
            window_state_marker="unknown",
        )
        is False
    )
    assert main_window_layout._apply_main_window_geometry_snapshot(
        app,
        geometry=QByteArray(b"geom"),
        normal_geometry=None,
        window_state_marker="",
    )
    assert calls[-1] == ("restore", b"geom")

    assert main_window_layout._apply_main_window_geometry_snapshot(
        app,
        geometry=None,
        normal_geometry=None,
        window_state_marker="fullscreen",
    )
    assert calls[-1] == ("fullscreen", None)

    assert main_window_layout._apply_main_window_geometry_snapshot(
        app,
        geometry=None,
        normal_geometry=None,
        window_state_marker="maximized",
    )
    assert calls[-1] == ("maximized", None)

    normal_geometry = QRect(5, 6, 700, 500)
    assert main_window_layout._apply_main_window_geometry_snapshot(
        app,
        geometry=None,
        normal_geometry=normal_geometry,
        window_state_marker="normal",
    )
    assert ("normal", None) in calls
    assert ("set_geometry", normal_geometry) in calls

    app.restoreGeometry = lambda _geometry: (_ for _ in ()).throw(RuntimeError("bad geometry"))
    assert (
        main_window_layout._apply_main_window_geometry_snapshot(
            app,
            geometry=QByteArray(b"bad"),
            normal_geometry=None,
            window_state_marker="",
        )
        is False
    )
    assert calls[-1][0] == "warning"


def test_layout_stabilization_and_dock_state_persistence_edges():
    class Widget:
        def __init__(self):
            self.calls: list[str] = []

        def updateGeometry(self):
            self.calls.append("geometry")

        def update(self):
            self.calls.append("update")

        def repaint(self):
            self.calls.append("repaint")

    widget = Widget()
    progress: list[tuple[object, object, str]] = []
    snapshots = iter([(("first",),), (("stable",),), (("stable",),)])
    app = SimpleNamespace(
        _visible_layout_stabilization_targets=lambda: [widget],
        updateGeometry=lambda: widget.calls.append("app-geometry"),
        update=lambda: widget.calls.append("app-update"),
        repaint=lambda: widget.calls.append("app-repaint"),
        _drain_qt_events=lambda: widget.calls.append("events"),
        _geometry_snapshot_for_widgets=lambda _widgets: next(snapshots),
        logger=SimpleNamespace(warning=mock.Mock()),
    )

    assert main_window_layout._stabilize_visible_layout_after_restore(
        app,
        progress_callback=lambda *args: progress.append(args),
        value=4,
        maximum=10,
    )
    assert "stabilized" in progress[-1][2]

    stuck_app = SimpleNamespace(
        _visible_layout_stabilization_targets=lambda: [widget],
        updateGeometry=lambda: None,
        update=lambda: None,
        repaint=lambda: None,
        _drain_qt_events=lambda: None,
        _geometry_snapshot_for_widgets=mock.Mock(side_effect=[(("a",),), (("b",),)]),
        logger=SimpleNamespace(warning=mock.Mock()),
    )
    assert (
        main_window_layout._stabilize_visible_layout_after_restore(
            stuck_app,
            progress_callback=lambda *args: progress.append(args),
            stabilization_limit=2,
        )
        is False
    )
    stuck_app.logger.warning.assert_called_once()

    settings = _Settings()
    events: list[tuple[str, object]] = []
    dock_app = SimpleNamespace(
        _suspend_dock_state_sync=True,
        _capture_current_workspace_panel_layout_snapshot=mock.Mock(),
        settings=settings,
        logger=SimpleNamespace(warning=lambda *args: events.append(("warning", args))),
        _dock_state_setting_key=main_window_layout._dock_state_setting_key,
        _write_workspace_panel_layouts=lambda snapshot, sync=False: events.append(
            ("workspace", (snapshot, sync))
        ),
        saveState=lambda _version: QByteArray(b"dock"),
        restoreState=mock.Mock(return_value=False),
    )
    main_window_layout._save_main_dock_state(dock_app)
    dock_app._capture_current_workspace_panel_layout_snapshot.assert_not_called()

    dock_app._suspend_dock_state_sync = False
    dock_app._capture_current_workspace_panel_layout_snapshot.return_value = {"panel": {}}
    main_window_layout._save_main_dock_state(dock_app)
    assert settings.values[main_window_layout._dock_state_setting_key()] == QByteArray(b"dock")
    assert events[-1] == ("workspace", ({"panel": {}}, False))
    assert settings.synced == 1

    assert not main_window_layout._apply_main_dock_state_snapshot(dock_app, QByteArray())
    assert not main_window_layout._apply_main_dock_state_snapshot(
        dock_app,
        QByteArray(b"rejected"),
    )
    dock_app.restoreState.assert_called_once()
    assert dock_app._suspend_dock_state_sync is False


def test_saved_layout_apply_pipeline_uses_fallback_panels_and_restores_flags():
    events: list[tuple[str, object]] = []

    @contextmanager
    def suspended_updates():
        events.append(("suspend", True))
        yield
        events.append(("suspend", False))

    app = SimpleNamespace(
        _action_ribbon_default_ids=["default"],
        _suspend_dock_state_sync=False,
        _is_restoring_workspace_layout=False,
        _ensure_persistent_workspace_dock_shells=lambda: events.append(("ensure", None)),
        _log_contract_template_restore_checkpoint=lambda event, **payload: events.append(
            (event, payload)
        ),
        _contract_template_workspace_debug_summary=lambda: {},
        _suspend_saved_layout_transition_updates=suspended_updates,
        _apply_main_window_geometry_snapshot=lambda **kwargs: events.append(("geometry", kwargs)),
        _apply_main_dock_state_snapshot=lambda state: False,
        _apply_add_data_panel_state=lambda enabled: events.append(("add_data", enabled)),
        _apply_catalog_table_panel_state=lambda enabled: events.append(("catalog", enabled)),
        _apply_profiles_toolbar_visibility=lambda visible: events.append(("profiles", visible)),
        _apply_action_ribbon_configuration=lambda ids, visible: events.append(
            ("ribbon", (tuple(ids), visible))
        ),
        _restore_catalog_zoom_layout_state=lambda payload, immediate: events.append(
            ("zoom", (payload, immediate))
        ),
        _refresh_workspace_dock_default_placement_flags=lambda: events.append(
            ("refresh_placement", None)
        ),
        _apply_workspace_panel_layout_snapshot=lambda payload: events.append(
            ("workspace", payload)
        ),
        _materialize_visible_workspace_dock_panels=lambda progress_callback=None: (
            progress_callback(1, 1, "Restored dock") if progress_callback else None
        ),
        _store_workspace_panel_visibility_preferences=lambda sync=False: events.append(
            ("store_visibility", sync)
        ),
        _store_action_ribbon_preferences=lambda ids, visible, sync=False: events.append(
            ("store_ribbon", (tuple(ids), visible, sync))
        ),
        _refresh_saved_layout_controls=lambda: events.append(("refresh_controls", None)),
        _stabilize_visible_layout_after_restore=lambda **kwargs: events.append(
            ("stabilize", kwargs)
        ),
        _validate_visible_workspace_dock_panels_after_restore=lambda: events.append(
            ("validate", None)
        ),
        _schedule_contract_template_restore_debug_snapshots=lambda **kwargs: events.append(
            ("schedule_debug", kwargs)
        ),
        _stop_queued_main_window_layout_persistence=lambda: events.append(("stop_timers", None)),
        _schedule_main_window_geometry_save=lambda: events.append(("schedule_geometry", None)),
        _schedule_main_dock_state_save=lambda: events.append(("schedule_dock", None)),
        _apply_top_chrome_boundary=lambda: events.append(("top_chrome", None)),
        settings=SimpleNamespace(sync=lambda: events.append(("settings_sync", None))),
        _advance_task_ui_progress=lambda ui, **kwargs: ui.report_progress(**kwargs),
        _normalize_action_ribbon_ids=lambda ids: list(ids or []),
    )
    ui_progress = SimpleNamespace(
        events=[],
        report_progress=lambda **kwargs: ui_progress.events.append(kwargs),
    )
    prepared = {
        "name": "Writer Desk",
        "geometry": QByteArray(b"geometry"),
        "normal_geometry": QRect(1, 2, 300, 200),
        "window_state_marker": "normal",
        "dock_state": QByteArray(),
        "workspace_panels": {"release": {"visible": True}},
        "add_data_panel": True,
        "catalog_table_panel": False,
        "profiles_toolbar_visible": True,
        "ribbon_action_ids": [],
        "ribbon_visible": False,
        CATALOG_ZOOM_LAYOUT_KEY: {"percent": 140},
    }

    assert main_window_layout._apply_prepared_named_main_window_layout(
        app,
        prepared,
        ui_progress=ui_progress,
    )
    assert main_window_layout._apply_prepared_named_main_window_layout(app, {"name": ""}) is False
    assert app._active_saved_main_window_layout_name == "Writer Desk"
    assert app._suspend_dock_state_sync is False
    assert app._is_restoring_workspace_layout is False
    assert ("add_data", True) in events
    assert ("catalog", False) in events
    assert ("ribbon", (("default",), False)) in events
    assert ("workspace", {"release": {"visible": True}}) in events
    assert ui_progress.events[-1]["message"] == 'Saved layout "Writer Desk" is ready.'


def test_saved_layout_switch_and_interactive_add_delete_cover_noop_and_reject_paths(monkeypatch):
    app = SimpleNamespace()
    app._build_named_main_window_layout_switch_request = mock.Mock(return_value=None)
    app._refresh_saved_layout_controls = mock.Mock()

    assert main_window_layout._start_named_main_window_layout_switch(app, "Missing") is None
    app._refresh_saved_layout_controls.assert_called_once()

    task_calls: list[dict[str, object]] = []
    status_messages: list[str] = []
    prepared_payload = {"name": "Writer Desk"}

    class Context:
        def __init__(self):
            self.statuses: list[str] = []
            self.progress: list[dict[str, object]] = []

        def set_status(self, message):
            self.statuses.append(message)

        def report_progress(self, **kwargs):
            self.progress.append(kwargs)

        def raise_if_cancelled(self):
            self.progress.append({"cancel_checked": True})

    app._build_named_main_window_layout_switch_request = mock.Mock(
        return_value={"requested_name": "Writer Desk"}
    )
    app._prepare_named_main_window_layout_switch_request = mock.Mock(return_value=prepared_payload)
    app._apply_prepared_named_main_window_layout = mock.Mock(return_value=True)
    app.statusBar = lambda: SimpleNamespace(
        showMessage=lambda message, _timeout: status_messages.append(message)
    )

    def submit_background_task(**kwargs):
        task_calls.append(kwargs)
        context = Context()
        prepared = kwargs["task_fn"](context)
        kwargs["on_success_before_cleanup"](prepared, SimpleNamespace())
        kwargs["on_success_after_cleanup"](prepared)
        kwargs["on_error"](SimpleNamespace(message="unused"))
        return "task-id"

    app._show_background_task_error = mock.Mock()
    app._submit_background_task = submit_background_task

    assert (
        main_window_layout._start_named_main_window_layout_switch(app, "Writer Desk") == "task-id"
    )
    assert task_calls[0]["unique_key"] == "saved-layout-switch"
    app._apply_prepared_named_main_window_layout.assert_called_once_with(
        prepared_payload,
        ui_progress=mock.ANY,
    )
    assert status_messages[-1] == 'Switched to layout "Writer Desk".'
    app._show_background_task_error.assert_called_once()

    save_calls: list[str] = []
    app._saved_main_window_layout_names = mock.Mock(return_value=["Writer Desk"])
    app._find_saved_main_window_layout_name = mock.Mock(return_value="Writer Desk")
    app._default_saved_main_window_layout_name = mock.Mock(return_value="Layout 1")
    app._save_named_main_window_layout = lambda name: save_calls.append(name) or name
    app.statusBar = lambda: SimpleNamespace(
        showMessage=lambda message, _timeout: status_messages.append(message)
    )

    class MessageBox:
        Yes = 1
        No = 2
        answers = [No, Yes]
        warnings: list[str] = []
        infos: list[str] = []

        @classmethod
        def warning(cls, _parent, _title, message):
            cls.warnings.append(message)

        @classmethod
        def information(cls, _parent, _title, message):
            cls.infos.append(message)

        @classmethod
        def question(cls, *_args):
            return cls.answers.pop(0)

    choices = iter([("", True), ("Writer Desk", True), ("Writer Desk", True)])
    monkeypatch.setattr(main_window_layout, "_message_box", lambda _app: MessageBox)
    monkeypatch.setattr(
        main_window_layout,
        "_name_choice_dialog",
        lambda _app: lambda *_args, **_kwargs: next(choices),
    )

    main_window_layout.add_named_main_window_layout(app)
    assert save_calls == []
    assert "Enter a layout name" in MessageBox.warnings[0]

    main_window_layout.add_named_main_window_layout(app)
    assert save_calls == ["Writer Desk"]
    assert status_messages[-1] == 'Saved layout "Writer Desk".'

    app._saved_main_window_layout_names = mock.Mock(return_value=[])
    main_window_layout.delete_named_main_window_layout_interactive(app)
    assert MessageBox.infos[-1] == "No saved layouts are available yet."

    app._saved_main_window_layout_names = mock.Mock(return_value=["Writer Desk"])
    app._find_saved_main_window_layout_name = mock.Mock(return_value="Writer Desk")
    app._delete_named_main_window_layout = mock.Mock(return_value=True)
    monkeypatch.setattr(
        main_window_layout,
        "_input_dialog",
        lambda _app: SimpleNamespace(
            getItem=lambda *_args: ("Writer Desk", False),
        ),
    )
    main_window_layout.delete_named_main_window_layout_interactive(app, "Writer Desk")
    app._delete_named_main_window_layout.assert_not_called()


def test_saved_layout_snapshot_delete_menu_and_selector_paths(monkeypatch):
    _ensure_qapp()
    settings = _Settings()
    status_messages: list[str] = []
    starts: list[str] = []
    app = SimpleNamespace(
        settings=settings,
        _active_saved_main_window_layout_name="Old",
        toolbar=None,
        action_ribbon_toolbar=None,
        add_data_dock=None,
        catalog_table_dock=None,
        saved_layout_selector=QComboBox(),
        saved_layout_delete_button=QPushButton(),
        saved_layouts_menu=QMenu(),
        delete_layout_action=None,
        _action_ribbon_specs_by_id={"save": object()},
        _action_ribbon_action_ids=["save"],
        _action_ribbon_default_ids=["save"],
        _normalize_action_ribbon_ids=lambda ids: list(ids or []),
        _current_action_ribbon_visibility=lambda: True,
        statusBar=lambda: SimpleNamespace(
            showMessage=lambda message, _timeout: status_messages.append(message)
        ),
        saveGeometry=lambda: QByteArray(b"geometry"),
        saveState=lambda _version: QByteArray(b"dock"),
        normalGeometry=lambda: QRect(1, 2, 640, 480),
        _catalog_zoom_layout_state=lambda: {CATALOG_ZOOM_LAYOUT_KEY: {"percent": 125}},
        _capture_current_action_ribbon_layout_snapshot=lambda: {
            "visible": True,
            "action_ids": ["save"],
        },
        _capture_current_workspace_panel_layout_snapshot=lambda: {"release": {"visible": True}},
        _contract_template_workspace_debug_summary=lambda: {},
        _start_named_main_window_layout_switch=lambda name: starts.append(name),
    )
    app._saved_main_window_layouts_setting_key = (
        main_window_layout._saved_main_window_layouts_setting_key
    )
    app._workspace_panels_setting_key = main_window_layout._workspace_panels_setting_key
    app._load_saved_main_window_layouts = (
        lambda: main_window_layout._load_saved_main_window_layouts(app)
    )
    app._write_saved_main_window_layouts = lambda layouts: (
        main_window_layout._write_saved_main_window_layouts(app, layouts)
    )
    app._saved_main_window_layout_names = (
        lambda: main_window_layout._saved_main_window_layout_names(app)
    )
    app._find_saved_main_window_layout_name = lambda name: (
        main_window_layout._find_saved_main_window_layout_name(app, name)
    )
    app._refresh_saved_layout_controls = lambda: main_window_layout._refresh_saved_layout_controls(
        app
    )
    app._capture_current_main_window_layout_snapshot = (
        lambda: main_window_layout._capture_current_main_window_layout_snapshot(app)
    )
    app._delete_named_main_window_layout = (
        lambda name: main_window_layout._delete_named_main_window_layout(
            app,
            name,
        )
    )
    app._serialize_qbytearray_setting = main_window_layout._serialize_qbytearray_setting
    app._serialize_rect_setting = main_window_layout._serialize_rect_setting
    app._current_main_window_state_marker = lambda: "normal"

    assert main_window_layout._save_named_main_window_layout(app, "") is None
    assert main_window_layout._save_named_main_window_layout(app, "Writer Desk") == "Writer Desk"
    assert app._active_saved_main_window_layout_name == "Writer Desk"
    assert app.saved_layout_selector.isEnabled()
    assert app.saved_layout_delete_button.isEnabled()

    request = main_window_layout._build_named_main_window_layout_switch_request(app, "writer desk")
    assert request is not None
    assert request["requested_name"] == "writer desk"
    assert main_window_layout._delete_named_main_window_layout(app, "missing") is False
    assert main_window_layout._delete_named_main_window_layout(app, "writer desk")
    assert app._active_saved_main_window_layout_name == ""
    assert not app.saved_layout_selector.isEnabled()

    main_window_layout._populate_saved_layouts_menu(app)
    assert app.saved_layouts_menu.actions()[0].text() == "No Saved Layouts"
    assert not app.saved_layouts_menu.actions()[0].isEnabled()

    main_window_layout._save_named_main_window_layout(app, "Desk A")
    main_window_layout._save_named_main_window_layout(app, "Desk B")
    main_window_layout._populate_saved_layouts_menu(app)
    assert app.saved_layouts_menu.actions()

    monkeypatch.setattr(main_window_layout.QTimer, "singleShot", lambda _ms, fn: fn())
    app.saved_layout_selector.setCurrentIndex(app.saved_layout_selector.findData("Desk B"))
    main_window_layout._on_saved_layout_selected(app, app.saved_layout_selector.currentIndex())
    assert starts[-1] == "Desk B"

    class MessageBox:
        Yes = 1
        No = 2

        @classmethod
        def question(cls, *_args):
            return cls.Yes

    monkeypatch.setattr(main_window_layout, "_message_box", lambda _app: MessageBox)
    monkeypatch.setattr(
        main_window_layout,
        "_input_dialog",
        lambda _app: SimpleNamespace(
            getItem=lambda *_args: ("Desk A", True),
        ),
    )
    main_window_layout.delete_named_main_window_layout_interactive(app, "Desk A")
    assert status_messages[-1] == 'Deleted layout "Desk A".'
