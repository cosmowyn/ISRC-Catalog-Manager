from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QByteArray, QPoint, QRect, Qt
from PySide6.QtWidgets import QDockWidget, QLabel, QScrollArea, QWidget

from isrc_manager.contract_templates import dialogs as contract_dialogs
from isrc_manager.contract_templates.dialogs import (
    _clean_text,
    _deserialize_dock_state,
    _dock_area_from_value,
    _dock_area_value,
    _dock_logically_visible,
    _DockableWorkspaceTab,
    _FillHtmlPreviewController,
    _invoke_dock_floating_transition_hook,
    _layout_state_has_saved_dock_topology,
    _normalized_dock_object_names,
    _normalized_dock_visibility_map,
    _normalized_workspace_layout_state,
    _PreviewCandidate,
    _serialize_dock_state,
)
from tests.qt_test_helpers import require_qapplication


class _Dock:
    def __init__(
        self,
        name: str,
        rect: QRect,
        *,
        area=Qt.LeftDockWidgetArea,
        visible: bool = True,
        floating: bool = False,
        order: int = 0,
        allow_floating: bool = False,
    ) -> None:
        self._name = name
        self._rect = rect
        self.area = area
        self._visible = visible
        self._floating = floating
        self._properties: dict[str, object] = {
            "dockOrderHint": order,
            "workspaceAllowFloating": allow_floating,
        }
        self.show_count = 0

    def objectName(self) -> str:
        return self._name

    def geometry(self) -> QRect:
        return self._rect

    def isVisible(self) -> bool:
        return self._visible

    def isFloating(self) -> bool:
        return self._floating

    def show(self) -> None:
        self._visible = True
        self.show_count += 1

    def property(self, name: str):
        return self._properties.get(name)

    def setProperty(self, name: str, value: object) -> None:
        self._properties[name] = value


class _Host:
    def __init__(self, docks: list[_Dock] | None = None) -> None:
        self._docks = list(docks or [])
        self.add_calls: list[tuple[object, str]] = []
        self.split_calls: list[tuple[str, str, object]] = []
        self.floating_changes: list[tuple[str, bool]] = []
        self.refresh_groups = None

    def dockWidgetArea(self, dock: _Dock):
        return dock.area

    def tabifiedDockWidgets(self, dock: _Dock):
        return getattr(dock, "tabified", [])

    def menuWidget(self):
        return None

    def addDockWidget(self, area, dock: _Dock) -> None:
        self.add_calls.append((area, dock.objectName()))

    def splitDockWidget(self, first: _Dock, second: _Dock, orientation) -> None:
        self.split_calls.append((first.objectName(), second.objectName(), orientation))

    def _set_dock_floating_state(self, dock: _Dock, floating: bool) -> None:
        dock._floating = bool(floating)
        self.floating_changes.append((dock.objectName(), bool(floating)))

    def _refresh_dock_order_hints(self, groups_by_area=None) -> None:
        self.refresh_groups = groups_by_area

    def _dock_allows_floating(self, dock: _Dock) -> bool:
        return _DockableWorkspaceTab._dock_allows_floating(dock)


def _make_workspace_host(
    *,
    layout_version: int = 2,
    reset_calls: list[str] | None = None,
    layout_changes: list[str] | None = None,
) -> _DockableWorkspaceTab:
    reset_log = reset_calls if reset_calls is not None else []
    change_log = layout_changes if layout_changes is not None else []
    host = _DockableWorkspaceTab(
        tab_key="fill",
        host_object_name="contractTemplateFillHost",
        layout_version=layout_version,
        reset_handler=lambda: reset_log.append("reset"),
        layout_changed_handler=lambda: change_log.append("changed"),
    )
    host.resize(640, 420)
    host.show()
    require_qapplication().processEvents()
    return host


def _make_qdock(
    name: str,
    *,
    widget: QWidget | None = None,
    allow_floating: bool = True,
) -> QDockWidget:
    dock = QDockWidget(name)
    dock.setObjectName(name)
    dock.setProperty("workspaceAllowFloating", bool(allow_floating))
    dock.setProperty("workspaceSafeDragToFloat", bool(allow_floating))
    dock.setWidget(widget or QWidget())
    return dock


