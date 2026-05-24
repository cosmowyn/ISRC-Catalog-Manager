"""Application-level ISRC registry and generation orchestration."""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QMessageBox, QWidget

from isrc_manager.domain.codes import to_compact_isrc
from isrc_manager.isrc_registry import ISRCRegistryConflict


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback)
        if main_window_module is not None
        else fallback
    )


def load_isrc_prefix(app):
    return app.settings_reads.load_isrc_prefix()


def _profile_paths_for_isrc_registry(app) -> list[Path]:
    candidates: list[Path] = []
    profile_store = getattr(app, "profile_store", None)
    if profile_store is not None:
        try:
            candidates.extend(Path(path) for path in profile_store.list_profiles())
        except Exception:
            pass
    current_path = str(getattr(app, "current_db_path", "") or "").strip()
    if current_path:
        candidates.append(Path(current_path))
    seen: set[str] = set()
    paths: list[Path] = []
    for candidate in candidates:
        normalized = str(Path(candidate).expanduser().resolve(strict=False))
        if normalized in seen:
            continue
        seen.add(normalized)
        paths.append(Path(normalized))
    return paths


def _sync_application_isrc_registry(app) -> None:
    registry = getattr(app, "application_isrc_registry", None)
    if registry is None:
        return
    try:
        summary = registry.sync_profiles(app._profile_paths_for_isrc_registry())
        app._last_isrc_registry_sync_summary = summary
        if summary.conflict_count:
            app._log_event(
                "isrc.registry.sync_conflicts",
                "Cross-profile ISRC registry found duplicate claims",
                level=logging.WARNING,
                profiles=summary.profile_count,
                conflicts=summary.conflict_count,
            )
    except Exception as exc:
        app.logger.warning("Application ISRC registry sync failed: %s", exc)


def _format_isrc_registry_conflict(conflict: ISRCRegistryConflict) -> str:
    profile_label = conflict.profile_name or Path(conflict.profile_path).name
    track_bits = []
    if conflict.track_id is not None:
        track_bits.append(f"track #{conflict.track_id}")
    if conflict.track_title:
        track_bits.append(f"'{conflict.track_title}'")
    track_text = " ".join(track_bits).strip() or "an existing track"
    return f"{conflict.isrc_iso or conflict.isrc_compact} is already claimed by {track_text} in {profile_label}."


def _isrc_registry_conflict(
    app,
    candidate: str,
    *,
    exclude_track_id: int | None = None,
) -> ISRCRegistryConflict | None:
    registry = getattr(app, "application_isrc_registry", None)
    if registry is None:
        return None
    current_path = str(getattr(app, "current_db_path", "") or "").strip() or None
    try:
        return registry.find_conflict(
            candidate,
            profile_path=current_path,
            exclude_track_id=exclude_track_id,
        )
    except Exception as exc:
        app.logger.warning("Application ISRC registry lookup failed: %s", exc)
        return None


def _reserve_isrc_claim_for_profile(
    app,
    isrc: str,
    *,
    track_title: str | None = None,
    claim_kind: str = "generated",
    exclude_track_id: int | None = None,
    parent_widget: QWidget | None = None,
) -> bool:
    registry = getattr(app, "application_isrc_registry", None)
    current_path = str(getattr(app, "current_db_path", "") or "").strip()
    if registry is None or not current_path or not to_compact_isrc(isrc):
        return True
    try:
        conflict = registry.reserve_isrc(
            isrc,
            profile_path=current_path,
            profile_name=app._current_profile_name(),
            track_title=track_title,
            claim_kind=claim_kind,
            exclude_track_id=exclude_track_id,
        )
    except Exception as exc:
        app.logger.warning("Application ISRC registry reservation failed: %s", exc)
        return True
    if conflict is None:
        return True
    _root_attr("QMessageBox", QMessageBox).warning(
        parent_widget or app,
        "Duplicate ISRC",
        app._format_isrc_registry_conflict(conflict),
    )
    return False


def _activate_isrc_claim_for_track(
    app,
    isrc: str,
    *,
    track_id: int,
    track_title: str,
    claim_kind: str = "profile_sync",
) -> None:
    registry = getattr(app, "application_isrc_registry", None)
    current_path = str(getattr(app, "current_db_path", "") or "").strip()
    if registry is None or not current_path or not to_compact_isrc(isrc):
        return
    try:
        conflict = registry.activate_isrc(
            isrc,
            profile_path=current_path,
            profile_name=app._current_profile_name(),
            track_id=int(track_id),
            track_title=track_title,
            claim_kind=claim_kind,
        )
        if conflict is not None:
            app._log_event(
                "isrc.registry.activate_conflict",
                "Could not activate ISRC claim because another profile already owns it",
                level=logging.WARNING,
                isrc=isrc,
                conflict_profile=conflict.profile_name,
                conflict_track_id=conflict.track_id,
            )
    except Exception as exc:
        app.logger.warning("Application ISRC registry activation failed: %s", exc)


def _release_reserved_isrc_claim(app, isrc: str) -> None:
    registry = getattr(app, "application_isrc_registry", None)
    current_path = str(getattr(app, "current_db_path", "") or "").strip()
    if registry is None or not current_path or not to_compact_isrc(isrc):
        return
    try:
        registry.release_reserved_isrc(isrc, profile_path=current_path)
    except Exception as exc:
        app.logger.warning("Application ISRC registry reservation release failed: %s", exc)


