"""Theme, theme-library, and visual settings orchestration."""

from __future__ import annotations

import json

from PySide6.QtCore import QEventLoop
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMenuBar, QWidget

from isrc_manager.blob_icons import (
    default_blob_icon_settings,
    normalize_blob_icon_settings,
)
from isrc_manager.qss_autocomplete import validate_qss_document
from isrc_manager.starter_themes import starter_theme_library, starter_theme_names
from isrc_manager.tasks import TaskFailure
from isrc_manager.theme_builder import (
    build_theme_palette as build_app_theme_palette,
)
from isrc_manager.theme_builder import (
    build_theme_style as build_app_theme_style,
)
from isrc_manager.theme_builder import (
    build_theme_stylesheet as build_app_theme_stylesheet,
)
from isrc_manager.theme_builder import (
    color_relative_luminance as theme_color_relative_luminance,
)
from isrc_manager.theme_builder import (
    contrast_ratio as theme_contrast_ratio,
)
from isrc_manager.theme_builder import (
    effective_theme_settings as build_effective_theme_settings,
)
from isrc_manager.theme_builder import (
    normalize_theme_color as normalize_app_theme_color,
)
from isrc_manager.theme_builder import (
    normalize_theme_font_family as normalize_app_theme_font_family,
)
from isrc_manager.theme_builder import (
    normalize_theme_settings as normalize_app_theme_settings,
)
from isrc_manager.theme_builder import (
    normalize_theme_string as normalize_app_theme_string,
)
from isrc_manager.theme_builder import (
    pick_contrasting_color as pick_theme_contrasting_color,
)
from isrc_manager.theme_builder import (
    shift_color as shift_theme_color,
)
from isrc_manager.theme_builder import (
    theme_setting_defaults as default_theme_settings,
)
from isrc_manager.theme_builder import (
    theme_setting_keys as app_theme_setting_keys,
)


def _theme_setting_defaults() -> dict[str, object]:
    return default_theme_settings()


def _theme_setting_keys() -> tuple[str, ...]:
    return app_theme_setting_keys()


def _normalize_theme_string(value) -> str:
    return normalize_app_theme_string(value)


def _format_theme_qss_issues(issues: list) -> str:
    if not issues:
        return ""
    first_issue = issues[0]
    return f"Line {first_issue.line}, column {first_issue.column}: {first_issue.message}"


def _normalize_theme_font_family(value, fallback) -> str:
    return normalize_app_theme_font_family(value, fallback)


def _normalize_theme_color(value) -> str:
    return normalize_app_theme_color(value)


def _load_theme_settings(app) -> dict[str, object]:
    defaults = app._theme_setting_defaults()
    loaded: dict[str, object] = {}
    for key, default in defaults.items():
        settings_key = f"theme/{key}"
        if isinstance(default, bool):
            loaded[key] = app.settings.value(settings_key, default, bool)
        elif isinstance(default, int):
            loaded[key] = int(app.settings.value(settings_key, default, int))
        else:
            loaded[key] = (
                app.settings.value(settings_key, default, str)
                if app.settings.contains(settings_key)
                else default
            )
    return app._normalize_theme_settings(loaded)


def _normalize_theme_settings(app, values: dict[str, object] | None) -> dict[str, object]:
    return normalize_app_theme_settings(values)


def _stored_theme_payload(app, values: dict[str, object] | None) -> dict[str, object]:
    payload = app._normalize_theme_settings(values)
    payload["selected_name"] = ""
    return payload


def _sanitize_theme_library(app, library: dict[str, object] | None) -> dict[str, dict[str, object]]:
    sanitized: dict[str, dict[str, object]] = {}
    for raw_name, raw_values in dict(library or {}).items():
        name = str(raw_name or "").strip()
        if not name:
            continue
        sanitized[name] = app._stored_theme_payload(dict(raw_values or {}))
    return sanitized


def _load_theme_library(app) -> dict[str, dict[str, object]]:
    raw_value = app.settings.value("theme/library_json", "{}", str)
    try:
        parsed = json.loads(raw_value or "{}")
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    bundled = starter_theme_library()
    custom = app._sanitize_theme_library(parsed)
    custom = {name: values for name, values in custom.items() if name not in bundled}
    merged = dict(bundled)
    merged.update(custom)
    return merged