class _MouseEvent:
    def __init__(
        self,
        *,
        point: QPoint | None = None,
        button=Qt.LeftButton,
        buttons=Qt.LeftButton,
        fail_position: bool = False,
        fail_pos: bool = False,
    ) -> None:
        self._point = point or QPoint()
        self._button = button
        self._buttons = buttons
        self._fail_position = fail_position
        self._fail_pos = fail_pos
        self.accepted = False
        self.ignored = False

    def position(self):
        if self._fail_position:
            raise RuntimeError("no position")
        return self

    def toPoint(self) -> QPoint:
        return self._point

    def pos(self) -> QPoint:
        if self._fail_pos:
            raise RuntimeError("no pos")
        return self._point

    def button(self):
        return self._button

    def buttons(self):
        return self._buttons

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class _Signal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


class _PreviewView:
    def __init__(self) -> None:
        self.loadFinished = _Signal()
        self.html: list[str] = []
        self.loads: list[str] = []
        self.programmatic_reloads = 0

    def setHtml(self, html: str) -> None:
        self.html.append(html)

    def mark_programmatic_reload(self) -> None:
        self.programmatic_reloads += 1

    def load(self, url) -> None:
        self.loads.append(url.toLocalFile())


class _PreviewExportService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.pruned = False
        self.fail_materialize: Exception | None = None
        self.after_materialize = None
        self.materialized: list[dict[str, object]] = []
        self.counter = 0
        self.last_session_root: Path | None = None

    def prune_html_preview_sessions(self) -> None:
        self.pruned = True

    def create_html_preview_session_root(self) -> Path:
        self.counter += 1
        session_root = self.root / f"preview-session-{self.counter}"
        session_root.mkdir()
        self.last_session_root = session_root
        return session_root

    def materialize_html_preview_session(
        self,
        *,
        revision_id: int,
        editable_payload: dict[str, object],
        draft_id: int | None,
        session_root: Path,
    ):
        if self.fail_materialize is not None:
            raise self.fail_materialize
        html_path = session_root / "index.html"
        html_path.write_text("<html>preview</html>", encoding="utf-8")
        self.materialized.append(
            {
                "revision_id": revision_id,
                "editable_payload": dict(editable_payload),
                "draft_id": draft_id,
                "session_root": session_root,
            }
        )
        if callable(self.after_materialize):
            self.after_materialize()
        return session_root, html_path, []


class _PreviewTemplateService:
    def __init__(self, source_path: Path | None = None, *, fail: bool = False) -> None:
        self.source_path = source_path
        self.fail = fail

    def resolve_html_revision_source_path(self, revision_id: int):
        if self.fail:
            raise RuntimeError(f"missing revision {revision_id}")
        return self.source_path


class _PreviewPanel:
    def __init__(
        self,
        view: _PreviewView | None,
        export_service: _PreviewExportService | None,
        template_service: _PreviewTemplateService | None,
    ) -> None:
        self.fill_html_preview_view = view
        self.fill_preview_stale_label = QLabel("Preview stale")
        self.fill_preview_status_label = QLabel("")
        self.payload: dict[str, object] = {}
        self.loaded_draft_record = SimpleNamespace(draft_id=42)
        self.selected_draft_record = SimpleNamespace(draft_id=99)
        self.export_service = export_service
        self.template_service = template_service

    def _export_service(self):
        return self.export_service

    def _template_service(self):
        return self.template_service

    def current_fill_state(self):
        return dict(self.payload)

    def _loaded_draft_record(self):
        return self.loaded_draft_record

    def _selected_fill_draft_record(self):
        return self.selected_draft_record