def _claim_next_generated_isrc(
    app,
    *,
    release_date: QDate | None = None,
    use_release_year: bool = False,
    reserved_compacts: set[str] | None = None,
    track_title: str | None = None,
    parent_widget: QWidget | None = None,
) -> str:
    blocked_compacts = set(reserved_compacts or set())
    while True:
        candidate = app._next_generated_isrc(
            release_date=release_date,
            use_release_year=use_release_year,
            reserved_compacts=blocked_compacts,
        )
        compact = to_compact_isrc(candidate)
        if not compact:
            return ""
        if app._reserve_isrc_claim_for_profile(
            candidate,
            track_title=track_title,
            claim_kind="generated",
            parent_widget=parent_widget,
        ):
            return candidate
        blocked_compacts.add(compact)


def _isrc_generation_state(app) -> tuple[str, str]:
    prefix = (app.load_isrc_prefix() or "").upper().strip()
    if not prefix:
        return (
            "disabled",
            "No ISRC prefix is configured. Tracks can still be saved, but ISRC auto-generation stays disabled until you add one in Settings.",
        )
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", prefix):
        return (
            "error",
            "The saved ISRC prefix is invalid. Fix it in Settings to re-enable auto-generation.",
        )

    artist_code = app.load_artist_code()
    if not re.fullmatch(r"\d{2}", artist_code or ""):
        return (
            "error",
            "The saved ISRC artist code is invalid. Fix it in Settings to re-enable auto-generation.",
        )

    return ("ready", "")


def _next_generated_isrc(
    app,
    *,
    release_date: QDate | None = None,
    use_release_year: bool = False,
    reserved_compacts: set[str] | None = None,
) -> str:
    if app.conn is None or app.cursor is None:
        return ""
    state, _message = app._isrc_generation_state()
    if state != "ready":
        return ""

    prefix = (app.load_isrc_prefix() or "").upper().strip()
    artist_code = app.load_artist_code()
    year = datetime.now().year % 100
    if use_release_year and isinstance(release_date, QDate) and release_date.isValid():
        year = release_date.year() % 100
    yy = f"{year:02d}"

    claimed_compacts = {
        str(code or "").strip().upper()
        for code in (reserved_compacts or set())
        if str(code or "").strip()
    }
    for seq in range(1, 1000):
        sss = f"{seq:03d}"
        candidate_compact = f"{prefix}{yy}{artist_code}{sss}"
        if candidate_compact in claimed_compacts:
            continue
        candidate = f"{prefix[0:2]}-{prefix[2:5]}-{yy}-{artist_code}{sss}"
        try:
            if not app.is_isrc_taken_normalized(candidate):
                return candidate
        except Exception:
            return candidate
    return ""


def _preview_generated_isrc(app) -> str:
    release_date = None
    if hasattr(app, "release_date_field"):
        try:
            release_date = app.release_date_field.selectedDate()
        except Exception:
            release_date = None
    return app._next_generated_isrc(
        release_date=release_date,
        use_release_year=bool(
            hasattr(app, "prev_release_toggle") and app.prev_release_toggle.isChecked()
        ),
    )


def _update_add_data_generated_fields(app) -> None:
    if hasattr(app, "record_id_field"):
        app.record_id_field.clear()
    if hasattr(app, "entry_date_preview_field"):
        app.entry_date_preview_field.clear()
    if not hasattr(app, "generated_isrc_field"):
        return

    state, message = app._isrc_generation_state()
    preview = app._preview_generated_isrc()
    app.generated_isrc_field.setText(preview)
    if hasattr(app, "prev_release_toggle"):
        app.prev_release_toggle.setEnabled(state == "ready")

    if preview:
        app.generated_isrc_field.setPlaceholderText(
            "Generated automatically using the current ISRC settings."
        )
        app.generated_isrc_field.setToolTip(
            "Next available ISRC based on the current release date and ISRC settings."
        )
    elif state == "ready":
        app.generated_isrc_field.setPlaceholderText("No free ISRC sequence is currently available.")
        app.generated_isrc_field.setToolTip(
            "ISRC auto-generation is enabled, but no free sequence is currently available for the active year and artist code."
        )
    elif state == "disabled":
        app.generated_isrc_field.setPlaceholderText(
            "Auto-generation disabled until an ISRC prefix is set."
        )
        app.generated_isrc_field.setToolTip(message)
    else:
        app.generated_isrc_field.setPlaceholderText(
            "Fix ISRC settings to re-enable auto-generation."
        )
        app.generated_isrc_field.setToolTip(message)


def generate_isrc(app) -> str:
    return app._next_generated_isrc(
        release_date=app.release_date_field.selectedDate(),
        use_release_year=bool(app.prev_release_toggle.isChecked()),
    )


def set_isrc_prefix(app, prefix: str | None = None):
    if prefix is None:
        app.open_settings_dialog(initial_focus="isrc_prefix")
        return

    pref = (prefix or "").strip().upper()
    if pref and not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", pref):
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Invalid Prefix", "Prefix must be CC+XXX (5 chars)."
        )
        return
    try:
        app._apply_single_setting_value("isrc_prefix", pref)
    except Exception as e:
        app.logger.exception(f"Set ISRC prefix failed: {e}")
        _root_attr("QMessageBox", QMessageBox).critical(
            app, "Error", f"Could not save prefix:\n{e}"
        )


def is_isrc_taken_normalized(app, candidate: str, exclude_track_id: int | None = None) -> bool:
    if app.track_service is not None:
        if app.track_service.is_isrc_taken_normalized(
            candidate,
            exclude_track_id=exclude_track_id,
            cursor=app.cursor,
        ):
            return True
    return app._isrc_registry_conflict(candidate, exclude_track_id=exclude_track_id) is not None
