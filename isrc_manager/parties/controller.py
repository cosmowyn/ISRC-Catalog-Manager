"""Party workflow orchestration for the application shell."""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDockWidget,
    QFileDialog,
    QMessageBox,
    QWidget,
)

from isrc_manager.catalog_workspace import ensure_catalog_workspace_dock
from isrc_manager.parties import (
    PartyExchangeInspection,
    PartyImportOptions,
    PartyImportReport,
    PartyPayload,
    PartyRecord,
    artist_choice_label,
    artist_primary_label,
)
from isrc_manager.parties.dialogs import OwnerBootstrapDialog, PartyImportDialog, PartyManagerPanel
from isrc_manager.services import OwnerPartySettings
from isrc_manager.tasks.history_helpers import run_file_history_action, run_snapshot_history_action


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback)
        if main_window_module is not None
        else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _file_dialog():
    return _root_attr("QFileDialog", QFileDialog)


def _timer():
    return _root_attr("QTimer", QTimer)


def _party_manager_panel_class():
    return _root_attr("PartyManagerPanel", PartyManagerPanel)


def _party_import_dialog_class():
    return _root_attr("PartyImportDialog", PartyImportDialog)


def _owner_bootstrap_dialog_class():
    return _root_attr("OwnerBootstrapDialog", OwnerBootstrapDialog)


def _run_snapshot_history_action(*args, **kwargs):
    return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(*args, **kwargs)


def _run_file_history_action(*args, **kwargs):
    return _root_attr("run_file_history_action", run_file_history_action)(*args, **kwargs)

def _create_party_manager_panel(self, parent: QWidget) -> PartyManagerPanel:
    return _party_manager_panel_class()(
        party_service_provider=lambda: self.party_service,
        current_owner_party_id_provider=self._current_owner_party_id,
        set_owner_party_handler=self._assign_owner_party,
        import_party_handler=self.import_party_exchange_file,
        export_party_handler=self.export_party_exchange_file,
        parent=parent,
    )
def _ensure_party_manager_dock(self) -> QDockWidget:
    dock = ensure_catalog_workspace_dock(
        self,
        key="party_manager",
        title="Party Manager",
        object_name="partyManagerDock",
        panel_factory=self._create_party_manager_panel,
    )
    self.party_manager_dock = dock
    return dock
def _party_identity_primary_label(record: PartyRecord) -> str:
    return (
        str(record.display_name or "").strip()
        or str(record.artist_name or "").strip()
        or str(record.company_name or "").strip()
        or str(record.legal_name or "").strip()
        or f"Party #{int(record.id)}"
    )
def _owner_party_choice_label(record: PartyRecord) -> str:
    primary = _party_identity_primary_label(record)
    legal_name = str(record.legal_name or "").strip()
    if legal_name and legal_name.casefold() != primary.casefold():
        return f"{primary} ({legal_name})"
    return primary
def _current_owner_party_id(self) -> int | None:
    settings_reads = getattr(self, "settings_reads", None)
    if settings_reads is None:
        return None
    return settings_reads.load_owner_party_id()
def _current_owner_party_record(self) -> PartyRecord | None:
    party_service = getattr(self, "party_service", None)
    if party_service is None:
        return None
    owner_party_id = self._current_owner_party_id()
    if owner_party_id is None:
        return None
    return party_service.fetch_party(int(owner_party_id))
def _legacy_owner_snapshot_has_data(snapshot: OwnerPartySettings) -> bool:
    fields = (
        snapshot.legal_name,
        snapshot.display_name,
        snapshot.artist_name,
        snapshot.company_name,
        snapshot.first_name,
        snapshot.middle_name,
        snapshot.last_name,
        snapshot.contact_person,
        snapshot.email,
        snapshot.alternative_email,
        snapshot.phone,
        snapshot.website,
        snapshot.street_name,
        snapshot.street_number,
        snapshot.address_line1,
        snapshot.address_line2,
        snapshot.city,
        snapshot.region,
        snapshot.postal_code,
        snapshot.country,
        snapshot.bank_account_number,
        snapshot.chamber_of_commerce_number,
        snapshot.tax_id,
        snapshot.vat_number,
        snapshot.pro_affiliation,
        snapshot.pro_number,
        snapshot.ipi_cae,
        snapshot.notes,
    )
    return any(str(value or "").strip() for value in fields)
def _owner_snapshot_name_candidates(snapshot: OwnerPartySettings) -> list[str]:
    person_name = " ".join(
        part
        for part in (
            str(snapshot.first_name or "").strip(),
            str(snapshot.middle_name or "").strip(),
            str(snapshot.last_name or "").strip(),
        )
        if part
    ).strip()
    candidates: list[str] = []
    for raw_value in (
        snapshot.legal_name,
        snapshot.display_name,
        snapshot.artist_name,
        snapshot.company_name,
        person_name,
    ):
        clean_value = str(raw_value or "").strip()
        if clean_value and clean_value.casefold() not in {
            item.casefold() for item in candidates
        }:
            candidates.append(clean_value)
    return candidates