def test_layout_state_normalization_serialization_and_dock_hook_edges() -> None:
    require_qapplication()

    assert _clean_text("  Contract  ") == "Contract"
    assert _clean_text("  ") is None
    assert _serialize_dock_state(None) == ""
    state_bytes = QByteArray(b"dock-state")
    encoded = _serialize_dock_state(state_bytes)
    assert encoded
    assert bytes(_deserialize_dock_state(encoded)) == bytes(state_bytes)
    assert _deserialize_dock_state(None) is None
    assert _deserialize_dock_state("  ") is None
    assert _deserialize_dock_state("not ascii \u2603") is None

    class BrokenState:
        def isEmpty(self) -> bool:
            return False

        def toBase64(self):
            raise RuntimeError("cannot serialize")

    assert _serialize_dock_state(BrokenState()) == ""

    class BrokenArea:
        @property
        def value(self):
            raise RuntimeError("bad area")

    assert _dock_area_value(BrokenArea()) == 0
    assert _dock_area_from_value(_dock_area_value(Qt.LeftDockWidgetArea)) == Qt.LeftDockWidgetArea
    assert _dock_area_from_value(999_999) == Qt.NoDockWidgetArea

    assert _normalized_dock_object_names(["left", "", None, 3]) == ["left", "None", "3"]
    assert _normalized_dock_visibility_map(
        {"left": True, "right": 0, "missing": True, "": True},
        ["left", "right"],
    ) == {"left": True, "right": False}
    assert _layout_state_has_saved_dock_topology(None) is False
    assert _layout_state_has_saved_dock_topology({"dock_state_b64": " abc "}) is True
    assert _layout_state_has_saved_dock_topology({"dock_object_names": ["left"]}) is True

    normalized = _normalized_workspace_layout_state(
        {
            "dock_state_b64": "state",
            "layout_locked": False,
            "layout_version": "2",
            "dock_object_names": ["left", "right"],
            "dock_visibility": {"left": True, "orphan": True},
        }
    )
    assert normalized == {
        "dock_state_b64": "state",
        "layout_locked": False,
        "layout_version": 2,
        "dock_object_names": ["left", "right"],
        "dock_visibility": {"left": True},
    }

    assert _dock_logically_visible(object()) is False

    class FallbackDock(QDockWidget):
        def isHidden(self):
            raise RuntimeError("hidden state unavailable")

        def isVisible(self):
            return True

    class HookDock(QDockWidget):
        def __init__(self):
            super().__init__()
            self.calls: list[bool] = []

        def prepare(self, floating: bool) -> None:
            self.calls.append(bool(floating))

        def broken(self, _floating: bool) -> None:
            raise RuntimeError("ignored")

    fallback = FallbackDock()
    hook_dock = HookDock()
    try:
        assert _dock_logically_visible(fallback) is True
        _invoke_dock_floating_transition_hook(object(), "prepare", True)
        _invoke_dock_floating_transition_hook(hook_dock, "missing", True)
        _invoke_dock_floating_transition_hook(hook_dock, "prepare", True)
        _invoke_dock_floating_transition_hook(hook_dock, "broken", False)
        assert hook_dock.calls == [True]
    finally:
        fallback.deleteLater()
        hook_dock.deleteLater()


def test_ordered_visible_area_groups_sorts_groups_and_ignores_tabified_or_hidden_docks() -> None:
    first = _Dock("first", QRect(10, 40, 50, 50), order=2)
    second = _Dock("second", QRect(0, 5, 50, 50), order=1)
    third = _Dock("third", QRect(120, 20, 50, 50), order=3)
    hidden = _Dock("hidden", QRect(0, 0, 50, 50), visible=False)
    floating = _Dock("floating", QRect(0, 0, 50, 50), floating=True)
    other_area = _Dock("top", QRect(0, 0, 50, 50), area=Qt.TopDockWidgetArea)
    host = _Host([first, second, third, hidden, floating, other_area])

    groups = _DockableWorkspaceTab._ordered_visible_area_groups(host, Qt.LeftDockWidgetArea)
    assert [[dock.objectName() for dock in group] for group in groups] == [
        ["second", "first"],
        ["third"],
    ]

    first.tabified = [second]
    assert _DockableWorkspaceTab._ordered_visible_area_groups(host, Qt.LeftDockWidgetArea) == []
    assert (
        _DockableWorkspaceTab._ordered_visible_area_groups(_Host([]), Qt.LeftDockWidgetArea) == []
    )