def _save_theme_library(app, library: dict[str, object] | None) -> dict[str, dict[str, object]]:
    sanitized = app._sanitize_theme_library(library)
    bundled_names = set(starter_theme_names())
    custom_only = {name: values for name, values in sanitized.items() if name not in bundled_names}
    app.settings.setValue("theme/library_json", json.dumps(custom_only, sort_keys=True))
    app.settings.sync()
    return sanitized


def _color_relative_luminance(color_value: str) -> float:
    return theme_color_relative_luminance(color_value)


def _contrast_ratio(fg_value: str, bg_value: str) -> float:
    return theme_contrast_ratio(fg_value, bg_value)


def _pick_contrasting_color(bg_value: str) -> str:
    return pick_theme_contrasting_color(bg_value)


def _shift_color(color_value: str, factor: int) -> str:
    return shift_theme_color(color_value, factor)


def _effective_theme_settings(
    app, raw_values: dict[str, object] | None = None
) -> dict[str, object]:
    return build_effective_theme_settings(raw_values or app.theme_settings)


def _save_theme_settings(app, values: dict[str, object]) -> dict[str, object]:
    normalized = app._normalize_theme_settings(values)
    for key in app._theme_setting_keys():
        app.settings.setValue(f"theme/{key}", normalized.get(key))
    app.settings.sync()
    app.theme_settings = normalized
    return normalized


def _blob_icon_setting_defaults() -> dict[str, dict[str, object]]:
    return default_blob_icon_settings()


def _load_blob_icon_settings(app) -> dict[str, dict[str, object]]:
    if app.blob_icon_settings_service is None:
        return app._blob_icon_setting_defaults()
    return normalize_blob_icon_settings(app.blob_icon_settings_service.load_settings())


def _save_blob_icon_settings(app, values: dict[str, object] | None) -> dict[str, dict[str, object]]:
    normalized = normalize_blob_icon_settings(values)
    if app.blob_icon_settings_service is not None:
        normalized = normalize_blob_icon_settings(
            app.blob_icon_settings_service.save_settings(normalized)
        )
    app.blob_icon_settings = normalized
    app._reset_blob_badge_render_cache()
    return normalized


def _reset_blob_badge_render_cache(app) -> None:
    app._blob_badge_icon_cache: dict[tuple[str, int, str], QIcon] = {}


def _active_custom_qss(app) -> str:
    return str((app.theme_settings or {}).get("custom_qss") or "")


def _build_theme_stylesheet(app, raw_values: dict[str, object] | None = None) -> str:
    return build_app_theme_stylesheet(raw_values or app.theme_settings)


def _set_application_theme_stylesheet(host, qt_app: QApplication, stylesheet: str) -> None:
    qt_app.setStyleSheet(stylesheet)


def _apply_theme(app, raw_values: dict[str, object] | None = None) -> None:
    qt_app = QApplication.instance()
    if qt_app is None:
        return
    theme_source = app.theme_settings if raw_values is None else raw_values
    normalized = app._normalize_theme_settings(theme_source)
    effective = app._effective_theme_settings(normalized)
    font = QFont(str(effective["font_family"]))
    font.setPointSize(int(effective["font_size"]))
    qt_app.setFont(font)
    palette = build_app_theme_palette(normalized)
    qt_app.setPalette(palette)
    app.setPalette(palette)
    qt_app.setStyle(build_app_theme_style(normalized))
    qss_issues = validate_qss_document(normalized.get("custom_qss"))
    if qss_issues:
        safe_values = dict(normalized)
        safe_values["custom_qss"] = ""
        if getattr(app, "logger", None) is not None:
            app.logger.warning(
                "Skipping invalid advanced QSS during theme application: %s",
                app._format_theme_qss_issues(qss_issues),
            )
        app._set_application_theme_stylesheet(
            qt_app,
            app._build_theme_stylesheet(safe_values),
        )
    else:
        app._set_application_theme_stylesheet(
            qt_app,
            app._build_theme_stylesheet(normalized),
        )
    refresh_catalog_toolbar_metrics = getattr(
        app, "_apply_catalog_table_toolbar_theme_metrics", None
    )
    if callable(refresh_catalog_toolbar_metrics):
        refresh_catalog_toolbar_metrics(effective)
    task_manager = getattr(app, "background_tasks", None)
    if task_manager is not None and callable(
        getattr(task_manager, "refresh_active_progress_dialogs", None)
    ):
        task_manager.refresh_active_progress_dialogs()
    app._reset_blob_badge_render_cache()
    app._refresh_menu_theme_state()
    app._queue_top_chrome_boundary_refresh()