def _owner_snapshot_to_party_payload(
    snapshot: OwnerPartySettings,
    *,
    profile_name: str | None,
) -> PartyPayload:
    legal_name = (
        str(snapshot.legal_name or "").strip()
        or str(snapshot.display_name or "").strip()
        or str(snapshot.company_name or "").strip()
        or "Owner Party"
    )
    party_type = "person" if str(snapshot.first_name or "").strip() else "organization"
    return PartyPayload(
        legal_name=legal_name,
        display_name=str(snapshot.display_name or "").strip() or None,
        artist_name=str(snapshot.artist_name or "").strip() or None,
        company_name=str(snapshot.company_name or "").strip() or None,
        first_name=str(snapshot.first_name or "").strip() or None,
        middle_name=str(snapshot.middle_name or "").strip() or None,
        last_name=str(snapshot.last_name or "").strip() or None,
        party_type=party_type,
        contact_person=str(snapshot.contact_person or "").strip() or None,
        email=str(snapshot.email or "").strip() or None,
        alternative_email=str(snapshot.alternative_email or "").strip() or None,
        phone=str(snapshot.phone or "").strip() or None,
        website=str(snapshot.website or "").strip() or None,
        street_name=str(snapshot.street_name or "").strip() or None,
        street_number=str(snapshot.street_number or "").strip() or None,
        address_line1=str(snapshot.address_line1 or "").strip() or None,
        address_line2=str(snapshot.address_line2 or "").strip() or None,
        city=str(snapshot.city or "").strip() or None,
        region=str(snapshot.region or "").strip() or None,
        postal_code=str(snapshot.postal_code or "").strip() or None,
        country=str(snapshot.country or "").strip() or None,
        bank_account_number=str(snapshot.bank_account_number or "").strip() or None,
        chamber_of_commerce_number=str(snapshot.chamber_of_commerce_number or "").strip()
        or None,
        tax_id=str(snapshot.tax_id or "").strip() or None,
        vat_number=str(snapshot.vat_number or "").strip() or None,
        pro_affiliation=str(snapshot.pro_affiliation or "").strip() or None,
        pro_number=str(snapshot.pro_number or "").strip() or None,
        ipi_cae=str(snapshot.ipi_cae or "").strip() or None,
        notes=str(snapshot.notes or "").strip() or None,
        profile_name=str(profile_name or "").strip() or None,
    )
def _merge_owner_snapshot_into_party(
    record: PartyRecord,
    snapshot: OwnerPartySettings,
) -> PartyPayload:
    def choose(existing: str | None, incoming: str | None) -> str | None:
        clean_existing = str(existing or "").strip()
        clean_incoming = str(incoming or "").strip()
        return clean_existing or clean_incoming or None

    return PartyPayload(
        legal_name=choose(record.legal_name, snapshot.legal_name) or "Owner Party",
        display_name=choose(record.display_name, snapshot.display_name),
        artist_name=choose(record.artist_name, snapshot.artist_name),
        company_name=choose(record.company_name, snapshot.company_name),
        first_name=choose(record.first_name, snapshot.first_name),
        middle_name=choose(record.middle_name, snapshot.middle_name),
        last_name=choose(record.last_name, snapshot.last_name),
        party_type=str(record.party_type or "organization"),
        contact_person=choose(record.contact_person, snapshot.contact_person),
        email=choose(record.email, snapshot.email),
        alternative_email=choose(record.alternative_email, snapshot.alternative_email),
        phone=choose(record.phone, snapshot.phone),
        website=choose(record.website, snapshot.website),
        street_name=choose(record.street_name, snapshot.street_name),
        street_number=choose(record.street_number, snapshot.street_number),
        address_line1=choose(record.address_line1, snapshot.address_line1),
        address_line2=choose(record.address_line2, snapshot.address_line2),
        city=choose(record.city, snapshot.city),
        region=choose(record.region, snapshot.region),
        postal_code=choose(record.postal_code, snapshot.postal_code),
        country=choose(record.country, snapshot.country),
        bank_account_number=choose(record.bank_account_number, snapshot.bank_account_number),
        chamber_of_commerce_number=choose(
            record.chamber_of_commerce_number,
            snapshot.chamber_of_commerce_number,
        ),
        tax_id=choose(record.tax_id, snapshot.tax_id),
        vat_number=choose(record.vat_number, snapshot.vat_number),
        pro_affiliation=choose(record.pro_affiliation, snapshot.pro_affiliation),
        pro_number=choose(record.pro_number, snapshot.pro_number),
        ipi_cae=choose(record.ipi_cae, snapshot.ipi_cae),
        notes=choose(record.notes, snapshot.notes),
        profile_name=choose(record.profile_name, None),
        artist_aliases=list(record.artist_aliases),
    )