def test_area_gap_detection_catches_secondary_and_between_group_spacing() -> None:
    host = _Host()
    compact = [
        [_Dock("a", QRect(0, 0, 50, 50)), _Dock("b", QRect(0, 50, 50, 50))],
        [_Dock("c", QRect(51, 0, 50, 50))],
    ]
    assert _DockableWorkspaceTab._area_has_gaps(host, Qt.LeftDockWidgetArea, []) is False
    assert _DockableWorkspaceTab._area_has_gaps(host, Qt.LeftDockWidgetArea, compact) is False

    secondary_gap = [[_Dock("a", QRect(0, 30, 50, 50))]]
    assert (
        _DockableWorkspaceTab._area_has_gaps(
            host,
            Qt.LeftDockWidgetArea,
            secondary_gap,
        )
        is True
    )

    within_group_gap = [[_Dock("a", QRect(0, 0, 50, 50)), _Dock("b", QRect(0, 90, 50, 50))]]
    assert (
        _DockableWorkspaceTab._area_has_gaps(
            host,
            Qt.LeftDockWidgetArea,
            within_group_gap,
        )
        is True
    )

    between_group_gap = [
        [_Dock("a", QRect(0, 0, 50, 50))],
        [_Dock("b", QRect(100, 0, 50, 50))],
    ]
    assert (
        _DockableWorkspaceTab._area_has_gaps(
            host,
            Qt.LeftDockWidgetArea,
            between_group_gap,
        )
        is True
    )

    vertical_groups = [
        [_Dock("a", QRect(0, 0, 50, 50), area=Qt.TopDockWidgetArea)],
        [_Dock("b", QRect(0, 51, 50, 50), area=Qt.TopDockWidgetArea)],
    ]
    assert (
        _DockableWorkspaceTab._area_has_gaps(host, Qt.TopDockWidgetArea, vertical_groups) is False
    )


def test_rebuild_area_groups_shows_docks_unfloats_and_splits_in_expected_directions() -> None:
    first = _Dock("first", QRect(0, 0, 50, 50))
    second = _Dock("second", QRect(0, 60, 50, 50), floating=True)
    third = _Dock("third", QRect(80, 0, 50, 50))
    groups = [[first, second], [third]]
    host = _Host([first, second, third])

    _DockableWorkspaceTab._rebuild_area_groups(host, Qt.LeftDockWidgetArea, groups)
    assert [dock.show_count for dock in (first, second, third)] == [1, 1, 1]
    assert host.floating_changes == [("second", False)]
    assert host.add_calls == [(Qt.LeftDockWidgetArea, "first")]
    assert host.split_calls == [
        ("first", "second", Qt.Vertical),
        ("first", "third", Qt.Horizontal),
    ]
    assert host.refresh_groups == groups

    top_host = _Host()
    _DockableWorkspaceTab._rebuild_area_groups(
        top_host,
        Qt.TopDockWidgetArea,
        [[_Dock("top-a", QRect(0, 0, 50, 50)), _Dock("top-b", QRect(60, 0, 50, 50))]],
    )
    assert top_host.split_calls == [("top-a", "top-b", Qt.Horizontal)]


def test_dock_feature_helpers_and_refresh_order_hints_update_expected_properties() -> None:
    movable = _Dock("movable", QRect(0, 0, 50, 50), allow_floating=True)
    fixed = _Dock("fixed", QRect(0, 0, 50, 50), allow_floating=False)
    host = _Host([movable, fixed])

    assert _DockableWorkspaceTab._dock_allows_floating(movable) is True
    assert _DockableWorkspaceTab._dock_allows_floating(fixed) is False
    movable_features = _DockableWorkspaceTab._unlocked_features_for_dock(host, movable)
    fixed_features = _DockableWorkspaceTab._unlocked_features_for_dock(host, fixed)
    assert movable_features & QDockWidget.DockWidgetFloatable
    assert not (fixed_features & QDockWidget.DockWidgetFloatable)

    _DockableWorkspaceTab._refresh_dock_order_hints(
        host,
        {
            Qt.LeftDockWidgetArea: [[fixed], [movable]],
            Qt.RightDockWidgetArea: [],
            Qt.TopDockWidgetArea: [],
            Qt.BottomDockWidgetArea: [],
        },
    )
    assert fixed.property("dockOrderHint") == 0
    assert movable.property("dockOrderHint") == 1


