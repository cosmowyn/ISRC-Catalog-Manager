"""Pure zoom-state controller for the staged catalog-table migration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

if TYPE_CHECKING:
    from PySide6.QtWidgets import QAbstractItemView

CATALOG_ZOOM_DEFAULT_PERCENT = 100
CATALOG_ZOOM_MIN_PERCENT = 25
CATALOG_ZOOM_MAX_PERCENT = 300
CATALOG_ZOOM_STEP_PERCENT = 1
CATALOG_ZOOM_LAYOUT_KEY = "catalog_zoom_percent"


class CatalogZoomController(QObject):
    """Manage pure zoom state, throttled apply, and layout persistence seams."""

    zoom_percent_changed = Signal(int)
    zoom_applied = Signal(int)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        throttle_ms: int = 16,
    ) -> None:
        super().__init__(parent)
        self._view: QAbstractItemView | None = None
        self._zoom_percent = CATALOG_ZOOM_DEFAULT_PERCENT
        self._pending_zoom_percent: int | None = None
        self._apply_callback: Callable[[QAbstractItemView | None, int], None] | None = None
        self._throttle_ms = max(0, int(throttle_ms))
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._apply_pending_zoom)

    def bind_view(
        self,
        view: "QAbstractItemView | None",
        *,
        apply_callback: Callable[[QAbstractItemView | None, int], None] | None = None,
    ) -> None:
        self._view = view
        if apply_callback is not None:
            self._apply_callback = apply_callback

    def set_apply_callback(
        self,
        apply_callback: Callable[[QAbstractItemView | None, int], None] | None,
    ) -> None:
        self._apply_callback = apply_callback

    def zoom_percent(self) -> int:
        return self._zoom_percent

    def pending_zoom_percent(self) -> int | None:
        return self._pending_zoom_percent

    def has_pending_apply(self) -> bool:
        return self._pending_zoom_percent is not None

    def throttle_ms(self) -> int:
        return self._throttle_ms

    def set_throttle_ms(self, throttle_ms: int) -> None:
        self._throttle_ms = max(0, int(throttle_ms))
        if self._pending_zoom_percent is not None:
            if self._throttle_ms == 0:
                self.flush_pending_apply()
            else:
                self._apply_timer.start(self._throttle_ms)

    def set_zoom_percent(
        self,
        zoom_percent: int,
        *,
        immediate: bool = False,
        snap_to_step: bool = True,
    ) -> int:
        if snap_to_step:
            normalized_zoom_percent = self.normalize_zoom_percent(zoom_percent)
        else:
            normalized_zoom_percent = self.clamp_zoom_percent(zoom_percent)
        changed = normalized_zoom_percent != self._zoom_percent
        self._zoom_percent = normalized_zoom_percent
        self._pending_zoom_percent = normalized_zoom_percent
        if changed:
            self.zoom_percent_changed.emit(normalized_zoom_percent)
        if immediate or self._throttle_ms == 0:
            self.flush_pending_apply()
        else:
            self._apply_timer.start(self._throttle_ms)
        return normalized_zoom_percent

    def step_zoom(self, steps: int, *, immediate: bool = False) -> int:
        return self.set_zoom_percent(
            self._zoom_percent + (int(steps) * CATALOG_ZOOM_STEP_PERCENT),
            immediate=immediate,
        )

    def apply_pinch_scale(self, scale_factor: float, *, immediate: bool = False) -> int:
        try:
            factor = float(scale_factor)
        except (TypeError, ValueError):
            factor = 1.0
        if factor <= 0:
            factor = 1.0
        return self.set_zoom_percent(
            int(round(self._zoom_percent * factor)),
            immediate=immediate,
            snap_to_step=False,
        )

    def reset_zoom(self, *, immediate: bool = False) -> int:
        return self.set_zoom_percent(CATALOG_ZOOM_DEFAULT_PERCENT, immediate=immediate)

    def flush_pending_apply(self) -> int:
        self._apply_timer.stop()
        if self._pending_zoom_percent is None:
            return self._zoom_percent
        self._apply_pending_zoom()
        return self._zoom_percent

    def layout_state(self) -> dict[str, int]:
        return {CATALOG_ZOOM_LAYOUT_KEY: int(self._zoom_percent)}

    def restore_layout_state(
        self,
        payload: Mapping[str, object] | None,
        *,
        immediate: bool = False,
        reset_on_profile_change: bool = False,
    ) -> int:
        if reset_on_profile_change:
            return self.reset_zoom(immediate=immediate)
        if payload is None:
            return self._zoom_percent
        try:
            zoom_percent = int(payload.get(CATALOG_ZOOM_LAYOUT_KEY, self._zoom_percent))
        except (TypeError, ValueError):
            zoom_percent = self._zoom_percent
        return self.set_zoom_percent(
            zoom_percent,
            immediate=immediate,
        )

    def on_profile_changed(self, *, immediate: bool = False) -> int:
        return self.reset_zoom(immediate=immediate)

    @staticmethod
    def clamp_zoom_percent(zoom_percent: int) -> int:
        try:
            numeric_zoom_percent = int(round(float(zoom_percent)))
        except (TypeError, ValueError):
            numeric_zoom_percent = CATALOG_ZOOM_DEFAULT_PERCENT
        return max(
            CATALOG_ZOOM_MIN_PERCENT,
            min(CATALOG_ZOOM_MAX_PERCENT, numeric_zoom_percent),
        )

    @staticmethod
    def normalize_zoom_percent(zoom_percent: int) -> int:
        clamped_zoom_percent = CatalogZoomController.clamp_zoom_percent(zoom_percent)
        step_offset = clamped_zoom_percent - CATALOG_ZOOM_MIN_PERCENT
        step_count = int(round(step_offset / CATALOG_ZOOM_STEP_PERCENT))
        return CATALOG_ZOOM_MIN_PERCENT + (step_count * CATALOG_ZOOM_STEP_PERCENT)

    def _apply_pending_zoom(self) -> None:
        if self._pending_zoom_percent is None:
            return
        zoom_percent = int(self._pending_zoom_percent)
        self._pending_zoom_percent = None
        if self._apply_callback is not None:
            self._apply_callback(self._view, zoom_percent)
        self.zoom_applied.emit(zoom_percent)


__all__ = [
    "CATALOG_ZOOM_DEFAULT_PERCENT",
    "CATALOG_ZOOM_LAYOUT_KEY",
    "CATALOG_ZOOM_MAX_PERCENT",
    "CATALOG_ZOOM_MIN_PERCENT",
    "CATALOG_ZOOM_STEP_PERCENT",
    "CatalogZoomController",
]