def _assign_owner_party(
    self,
    party_id: int | None,
    *,
    record_history: bool = True,
) -> int | None:
    if self.settings_mutations is None:
        return None
    before_owner_party_id = self._current_owner_party_id()
    saved_owner_party_id = self.settings_mutations.set_owner_party_id(party_id)
    if (
        record_history
        and self.history_manager is not None
        and before_owner_party_id != saved_owner_party_id
    ):
        self.history_manager.record_setting_change(
            key="owner_party_id",
            label="Set Current Owner Party",
            before_value=before_owner_party_id,
            after_value=saved_owner_party_id,
        )
    self._refresh_catalog_workspace_docks()
    current_owner = self._current_owner_party_record()
    if current_owner is not None:
        self.statusBar().showMessage(
            f"Current Owner Party set to {self._owner_party_choice_label(current_owner)}",
            4000,
        )
    return saved_owner_party_id
def _migrate_legacy_owner_party_if_needed(self) -> None:
    if (
        self.party_service is None
        or self.settings_reads is None
        or self.settings_mutations is None
    ):
        return
    current_owner = self._current_owner_party_record()
    legacy_snapshot = self.settings_reads.load_legacy_owner_party_snapshot()
    if current_owner is not None:
        if self._legacy_owner_snapshot_has_data(legacy_snapshot):
            merged_payload = self._merge_owner_snapshot_into_party(
                current_owner, legacy_snapshot
            )
            try:
                self.party_service.update_party(int(current_owner.id), merged_payload)
            except Exception:
                pass
        self.settings_mutations.set_owner_party_id(int(current_owner.id))
        with self.conn:
            self.conn.execute("DELETE FROM BTW WHERE id=1")
            self.conn.execute("DELETE FROM BUMA_STEMRA WHERE id=1")
        return
    if not self._legacy_owner_snapshot_has_data(legacy_snapshot):
        return
    matched_party_id = None
    linked_party_id = getattr(legacy_snapshot, "party_id", None)
    if linked_party_id is not None:
        linked_record = self.party_service.fetch_party(int(linked_party_id))
        if linked_record is not None:
            matched_party_id = int(linked_record.id)
    if matched_party_id is None:
        for candidate in self._owner_snapshot_name_candidates(legacy_snapshot):
            party_id = self.party_service.find_party_id_by_name(candidate)
            if party_id is not None:
                matched_party_id = int(party_id)
                break
    if matched_party_id is not None:
        existing = self.party_service.fetch_party(int(matched_party_id))
        if existing is not None:
            merged_payload = self._merge_owner_snapshot_into_party(existing, legacy_snapshot)
            self.party_service.update_party(int(existing.id), merged_payload)
            self._assign_owner_party(int(existing.id), record_history=False)
            with self.conn:
                self.conn.execute("DELETE FROM BTW WHERE id=1")
                self.conn.execute("DELETE FROM BUMA_STEMRA WHERE id=1")
            return
    created_party_id = self.party_service.create_party(
        self._owner_snapshot_to_party_payload(
            legacy_snapshot,
            profile_name=self._current_profile_name(),
        )
    )
    self._assign_owner_party(int(created_party_id), record_history=False)
    with self.conn:
        self.conn.execute("DELETE FROM BTW WHERE id=1")
        self.conn.execute("DELETE FROM BUMA_STEMRA WHERE id=1")
def _owner_bootstrap_required(self) -> bool:
    return self.party_service is not None and self._current_owner_party_record() is None
def _schedule_owner_party_bootstrap(self) -> None:
    if getattr(self, "_owner_party_bootstrap_scheduled", False):
        return
    self._owner_party_bootstrap_scheduled = True
    _timer().singleShot(0, lambda: self._ensure_owner_party_bootstrap())