def test_workspace_host_normalization_capture_lock_and_pending_state_paths() -> None:
    require_qapplication()
    reset_calls: list[str] = []
    layout_changes: list[str] = []
    host = _make_workspace_host(reset_calls=reset_calls, layout_changes=layout_changes)
    left = _make_qdock("leftPanel", allow_floating=True)
    right = _make_qdock("rightPanel", allow_floating=False)
    try:
        host.addDockWidget(Qt.LeftDockWidgetArea, left)
        host.addDockWidget(Qt.RightDockWidgetArea, right)
        host.register_docks([left, right])

        assert host.panels_action_for_dock(left) is left.toggleViewAction()
        assert host.panels_action_for_dock(_make_qdock("unknown")) is None
        assert host.has_compatible_pending_state() is False

        host.set_layout_normalizer(None)
        host.schedule_layout_normalization()
        assert host._layout_normalization_pending is False
        host.set_layout_normalizer(lambda: None)
        assert host.apply_layout_normalization_if_ready() is False

        normalized: list[str] = []
        host.set_layout_normalizer(lambda: normalized.append("ran"))
        host._layout_normalization_pending = True
        assert host.apply_layout_normalization_if_ready() is True
        assert normalized == ["ran"]
        assert host._layout_normalization_pending is False
        assert host._stable_layout_state

        host.set_layout_normalizer(lambda: (_ for _ in ()).throw(RuntimeError("layout failed")))
        host._layout_normalization_pending = True
        assert host.apply_layout_normalization_if_ready() is False
        assert host._layout_normalization_pending is True

        host._pending_state = {
            "layout_version": 0,
            "dock_object_names": ["leftPanel", "rightPanel"],
        }
        assert host.has_compatible_pending_state() is False
        host._pending_state = {
            "layout_version": 3,
            "dock_object_names": ["leftPanel", "rightPanel"],
        }
        assert host.has_compatible_pending_state() is False
        host._pending_state = {
            "layout_version": 2,
            "dock_object_names": ["rightPanel", "leftPanel"],
        }
        assert host.has_compatible_pending_state() is False
        host._pending_state = {
            "layout_version": 2,
            "dock_object_names": ["leftPanel", "rightPanel"],
            "layout_locked": False,
        }
        assert host.has_compatible_pending_state() is True

        host.hide()
        pending_capture = host.capture_layout_state()
        assert pending_capture["dock_object_names"] == ["leftPanel", "rightPanel"]
        host._pending_state = None
        host._stable_layout_state = {
            "layout_version": 2,
            "dock_object_names": ["stable"],
            "dock_visibility": {"stable": True},
        }
        stable_capture = host.capture_layout_state()
        assert stable_capture["dock_object_names"] == ["stable"]
        host._stable_layout_state = None
        topology_capture = host.capture_layout_state()
        assert topology_capture["dock_object_names"] == ["leftPanel", "rightPanel"]

        host.show()
        host.reset_to_default_layout()
        assert reset_calls[-1] == "reset"
        assert host._locked is True
        host.set_locked(False)
        assert layout_changes[-1] == "changed"
        assert host.lock_layout_button.text() == "Lock Layout"
        assert left.features() & QDockWidget.DockWidgetFloatable
        assert not (right.features() & QDockWidget.DockWidgetFloatable)
        host._toggle_locked_state()
        assert host._locked is True
    finally:
        host.close()
        host.deleteLater()