def _prepare_theme_application_payload(
    app, raw_values: dict[str, object] | None = None
) -> dict[str, object]:
    theme_source = app.theme_settings if raw_values is None else raw_values
    normalized = app._normalize_theme_settings(theme_source)
    qss_issues = validate_qss_document(normalized.get("custom_qss"))
    if qss_issues:
        raise ValueError(
            "Advanced QSS is not ready to apply.\n\n" + app._format_theme_qss_issues(qss_issues)
        )
    effective = app._effective_theme_settings(normalized)
    return {
        "normalized_theme": normalized,
        "effective_theme": effective,
        "stylesheet": build_app_theme_stylesheet(normalized),
    }


def _apply_prepared_theme_payload(app, payload: dict[str, object]) -> None:
    qt_app = QApplication.instance()
    if qt_app is None:
        return
    effective = dict(payload.get("effective_theme") or app._effective_theme_settings())
    normalized = dict(payload.get("normalized_theme") or app.theme_settings or {})
    font = QFont(str(effective["font_family"]))
    font.setPointSize(int(effective["font_size"]))
    qt_app.setFont(font)
    palette = build_app_theme_palette(normalized)
    qt_app.setPalette(palette)
    app.setPalette(palette)
    qt_app.setStyle(build_app_theme_style(normalized))
    app._set_application_theme_stylesheet(
        qt_app,
        str(payload.get("stylesheet") or app._build_theme_stylesheet(normalized)),
    )
    refresh_catalog_toolbar_metrics = getattr(
        app, "_apply_catalog_table_toolbar_theme_metrics", None
    )
    if callable(refresh_catalog_toolbar_metrics):
        refresh_catalog_toolbar_metrics(effective)
    task_manager = getattr(app, "background_tasks", None)
    if task_manager is not None and callable(
        getattr(task_manager, "refresh_active_progress_dialogs", None)
    ):
        task_manager.refresh_active_progress_dialogs()
    app._reset_blob_badge_render_cache()
    app._refresh_menu_theme_state()
    app._queue_top_chrome_boundary_refresh()


def _refresh_menu_theme_state(app) -> None:
    qt_app = QApplication.instance()
    if qt_app is None:
        return
    palette = qt_app.palette()
    seen: set[int] = set()

    def _refresh(widget: QWidget | None) -> None:
        if widget is None:
            return
        widget_id = id(widget)
        if widget_id in seen:
            return
        seen.add(widget_id)
        try:
            widget.setPalette(palette)
        except Exception:
            pass
        try:
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)
        except Exception:
            pass
        try:
            widget.setPalette(palette)
        except Exception:
            pass
        try:
            widget.update()
        except Exception:
            pass

    menu_bar = getattr(app, "menu_bar", None)
    if isinstance(menu_bar, QMenuBar):
        _refresh(menu_bar)
    for menu in app.findChildren(QMenu):
        _refresh(menu)


def _apply_theme_with_loading(
    app,
    raw_values: dict[str, object] | None = None,
    *,
    title: str = "Apply Theme",
    description: str = "Preparing updated theme styles...",
) -> None:
    prepared: dict[str, object] = {}
    failure: dict[str, TaskFailure] = {}
    cancelled = {"value": False}
    loop = QEventLoop(app)

    def _task(ctx):
        ctx.set_status("Preparing updated theme styles...")
        return app._prepare_theme_application_payload(raw_values)

    def _quit_loop() -> None:
        if loop.isRunning():
            loop.quit()

    task_id = app._submit_background_task(
        title=title,
        description=description,
        task_fn=_task,
        kind="read",
        unique_key="theme.apply.prepare",
        requires_profile=False,
        show_dialog=True,
        owner=app,
        on_success=lambda payload: (prepared.update(payload), _quit_loop()),
        on_error=lambda task_failure: (failure.setdefault("value", task_failure), _quit_loop()),
        on_cancelled=lambda: (cancelled.__setitem__("value", True), _quit_loop()),
    )
    if task_id is None:
        message = failure.get("value").message if "value" in failure else "Task could not start."
        raise RuntimeError(message)
    if not prepared and "value" not in failure and not cancelled["value"]:
        loop.exec()
    if "value" in failure:
        raise RuntimeError(failure["value"].message)
    if cancelled["value"]:
        return
    app._apply_prepared_theme_payload(prepared)