def _ensure_owner_party_bootstrap(self) -> None:
    self._owner_party_bootstrap_scheduled = False
    if not self._owner_bootstrap_required():
        return
    if self.party_service is None:
        return
    while self._current_owner_party_record() is None:
        dialog = _owner_bootstrap_dialog_class()(
            party_service=self.party_service,
            current_owner_party_id=self._current_owner_party_id(),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            continue
        selected_party_id = dialog.selected_party_id()
        if selected_party_id is None:
            continue
        self._assign_owner_party(int(selected_party_id), record_history=False)
def _artist_party_primary_label(record: PartyRecord) -> str:
    return artist_primary_label(record)
def _artist_party_choice_label(record: PartyRecord) -> str:
    return artist_choice_label(record)
def _artist_party_records(self) -> list[PartyRecord]:
    if self.party_service is None:
        return []
    try:
        return list(self.party_service.list_artist_parties() or [])
    except Exception:
        return []
def _configure_artist_party_combo(
    self,
    combo: QComboBox,
    *,
    allow_empty: bool = False,
    selected_party_id: int | None = None,
    current_text: str | None = None,
) -> None:
    clean_text_value = str(current_text or "").strip()
    labels: list[str] = []
    previous_state = combo.blockSignals(True)
    try:
        combo.clear()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        if allow_empty:
            combo.addItem("", None)
        for record in self._artist_party_records():
            label = self._artist_party_choice_label(record)
            combo.addItem(label, int(record.id))
            combo.setItemData(
                combo.count() - 1,
                self._artist_party_primary_label(record),
                Qt.UserRole + 1,
            )
            labels.append(label)
            labels.extend(
                alias
                for alias in getattr(record, "artist_aliases", ()) or ()
                if str(alias or "").strip()
            )
        if selected_party_id is not None and combo.findData(int(selected_party_id)) < 0:
            fallback_label = clean_text_value or f"Party #{int(selected_party_id)}"
            combo.addItem(fallback_label, int(selected_party_id))
            combo.setItemData(combo.count() - 1, fallback_label, Qt.UserRole + 1)
            labels.append(fallback_label)
        completer = QCompleter(sorted({label for label in labels if label}), combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        combo.setCompleter(completer)
        if selected_party_id is not None:
            index = combo.findData(int(selected_party_id))
            combo.setCurrentIndex(index if index >= 0 else 0)
        elif clean_text_value:
            combo.setCurrentIndex(-1)
            combo.setEditText(clean_text_value)
        elif allow_empty:
            combo.setCurrentIndex(0)
    finally:
        combo.blockSignals(previous_state)
def _resolve_artist_party_choice(self, combo: QComboBox) -> tuple[str, int | None]:
    clean = str(combo.currentText() or "").strip()
    if not clean:
        return "", None
    current_index = combo.currentIndex()
    if current_index >= 0:
        data = combo.itemData(current_index)
        label = str(combo.itemText(current_index) or "").strip()
        if data not in (None, "") and clean.casefold() == label.casefold():
            primary_label = str(combo.itemData(current_index, Qt.UserRole + 1) or label).strip()
            return primary_label or label, int(data)
    for index in range(combo.count()):
        label = str(combo.itemText(index) or "").strip()
        if clean.casefold() != label.casefold():
            continue
        data = combo.itemData(index)
        if data not in (None, ""):
            primary_label = str(combo.itemData(index, Qt.UserRole + 1) or label).strip()
            return primary_label or label, int(data)
    return clean, None
def _resolve_party_backed_artist_name(
    self,
    raw_name: str,
    *,
    selected_party_id: int | None = None,
    cursor: sqlite3.Cursor | None = None,
) -> tuple[str, int | None]:
    clean_name = str(raw_name or "").strip()
    if not clean_name:
        return "", None
    if self.party_service is None:
        return clean_name, None
    party_id = int(selected_party_id) if selected_party_id not in (None, "") else None
    if party_id is None:
        existing_id = self.party_service.find_artist_party_id_by_name(
            clean_name,
            cursor=cursor,
        )
        if existing_id is not None:
            party_id = int(existing_id)
        else:
            party_id = int(
                self.party_service.ensure_artist_party_by_name(
                    clean_name,
                    cursor=cursor,
                )
            )
    record = self.party_service.fetch_party(int(party_id))
    if record is None:
        return clean_name, int(party_id)
    return self._artist_party_primary_label(record), int(record.id)
def _resolve_party_backed_additional_artist_names(
    self,
    names: list[str],
    *,
    cursor: sqlite3.Cursor | None = None,
) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for raw_name in names:
        clean_name, _party_id = self._resolve_party_backed_artist_name(
            raw_name,
            cursor=cursor,
        )
        normalized = clean_name.casefold()
        if not clean_name or normalized in seen:
            continue
        seen.add(normalized)
        resolved.append(clean_name)
    return resolved
def _refresh_add_track_artist_party_choices(self) -> None:
    for combo, allow_empty in (
        (getattr(self, "artist_field", None), False),
        (getattr(self, "additional_artist_field", None), True),
    ):
        if not isinstance(combo, QComboBox):
            continue
        current_text, selected_party_id = self._resolve_artist_party_choice(combo)
        self._configure_artist_party_combo(
            combo,
            allow_empty=allow_empty,
            selected_party_id=selected_party_id,
            current_text=current_text,
        )
def _on_party_authority_changed(self) -> None:
    if self.conn is None:
        return
    artist_combo_states: list[tuple[QComboBox, bool, str, int | None]] = []
    for combo, allow_empty in (
        (getattr(self, "artist_field", None), False),
        (getattr(self, "additional_artist_field", None), True),
    ):
        if not isinstance(combo, QComboBox):
            continue
        current_text, selected_party_id = self._resolve_artist_party_choice(combo)
        artist_combo_states.append((combo, allow_empty, current_text, selected_party_id))
    try:
        self.populate_all_comboboxes()
    except Exception:
        pass
    for combo, allow_empty, current_text, selected_party_id in artist_combo_states:
        try:
            self._configure_artist_party_combo(
                combo,
                allow_empty=allow_empty,
                selected_party_id=selected_party_id,
                current_text=current_text,
            )
        except Exception:
            pass
    try:
        self.refresh_table_preserve_view()
    except Exception:
        pass
    try:
        self._refresh_work_manager_panel()
    except Exception:
        pass
    try:
        self._refresh_party_manager_panel()
    except Exception:
        pass
    try:
        if self.release_browser_dialog is not None and self.release_browser_dialog.isVisible():
            self.release_browser_dialog.refresh()
    except Exception:
        pass
    try:
        self._refresh_catalog_workspace_docks()
    except Exception:
        pass
    try:
        self._refresh_add_track_artist_party_choices()
    except Exception:
        pass
def open_party_manager(self, party_id: int | None = None):
    if self.party_service is None:
        _message_box().warning(self, "Party Manager", "Open a profile first.")
        return
    return self._show_workspace_panel(
        self._ensure_party_manager_dock,
        panel_attr="party_manager_panel",
        legacy_attr="party_manager_dialog",
        configure=lambda panel: panel.focus_party(party_id),
    )
def _selected_party_manager_ids(self) -> list[int]:
    seen_panel_ids: set[int] = set()
    candidate_panels: list[PartyManagerPanel] = []

    def _append_candidate(panel) -> None:
        if not isinstance(panel, _party_manager_panel_class()):
            return
        panel_id = id(panel)
        if panel_id in seen_panel_ids:
            return
        seen_panel_ids.add(panel_id)
        candidate_panels.append(panel)

    _append_candidate(getattr(self, "party_manager_panel", None))
    dialog = getattr(self, "party_manager_dialog", None)
    _append_candidate(getattr(dialog, "panel", None) if dialog is not None else None)
    dock = getattr(self, "party_manager_dock", None)
    _append_candidate(getattr(dock, "widget", lambda: None)() if dock is not None else None)

    for panel in candidate_panels:
        if not panel.isVisible():
            continue
        selected_ids = panel.selected_party_ids()
        if selected_ids:
            return selected_ids

    for panel in candidate_panels:
        selected_ids = panel.selected_party_ids()
        if selected_ids:
            return selected_ids
    return []
def _party_import_review_summary(report: PartyImportReport) -> list[str]:
    evaluated_mode = str(report.evaluated_mode or report.mode or "dry_run")
    lines = [
        f"Planned mode: {evaluated_mode}",
        f"Rows ready: {report.passed}",
        f"Rows blocked: {report.failed}",
        f"Rows skipped: {report.skipped}",
    ]
    if report.would_create_parties:
        lines.append(f"Would create Parties: {report.would_create_parties}")
    if report.would_update_parties:
        lines.append(f"Would update Parties: {report.would_update_parties}")
    if report.would_set_owner:
        lines.append("Would update the current Owner Party binding.")
    if report.duplicates:
        lines.append(f"Duplicate-safe skips: {len(report.duplicates)}")
    if report.unknown_fields:
        lines.append("Unmapped fields: " + ", ".join(report.unknown_fields[:8]))
    return lines
def _show_party_import_report(self, path: str, report: PartyImportReport) -> None:
    lines = [
        f"Format: {report.format_name.upper()}",
        f"Mode: {report.mode}",
        f"Passed: {report.passed}",
        f"Failed: {report.failed}",
        f"Skipped: {report.skipped}",
    ]
    if report.mode == "dry_run":
        lines.extend(
            [
                "",
                "No database changes were made because this run used Dry run validation mode.",
            ]
        )
        if report.would_create_parties:
            lines.append(f"Would create: {report.would_create_parties}")
        if report.would_update_parties:
            lines.append(f"Would update: {report.would_update_parties}")
        if report.would_set_owner:
            lines.append("Would update the current Owner Party binding.")
    if report.created_parties:
        lines.append(f"Created: {len(report.created_parties)}")
    if report.updated_parties:
        lines.append(f"Updated: {len(report.updated_parties)}")
    if report.owner_party_id is not None:
        lines.append(f"Owner Party: {report.owner_party_id}")
    if report.duplicates:
        lines.append(f"Duplicates: {len(report.duplicates)}")
    if report.unknown_fields:
        lines.append("Unmapped fields: " + ", ".join(report.unknown_fields[:8]))
    if report.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings[:12])
    _message_box().information(
        self,
        "Import Parties",
        "\n".join(lines) + f"\n\nSource:\n{path}",
    )
def import_party_exchange_file(self, format_name: str):
    if self.party_exchange_service is None:
        _message_box().warning(self, "Import Parties", "Open a profile first.")
        return
    normalized_format = str(format_name or "").strip().lower()
    filters = {
        "csv": "CSV Files (*.csv)",
        "xlsx": "Excel Workbook (*.xlsx)",
        "json": "JSON Files (*.json)",
    }
    path, _ = _file_dialog().getOpenFileName(
        self,
        f"Import Parties {normalized_format.upper()}",
        "",
        filters.get(normalized_format, "All files (*)"),
    )
    if not path:
        return

    def _inspection_worker(bundle, ctx):
        ctx.report_progress(
            value=0,
            maximum=100,
            message=f"Inspecting {normalized_format.upper()} Party source file...",
        )
        if normalized_format == "csv":
            return bundle.party_exchange_service.inspect_csv(
                path,
                progress_callback=self._scaled_progress_callback(
                    ctx.report_progress, start=0, end=90
                ),
                cancel_callback=ctx.raise_if_cancelled,
            )
        if normalized_format == "xlsx":
            return bundle.party_exchange_service.inspect_xlsx(
                path,
                progress_callback=self._scaled_progress_callback(
                    ctx.report_progress, start=0, end=90
                ),
                cancel_callback=ctx.raise_if_cancelled,
            )
        if normalized_format == "json":
            return bundle.party_exchange_service.inspect_json(
                path,
                progress_callback=self._scaled_progress_callback(
                    ctx.report_progress, start=0, end=90
                ),
                cancel_callback=ctx.raise_if_cancelled,
            )
        raise ValueError(f"Unsupported Party exchange format: {normalized_format}")

    def _inspection_success(inspection: PartyExchangeInspection):
        def _csv_reinspect(delimiter: str | None) -> PartyExchangeInspection:
            return self.party_exchange_service.inspect_csv(path, delimiter=delimiter)

        dlg = _party_import_dialog_class()(
            inspection=inspection,
            supported_headers=self.party_exchange_service.supported_import_targets(),
            settings=self.settings,
            initial_mode="dry_run",
            csv_reinspect_callback=(_csv_reinspect if normalized_format == "csv" else None),
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        mapping = dlg.mapping()
        options: PartyImportOptions = dlg.import_options()
        selected_csv_delimiter = dlg.resolved_csv_delimiter()

        def _submit_import_task(active_options: PartyImportOptions) -> None:
            def _import_worker(bundle, ctx):
                import_progress = self._scaled_progress_callback(
                    ctx.report_progress,
                    start=0,
                    end=(90 if active_options.mode != "dry_run" else 96),
                )
                ctx.report_progress(
                    value=0,
                    maximum=100,
                    message=(
                        f"Importing {normalized_format.upper()} Parties into the current profile..."
                    ),
                )

                def _mutation():
                    if normalized_format == "csv":
                        return bundle.party_exchange_service.import_csv(
                            path,
                            mapping=mapping,
                            options=active_options,
                            delimiter=selected_csv_delimiter,
                            progress_callback=import_progress,
                            cancel_callback=ctx.raise_if_cancelled,
                        )
                    if normalized_format == "xlsx":
                        return bundle.party_exchange_service.import_xlsx(
                            path,
                            mapping=mapping,
                            options=active_options,
                            progress_callback=import_progress,
                            cancel_callback=ctx.raise_if_cancelled,
                        )
                    return bundle.party_exchange_service.import_json(
                        path,
                        mapping=mapping,
                        options=active_options,
                        progress_callback=import_progress,
                        cancel_callback=ctx.raise_if_cancelled,
                    )

                if active_options.mode == "dry_run":
                    return _mutation()
                return _run_snapshot_history_action(
                    history_manager=bundle.history_manager,
                    action_label=f"Import Parties {normalized_format.upper()}: {Path(path).name}",
                    action_type=f"party.import.{normalized_format}",
                    entity_type="PartyImport",
                    entity_id=path,
                    payload={"path": path, "mode": active_options.mode},
                    mutation=_mutation,
                    progress_callback=ctx.report_progress,
                    post_mutation_progress=(92, "Capturing Party import history snapshot..."),
                    record_progress=(94, "Recording Party import history..."),
                    logger=self.logger,
                )

            def _import_before_cleanup(report: PartyImportReport, ui_progress) -> None:
                changed_ids = list(report.created_parties or []) + list(
                    report.updated_parties or []
                )
                if active_options.mode == "dry_run":
                    self._advance_task_ui_progress(
                        ui_progress,
                        value=100,
                        message="Party import validation complete.",
                    )
                    return
                self._advance_task_ui_progress(
                    ui_progress,
                    value=97,
                    message="Applying imported Party changes...",
                )
                try:
                    self.conn.commit()
                except Exception:
                    pass
                self._advance_task_ui_progress(
                    ui_progress,
                    value=99,
                    message="Refreshing Party views and history...",
                )
                self.populate_all_comboboxes()
                self._refresh_catalog_workspace_docks()
                self._refresh_history_actions()
                if changed_ids:
                    focus_party_id = int(changed_ids[0])
                    panel = getattr(self, "party_manager_panel", None)
                    if isinstance(panel, _party_manager_panel_class()):
                        panel.focus_party(focus_party_id)
                self._advance_task_ui_progress(
                    ui_progress,
                    value=100,
                    message="Party import complete.",
                )

            def _import_success(report: PartyImportReport):
                self._log_event(
                    f"party.import.{normalized_format}",
                    f"Imported {normalized_format.upper()} Party data",
                    path=path,
                    mode=active_options.mode,
                    passed=report.passed,
                    failed=report.failed,
                    skipped=report.skipped,
                    created=len(report.created_parties),
                    updated=len(report.updated_parties),
                    owner_party_id=report.owner_party_id,
                    warnings=report.warnings,
                    duplicates=report.duplicates,
                    unknown_fields=report.unknown_fields,
                )
                self._audit(
                    "IMPORT",
                    "Parties",
                    ref_id=path,
                    details=(
                        f"format={normalized_format}; mode={active_options.mode}; passed={report.passed}; "
                        f"failed={report.failed}; skipped={report.skipped}; "
                        f"created={len(report.created_parties)}; updated={len(report.updated_parties)}"
                    ),
                )
                self._audit_commit()
                self._show_party_import_report(path, report)

            self._submit_background_bundle_task(
                title=f"Import Parties {normalized_format.upper()}",
                description=f"Importing {normalized_format.upper()} Party data into the current profile...",
                task_fn=_import_worker,
                kind=("read" if active_options.mode == "dry_run" else "write"),
                unique_key=f"party.import.{normalized_format}",
                worker_completion_progress=(
                    (96, "Finalizing background Party import...")
                    if active_options.mode != "dry_run"
                    else (100, "Party import validation complete.")
                ),
                on_success_before_cleanup=_import_before_cleanup,
                on_success_after_cleanup=_import_success,
                on_error=lambda failure: self._show_background_task_error(
                    "Import Parties",
                    failure,
                    user_message="Could not complete the Party import:",
                ),
            )

        def _run_preflight_review() -> None:
            preview_options = PartyImportOptions(
                mode="dry_run",
                match_by_internal_id=options.match_by_internal_id,
                match_by_legal_name=options.match_by_legal_name,
                match_by_identity_keys=options.match_by_identity_keys,
                match_by_name_fields=options.match_by_name_fields,
                preview_apply_mode=options.mode,
            )

            def _preview_worker(bundle, ctx):
                preview_progress = self._scaled_progress_callback(
                    ctx.report_progress,
                    start=0,
                    end=96,
                )
                ctx.report_progress(
                    value=0,
                    maximum=100,
                    message="Running Party import dry-run review...",
                )
                if normalized_format == "csv":
                    return bundle.party_exchange_service.import_csv(
                        path,
                        mapping=mapping,
                        options=preview_options,
                        delimiter=selected_csv_delimiter,
                        progress_callback=preview_progress,
                        cancel_callback=ctx.raise_if_cancelled,
                    )
                if normalized_format == "xlsx":
                    return bundle.party_exchange_service.import_xlsx(
                        path,
                        mapping=mapping,
                        options=preview_options,
                        progress_callback=preview_progress,
                        cancel_callback=ctx.raise_if_cancelled,
                    )
                return bundle.party_exchange_service.import_json(
                    path,
                    mapping=mapping,
                    options=preview_options,
                    progress_callback=preview_progress,
                    cancel_callback=ctx.raise_if_cancelled,
                )

            def _preview_success(report: PartyImportReport) -> None:
                accepted = self._open_import_review_dialog(
                    title=f"Review Parties {normalized_format.upper()} Import",
                    subtitle=(
                        "Dry run completed. Review the planned Party changes before anything is written to the current profile."
                    ),
                    summary_lines=self._party_import_review_summary(report),
                    warnings=report.warnings,
                    preview_rows=inspection.preview_rows,
                    preview_headers=inspection.headers,
                    preview_title="Source Preview",
                    confirm_label="Apply Party Import",
                )
                if accepted:
                    _submit_import_task(options)

            self._submit_background_bundle_task(
                title=f"Review Parties {normalized_format.upper()}",
                description="Running a dry-run review of the selected Party import...",
                task_fn=_preview_worker,
                kind="read",
                unique_key=f"party.review.{normalized_format}",
                worker_completion_progress=(100, "Party import review ready."),
                on_success_after_cleanup=_preview_success,
                on_error=lambda failure: self._show_background_task_error(
                    "Import Parties",
                    failure,
                    user_message="Could not review the Party import before apply:",
                ),
            )

        if options.mode == "dry_run":
            _submit_import_task(options)
        else:
            _run_preflight_review()

    self._submit_background_bundle_task(
        title=f"Inspect Parties {normalized_format.upper()}",
        description=f"Inspecting the selected {normalized_format.upper()} Party source...",
        task_fn=_inspection_worker,
        kind="read",
        unique_key=f"party.inspect.{normalized_format}",
        worker_completion_progress=(100, "Party import inspection complete."),
        on_success_after_cleanup=_inspection_success,
        on_error=lambda failure: self._show_background_task_error(
            "Import Parties",
            failure,
            user_message="Could not inspect the selected Party file:",
        ),
    )
def export_party_exchange_file(
    self,
    format_name: str,
    selected_only: bool,
    *,
    party_ids: list[int] | None = None,
):
    if self.party_exchange_service is None:
        _message_box().warning(self, "Export Parties", "Open a profile first.")
        return
    normalized_format = str(format_name or "").strip().lower()
    selected_party_ids = [int(party_id) for party_id in (party_ids or [])]
    if selected_only and not selected_party_ids:
        selected_party_ids = self._selected_party_manager_ids()
    if selected_only and not selected_party_ids:
        _message_box().information(
            self,
            "Export Parties",
            "Select one or more Party rows in Party Manager first.",
        )
        return

    extension_map = {
        "csv": ("CSV Files (*.csv)", ".csv"),
        "xlsx": ("Excel Workbooks (*.xlsx)", ".xlsx"),
        "json": ("JSON Files (*.json)", ".json"),
    }
    file_filter, suffix = extension_map.get(normalized_format, ("All files (*)", ""))
    default_name = (
        f"{'selected_parties' if selected_only else 'party_catalog'}_"
        f"{normalized_format}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"
    )
    path, _ = _file_dialog().getSaveFileName(
        self,
        f"Export Parties {normalized_format.upper()}",
        str(self.exports_dir / default_name),
        file_filter,
    )
    if not path:
        return
    try:
        resolved_path = self._resolve_file_export_target(
            path,
            default_filename=default_name,
        )
    except ValueError as exc:
        _message_box().warning(self, "Export Parties", str(exc))
        return

    export_ids = list(selected_party_ids) if selected_only else None

    def _worker(bundle, ctx):
        export_progress = self._scaled_progress_callback(ctx.report_progress, start=0, end=94)

        def _mutation():
            if normalized_format == "csv":
                return bundle.party_exchange_service.export_csv(
                    resolved_path,
                    export_ids,
                    progress_callback=export_progress,
                )
            if normalized_format == "xlsx":
                return bundle.party_exchange_service.export_xlsx(
                    resolved_path,
                    export_ids,
                    progress_callback=export_progress,
                )
            if normalized_format == "json":
                return bundle.party_exchange_service.export_json(
                    resolved_path,
                    export_ids,
                    progress_callback=export_progress,
                )
            raise ValueError(f"Unsupported Party exchange format: {normalized_format}")

        return _run_file_history_action(
            history_manager=bundle.history_manager,
            action_label=lambda count: f"Export Parties {normalized_format.upper()}: {count} rows",
            action_type=f"file.party_export_{normalized_format}",
            target_path=resolved_path,
            mutation=_mutation,
            entity_type="PartyExport",
            entity_id=str(resolved_path),
            payload=lambda count: {
                "path": str(resolved_path),
                "format": normalized_format,
                "selected_only": bool(selected_only),
                "count": count,
            },
            progress_callback=ctx.report_progress,
            post_mutation_progress=(96, "Capturing Party export history..."),
            record_progress=(98, "Recording Party export history..."),
            logger=self.logger,
        )

    def _success(exported_count: int):
        self._refresh_history_actions()
        self._log_event(
            f"party.export.{normalized_format}",
            f"Exported {normalized_format.upper()} Party data",
            path=str(resolved_path),
            exported=exported_count,
            selected_only=selected_only,
            selected_party_count=len(selected_party_ids) if selected_only else None,
        )
        self._audit(
            "EXPORT",
            "Parties",
            ref_id=str(resolved_path),
            details=f"format={normalized_format}; count={exported_count}; selected_only={int(bool(selected_only))}",
        )
        self._audit_commit()
        _message_box().information(
            self,
            "Export Parties",
            f"Exported {exported_count} Part{'ies' if exported_count != 1 else 'y'} to:\n{resolved_path}",
        )

    self._submit_background_bundle_task(
        title=f"Export Parties {normalized_format.upper()}",
        description=f"Exporting {normalized_format.upper()} Party data...",
        task_fn=_worker,
        kind="read",
        unique_key=f"party.export.{normalized_format}",
        worker_completion_progress=(100, "Party export complete."),
        on_success_after_cleanup=_success,
        on_error=lambda failure: self._show_background_task_error(
            "Export Parties",
            failure,
            user_message="Could not export the selected Party data:",
        ),
    )
def _refresh_party_manager_panel(self) -> None:
    seen_panel_ids: set[int] = set()
    for attr in ("party_manager_panel", "party_manager_dialog"):
        panel = getattr(self, attr, None)
        if panel is None or not panel.isVisible():
            continue
        panel_id = id(panel)
        if panel_id in seen_panel_ids:
            continue
        seen_panel_ids.add(panel_id)
        refresh = getattr(panel, "refresh", None)
        if callable(refresh):
            refresh()
def _redirect_owner_registration_edit_to_party_manager(self, field_label: str) -> None:
    owner_party_id = self._current_owner_party_id()
    if owner_party_id is None:
        _message_box().information(
            self,
            field_label,
            f"{field_label} is edited on the current Owner Party in Party Manager.",
        )
        self.open_party_manager()
        return
    _message_box().information(
        self,
        field_label,
        f"{field_label} is edited on the current Owner Party in Party Manager.",
    )
    self.open_party_manager(owner_party_id)