def test_workspace_host_repair_visibility_integrity_and_command_paths(monkeypatch) -> None:
    require_qapplication()
    reset_calls: list[str] = []
    layout_changes: list[str] = []
    host = _make_workspace_host(reset_calls=reset_calls, layout_changes=layout_changes)
    content = QWidget()
    content.resize(4, 4)
    content.hide()
    scroll = QScrollArea()
    scroll.setWidget(content)
    scroll.setWidgetResizable(False)
    scroll_dock = _make_qdock("scrollPanel", widget=scroll, allow_floating=True)
    command_dock = _make_qdock("commandPanel", allow_floating=True)
    try:
        host.addDockWidget(Qt.LeftDockWidgetArea, scroll_dock)
        host.addDockWidget(Qt.RightDockWidgetArea, command_dock)
        host.register_docks([scroll_dock, command_dock])
        require_qapplication().processEvents()

        assert host._visible_scroll_area_contents_ready() is False
        assert host._repair_visible_scroll_area_contents() is True
        assert content.isVisible() is True
        content.resize(80, 80)
        assert host._visible_scroll_area_contents_ready() is True

        host.panels_menu.clear()
        host._ensure_panels_menu_matches_live_docks()
        assert set(host.panels_menu.actions()) >= {
            scroll_dock.toggleViewAction(),
            command_dock.toggleViewAction(),
        }

        assert host._dock_is_recoverably_registered(_make_qdock("unknown")) is False
        command_dock.setFloating(True)
        assert host._dock_is_recoverably_registered(command_dock) is True
        command_dock.setFloating(False)
        host.removeDockWidget(command_dock)
        assert host._dock_is_recoverably_registered(command_dock) is False
        host._restore_saved_dock_visibility({"scrollPanel": True, "commandPanel": False})
        assert scroll_dock.isVisible() is True
        assert command_dock.isHidden() is True

        orphan = _make_qdock("orphanPanel")
        host._docks = [orphan]
        host._locked = False
        host._layout_normalization_pending = True
        repair_calls: list[str] = []
        monkeypatch.setattr(host, "apply_layout_normalization_if_ready", lambda **_kw: False)
        monkeypatch.setattr(host, "_repair_visible_scroll_area_contents", lambda: False)
        monkeypatch.setattr(host, "_layout_integrity_ok", lambda: False)
        monkeypatch.setattr(host, "_dock_is_recoverably_registered", lambda _dock: False)
        monkeypatch.setattr(
            host,
            "_restore_saved_dock_visibility",
            lambda snapshot: repair_calls.append(f"visibility:{sorted(snapshot.items())}"),
        )
        host._repair_unrecoverable_restore_state({"orphanPanel": True})
        assert orphan.property("lastDockArea") == _dock_area_value(Qt.LeftDockWidgetArea)
        assert reset_calls[-1] == "reset"
        assert repair_calls

        host._docks = [scroll_dock, command_dock]
        host.addDockWidget(Qt.LeftDockWidgetArea, scroll_dock)
        host.addDockWidget(Qt.RightDockWidgetArea, command_dock)
        host._locked = True
        host.move_dock_to_area(scroll_dock, Qt.BottomDockWidgetArea)
        assert host.dockWidgetArea(scroll_dock) == Qt.LeftDockWidgetArea
        host.float_dock(command_dock)
        assert command_dock.isFloating() is False
        host.hide_dock(scroll_dock)
        assert scroll_dock.isVisible() is True

        queued: list[str] = []
        notified: list[str] = []
        monkeypatch.setattr(host, "_queue_layout_compaction", lambda: queued.append("queue"))
        monkeypatch.setattr(host, "_notify_layout_changed", lambda: notified.append("notify"))
        host._locked = False
        command_dock.setFloating(True)
        host.move_dock_to_area(command_dock, Qt.BottomDockWidgetArea)
        assert command_dock.isFloating() is False
        assert command_dock.property("lastDockArea") == _dock_area_value(Qt.BottomDockWidgetArea)
        host.float_dock(command_dock)
        assert command_dock.isFloating() is True
        host.hide_dock(scroll_dock)
        assert scroll_dock.isHidden() is True
        assert queued
        assert notified
    finally:
        host.close()
        host.deleteLater()


def test_workspace_host_layout_events_compaction_and_title_bar_edges(monkeypatch) -> None:
    require_qapplication()
    host = _make_workspace_host()
    dock = _make_qdock("eventPanel", allow_floating=True)
    try:
        host.addDockWidget(Qt.LeftDockWidgetArea, dock)
        host.register_docks([dock])
        title_bar = dock.titleBarWidget()
        assert title_bar is not None

        host._locked = True
        title_bar._refresh_menu_state()
        assert title_bar._move_left_action.isEnabled() is False
        host._locked = False
        title_bar._refresh_menu_state()
        assert title_bar._move_left_action.isEnabled() is True
        assert title_bar._float_action.isEnabled() is True

        assert title_bar._event_pos(_MouseEvent(point=QPoint(3, 4))) == QPoint(3, 4)
        assert title_bar._event_pos(_MouseEvent(point=QPoint(5, 6), fail_position=True)) == QPoint(
            5,
            6,
        )
        assert title_bar._event_pos(_MouseEvent(fail_position=True, fail_pos=True)) == QPoint()
        assert title_bar._safe_drag_to_float_enabled() is True

        floats: list[str] = []
        monkeypatch.setattr(host, "float_dock", lambda target: floats.append(target.objectName()))
        press = _MouseEvent(point=QPoint(0, 0))
        title_bar.mousePressEvent(press)
        assert press.accepted is True
        move = _MouseEvent(point=QPoint(QApplication_start_drag_distance() + 2, 0))
        title_bar.mouseMoveEvent(move)
        assert move.accepted is True
        assert floats == ["eventPanel"]
        release = _MouseEvent()
        title_bar.mouseReleaseEvent(release)
        assert release.ignored is True
        double = _MouseEvent()
        title_bar.mouseDoubleClickEvent(double)
        assert double.ignored is True

        title_bar._drag_start_pos = QPoint(0, 0)
        no_button_move = _MouseEvent(point=QPoint(100, 0), buttons=Qt.NoButton)
        title_bar.mouseMoveEvent(no_button_move)
        assert no_button_move.ignored is True
        idle_move = _MouseEvent()
        title_bar.mouseMoveEvent(idle_move)
        assert idle_move.ignored is True

        menu_exec_calls: list[QPoint] = []
        monkeypatch.setattr(
            title_bar.options_menu, "exec", lambda point: menu_exec_calls.append(point)
        )
        title_bar._show_context_menu(QPoint(1, 2))
        assert menu_exec_calls

        queued: list[str] = []
        notified: list[str] = []
        refreshed: list[str] = []
        monkeypatch.setattr(host, "_queue_layout_compaction", lambda: queued.append("queue"))
        monkeypatch.setattr(host, "_notify_layout_changed", lambda: notified.append("notify"))
        monkeypatch.setattr(
            host, "_refresh_dock_order_hints", lambda *args: refreshed.append("refresh")
        )

        host._applying_layout_normalization = True
        host._on_dock_layout_event(dock)
        assert queued == []
        host._applying_layout_normalization = False
        host._compacting_layout = True
        host._on_dock_layout_event(dock)
        assert queued == []
        host._compacting_layout = False
        host._on_dock_layout_event(dock)
        assert queued == ["queue"]
        assert notified == ["notify"]
        assert refreshed == ["refresh"]

        compacted_areas: list[object] = []
        monkeypatch.setattr(host, "_compact_area", lambda area: compacted_areas.append(area))
        host._applying_layout_state = True
        host._compact_empty_dock_space()
        assert compacted_areas == []
        host._applying_layout_state = False
        host._compacting_layout = True
        host._compact_empty_dock_space()
        assert compacted_areas == []
        host._compacting_layout = False
        host._compact_empty_dock_space()
        assert compacted_areas == [
            Qt.LeftDockWidgetArea,
            Qt.RightDockWidgetArea,
            Qt.TopDockWidgetArea,
            Qt.BottomDockWidgetArea,
        ]

        rebuilt: list[tuple[object, list[list[QDockWidget]]]] = []
        monkeypatch.setattr(host, "_ordered_visible_area_groups", lambda _area: [])
        _DockableWorkspaceTab._compact_area(host, Qt.LeftDockWidgetArea)
        monkeypatch.setattr(host, "_ordered_visible_area_groups", lambda _area: [[dock]])
        monkeypatch.setattr(host, "_area_has_gaps", lambda _area, _groups: False)
        _DockableWorkspaceTab._compact_area(host, Qt.LeftDockWidgetArea)
        monkeypatch.setattr(host, "_area_has_gaps", lambda _area, _groups: True)
        monkeypatch.setattr(
            host,
            "_rebuild_area_groups",
            lambda area, groups: rebuilt.append((area, groups)),
        )
        _DockableWorkspaceTab._compact_area(host, Qt.LeftDockWidgetArea)
        assert rebuilt == [(Qt.LeftDockWidgetArea, [[dock]])]
    finally:
        host.close()
        host.deleteLater()


def test_fill_html_preview_controller_handles_stale_cleanup_failures_and_refresh_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    require_qapplication()
    monkeypatch.setattr(contract_dialogs, "QWebEngineView", object())
    source_path = tmp_path / "revision.html"
    source_path.write_text("<html>source</html>", encoding="utf-8")
    view = _PreviewView()
    export_service = _PreviewExportService(tmp_path)
    template_service = _PreviewTemplateService(source_path)
    panel = _PreviewPanel(view, export_service, template_service)
    controller = _FillHtmlPreviewController(panel)
    try:
        assert view.loadFinished.callbacks == [controller._on_view_load_finished]
        controller.initialize()
        assert export_service.pruned is True

        controller.set_revision_context("12")
        assert controller._current_revision_id == 12
        controller.mark_stale("Preview out of date")
        assert panel.fill_preview_stale_label.isVisible() is True
        assert panel.fill_preview_stale_label.text() == "Preview out of date"
        assert panel.fill_preview_status_label.text() == "Preview out of date"

        pending_root = tmp_path / "pending-tree"
        pending_root.mkdir()
        active_root = tmp_path / "active-tree"
        active_root.mkdir()
        controller._pending_candidate = _PreviewCandidate(
            generation=1,
            root_path=pending_root,
            html_path=pending_root / "index.html",
        )
        controller._active_tree = active_root
        controller.clear()
        assert view.html[-1] == ""
        assert pending_root.exists() is False
        assert active_root.exists() is False
        assert panel.fill_preview_stale_label.isVisible() is False
        assert "HTML preview becomes available" in panel.fill_preview_status_label.text()

        request_key = controller._request_key_for(12, {"bad": object()})
        assert request_key[0] == 12
        assert "object" in request_key[1]

        original_stat = contract_dialogs.Path.stat

        def failing_stat(path: Path, *args, **kwargs):
            if path == source_path:
                raise OSError("stat unavailable")
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(contract_dialogs.Path, "stat", failing_stat)
        assert str(source_path) in controller._runtime_preview_key(12)
        panel.template_service = _PreviewTemplateService(fail=True)
        assert "source=" in controller._runtime_preview_key(12)
        monkeypatch.setattr(contract_dialogs.Path, "stat", original_stat)
        panel.template_service = template_service

        panel.fill_html_preview_view = None
        latest_generation = controller._latest_generation
        controller.request_refresh(reason="no view", delay_ms=0)
        assert controller._latest_generation == latest_generation

        panel.fill_html_preview_view = view
        controller.set_revision_context(None)
        controller.request_refresh(reason="no revision", delay_ms=0)
        assert controller._latest_generation == latest_generation

        controller.set_revision_context(12)
        panel.payload = {"artist": "Ada"}
        controller.request_refresh(reason="initial", delay_ms=0)
        assert controller._latest_generation == latest_generation + 1
        controller._start_refresh_if_idle()
        controller._refresh_timer.stop()
        assert export_service.materialized[-1]["revision_id"] == 12
        assert export_service.materialized[-1]["editable_payload"] == {"artist": "Ada"}
        assert export_service.materialized[-1]["draft_id"] == 42
        assert view.programmatic_reloads == 1
        assert view.loads[-1].endswith("index.html")

        controller._on_view_load_finished(False)
        controller._refresh_timer.stop()
        assert controller._pending_candidate is None
        assert "Unable to load" in panel.fill_preview_status_label.text()

        export_service.fail_materialize = RuntimeError("render failed")
        controller.request_refresh(reason="failure", delay_ms=0)
        controller._start_refresh_if_idle()
        controller._refresh_timer.stop()
        assert "render failed" in panel.fill_preview_status_label.text()
        export_service.fail_materialize = None

        stale_pending_root = tmp_path / "stale-pending"
        stale_pending_root.mkdir()
        controller._pending_candidate = _PreviewCandidate(
            generation=controller._latest_generation,
            root_path=stale_pending_root,
            html_path=stale_pending_root / "index.html",
        )
        controller.request_refresh(reason="replace pending", delay_ms=0)
        controller._start_refresh_if_idle()
        controller._refresh_timer.stop()
        assert stale_pending_root.exists() is False
        old_active_root = tmp_path / "old-active"
        old_active_root.mkdir()
        controller._active_tree = old_active_root
        controller._on_view_load_finished(True)
        assert controller._active_tree is not None
        assert controller._active_tree.exists() is True
        assert old_active_root.exists() is False
        assert panel.fill_preview_stale_label.isVisible() is False

        race_root: Path | None = None

        def advance_generation() -> None:
            nonlocal race_root
            race_root = export_service.last_session_root
            controller._latest_generation += 1

        export_service.after_materialize = advance_generation
        controller.request_refresh(reason="race", delay_ms=0)
        controller._start_refresh_if_idle()
        controller._refresh_timer.stop()
        assert race_root is not None
        assert race_root.exists() is False
        export_service.after_materialize = None

        controller._on_view_load_finished(True)
        assert panel.fill_preview_status_label.text()

        _FillHtmlPreviewController._delete_tree(None)
        monkeypatch.setattr(
            contract_dialogs.shutil,
            "rmtree",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("delete failed")),
        )
        _FillHtmlPreviewController._delete_tree(tmp_path / "missing-ok")
    finally:
        controller.deleteLater()


def QApplication_start_drag_distance() -> int:
    return max(1, require_qapplication().startDragDistance())
