"""Themed workspace panel for the Bandcamp promo-code ledger."""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path

from PySide6.QtCore import QModelIndex, QObject, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.ui_common import (
    FocusWheelComboBox,
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_widget_chrome,
    _configure_standard_form_layout,
    _create_standard_section,
)

from .models import PromoCodeImportResult, PromoCodeRecord, PromoCodeSheetRecord
from .service import PromoCodeService

_CODE_ID_ROLE = int(Qt.ItemDataRole.UserRole) + 701
_REDEEMED_ROLE = _CODE_ID_ROLE + 1
_SEARCH_TEXT_ROLE = _CODE_ID_ROLE + 2
_SORT_ROLE = _CODE_ID_ROLE + 3


def _clean_search_text(value: str | None) -> str:
    return " ".join(str(value or "").casefold().split())


def _search_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9@._-]+", value) if token]


class _PromoCodeFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._search_text = ""
        self._status_filter = "available"
        self.setDynamicSortFilter(True)
        self.setSortRole(_SORT_ROLE)

    def set_search_text(self, value: str | None) -> None:
        clean = _clean_search_text(value)
        if clean == self._search_text:
            return
        self._search_text = clean
        self._invalidate_rows()

    def set_status_filter(self, value: str | None) -> None:
        clean = str(value or "available").strip().casefold()
        if clean not in {"all", "available", "redeemed"}:
            clean = "available"
        if clean == self._status_filter:
            return
        self._status_filter = clean
        self._invalidate_rows()

    def _invalidate_rows(self) -> None:
        begin_filter_change = getattr(self, "beginFilterChange", None)
        end_filter_change = getattr(self, "endFilterChange", None)
        direction = getattr(getattr(QSortFilterProxyModel, "Direction", None), "Rows", None)
        if callable(begin_filter_change) and callable(end_filter_change) and direction is not None:
            begin_filter_change()
            end_filter_change(direction)
            return
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return False
        first_index = model.index(source_row, 0, source_parent)
        redeemed = bool(model.data(first_index, _REDEEMED_ROLE))
        if self._status_filter == "available" and redeemed:
            return False
        if self._status_filter == "redeemed" and not redeemed:
            return False
        if not self._search_text:
            return True
        search_blob = _clean_search_text(str(model.data(first_index, _SEARCH_TEXT_ROLE) or ""))
        if not search_blob:
            return False
        terms = [term for term in self._search_text.split() if term]
        if terms and all(term in search_blob for term in terms):
            return True
        tokens = _search_tokens(search_blob)
        if terms and tokens:
            fuzzy_terms_matched = 0
            for term in terms:
                if any(term in token for token in tokens):
                    fuzzy_terms_matched += 1
                    continue
                best_token_score = max(
                    (SequenceMatcher(None, term, token).ratio() for token in tokens),
                    default=0.0,
                )
                if best_token_score >= 0.72:
                    fuzzy_terms_matched += 1
            if fuzzy_terms_matched == len(terms):
                return True
        if len(self._search_text) < 3:
            return False
        return SequenceMatcher(None, self._search_text, search_blob).ratio() >= 0.42

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_value = left.data(self.sortRole())
        right_value = right.data(self.sortRole())
        if left_value != right_value:
            return left_value < right_value
        return left.row() < right.row()


class PromoCodeLedgerPanel(QWidget):
    close_requested = Signal()

    def __init__(
        self,
        *,
        service_provider: Callable[[], PromoCodeService | None],
        import_handler: (
            Callable[[str, QWidget | None, Callable[[PromoCodeImportResult], None] | None], object]
            | None
        ) = None,
        ledger_update_handler: (
            Callable[[int, bool, str | None, str | None, str | None], PromoCodeRecord] | None
        ) = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service_provider = service_provider
        self.import_handler = import_handler
        self.ledger_update_handler = ledger_update_handler
        self._sheet_rows: list[PromoCodeSheetRecord] = []
        self._code_rows_by_id: dict[int, PromoCodeRecord] = {}
        self._current_sheet_id: int | None = None
        self._suspend_selection_sync = False
        _apply_standard_widget_chrome(
            self,
            "promoCodeLedgerPanel",
            extra_qss="""
            QWidget#promoCodeLedgerPanel QPlainTextEdit {
                min-height: 90px;
            }
            """,
        )
        self._build_ui()
        self.refresh()

    def _service(self) -> PromoCodeService | None:
        try:
            return self.service_provider()
        except Exception:
            return None

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title="Promo Code Ledger",
            subtitle="Import Bandcamp promo-code sheets and track who received each code.",
        )

        sheet_box, sheet_layout = _create_standard_section(self, "Code Sheet")
        sheet_row = QHBoxLayout()
        sheet_row.setContentsMargins(0, 0, 0, 0)
        sheet_row.setSpacing(8)
        self.sheet_combo = FocusWheelComboBox(self)
        self.sheet_combo.currentIndexChanged.connect(self._on_sheet_changed)
        sheet_row.addWidget(self.sheet_combo, 1)
        self.import_button = QPushButton("Import or Update CSV...", self)
        self.import_button.clicked.connect(self._choose_import_file)
        sheet_row.addWidget(self.import_button)
        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.clicked.connect(self.refresh)
        sheet_row.addWidget(self.refresh_button)
        sheet_layout.addLayout(sheet_row)
        self.sheet_detail_label = QLabel("", self)
        self.sheet_detail_label.setProperty("role", "supportingText")
        self.sheet_detail_label.setWordWrap(True)
        sheet_layout.addWidget(self.sheet_detail_label)
        root.addWidget(sheet_box)

        filter_box, filter_layout = _create_standard_section(self, "Find Codes")
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(8)
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Fuzzy search code, recipient, email, or notes...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.search_edit, 1)
        self.status_combo = FocusWheelComboBox(self)
        self.status_combo.addItem("Available", "available")
        self.status_combo.addItem("Redeemed", "redeemed")
        self.status_combo.addItem("All", "all")
        self.status_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.status_combo)
        filter_layout.addLayout(filter_row)
        root.addWidget(filter_box)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_table_panel())
        splitter.addWidget(self._build_ledger_editor())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self.status_label = QLabel("", self)
        self.status_label.setProperty("role", "supportingText")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        _apply_compact_dialog_control_heights(self)

    def _build_table_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(
            ["Status", "Code", "Recipient", "Email", "Redeemed At", "Notes"]
        )
        self.proxy = _PromoCodeFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView(panel)
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._open_table_context_menu)
        selection_model = self.table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(
                lambda *_args: self._on_code_selection_changed()
            )
        layout.addWidget(self.table, 1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self.copy_button = QPushButton("Copy Code", panel)
        self.copy_button.clicked.connect(self.copy_selected_code)
        self.mark_redeemed_button = QPushButton("Mark Redeemed", panel)
        self.mark_redeemed_button.clicked.connect(lambda: self._save_selected_code(redeemed=True))
        self.mark_available_button = QPushButton("Mark Available", panel)
        self.mark_available_button.clicked.connect(lambda: self._save_selected_code(redeemed=False))
        button_row.addWidget(self.copy_button)
        button_row.addWidget(self.mark_redeemed_button)
        button_row.addWidget(self.mark_available_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return panel

    def _build_ledger_editor(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        editor_box, editor_layout = _create_standard_section(panel, "Ledger")
        self.selected_code_label = QLabel("No code selected", editor_box)
        self.selected_code_label.setProperty("role", "sectionDescription")
        self.selected_code_label.setWordWrap(True)
        editor_layout.addWidget(self.selected_code_label)

        form = QFormLayout()
        _configure_standard_form_layout(form)
        self.recipient_name_edit = QLineEdit(editor_box)
        self.recipient_email_edit = QLineEdit(editor_box)
        self.redeemed_check = QCheckBox("Redeemed", editor_box)
        self.notes_edit = QPlainTextEdit(editor_box)
        self.notes_edit.setPlaceholderText("Ledger notes")
        form.addRow("Name", self.recipient_name_edit)
        form.addRow("Email", self.recipient_email_edit)
        form.addRow("Status", self.redeemed_check)
        form.addRow("Notes", self.notes_edit)
        editor_layout.addLayout(form)

        save_row = QHBoxLayout()
        save_row.setContentsMargins(0, 0, 0, 0)
        save_row.addStretch(1)
        self.save_ledger_button = QPushButton("Save Ledger", editor_box)
        self.save_ledger_button.clicked.connect(lambda: self._save_selected_code())
        save_row.addWidget(self.save_ledger_button)
        editor_layout.addLayout(save_row)
        layout.addWidget(editor_box)
        layout.addStretch(1)
        return panel

    def refresh(self) -> None:
        service = self._service()
        previous_sheet_id = self.current_sheet_id()
        self._sheet_rows = []
        self.sheet_combo.blockSignals(True)
        try:
            self.sheet_combo.clear()
            if service is None:
                self.sheet_combo.addItem("Open a profile first", None)
                self._set_empty_codes("Promo code service is unavailable.")
                return
            self._sheet_rows = service.list_sheets()
            if not self._sheet_rows:
                self.sheet_combo.addItem("No promo-code sheets imported", None)
                self._set_empty_codes("No Bandcamp promo-code sheets have been imported yet.")
                return
            for sheet in self._sheet_rows:
                self.sheet_combo.addItem(sheet.display_name, int(sheet.id))
            target_index = 0
            if previous_sheet_id is not None:
                found = self.sheet_combo.findData(int(previous_sheet_id))
                if found >= 0:
                    target_index = found
            self.sheet_combo.setCurrentIndex(target_index)
        finally:
            self.sheet_combo.blockSignals(False)
        self._load_current_sheet()

    def current_sheet_id(self) -> int | None:
        sheet_id = self.sheet_combo.currentData()
        try:
            return int(sheet_id) if sheet_id is not None else None
        except (TypeError, ValueError):
            return None

    def _on_sheet_changed(self, _index: int | None = None) -> None:
        self._load_current_sheet()

    def _load_current_sheet(self) -> None:
        service = self._service()
        sheet_id = self.current_sheet_id()
        self._current_sheet_id = sheet_id
        if service is None or sheet_id is None:
            self._set_empty_codes("Choose or import a promo-code sheet.")
            return
        sheet = next((item for item in self._sheet_rows if int(item.id) == int(sheet_id)), None)
        if sheet is not None:
            self.sheet_detail_label.setText(self._sheet_summary(sheet))
        try:
            codes = service.list_codes(sheet_id)
        except Exception as exc:
            QMessageBox.critical(self, "Promo Code Ledger", str(exc))
            self._set_empty_codes("Could not load promo-code rows.")
            return
        self._populate_codes(codes)

    def _sheet_summary(self, sheet: PromoCodeSheetRecord) -> str:
        parts = [
            f"{sheet.total_codes} total",
            f"{sheet.available_codes} available",
            f"{sheet.redeemed_codes} redeemed",
        ]
        if sheet.bandcamp_date_created:
            parts.append(f"created {sheet.bandcamp_date_created}")
        if sheet.bandcamp_date_exported:
            parts.append(f"exported {sheet.bandcamp_date_exported}")
        bandcamp_parts: list[str] = []
        if sheet.quantity_created is not None:
            bandcamp_parts.append(f"{sheet.quantity_created} created")
        if sheet.quantity_redeemed_to_date is not None:
            bandcamp_parts.append(f"{sheet.quantity_redeemed_to_date} redeemed on Bandcamp")
        if bandcamp_parts:
            parts.append("Bandcamp: " + ", ".join(bandcamp_parts))
        if sheet.redeem_url:
            parts.append(sheet.redeem_url)
        return " | ".join(parts)

    def _set_empty_codes(self, message: str) -> None:
        self.model.removeRows(0, self.model.rowCount())
        self._code_rows_by_id = {}
        self.sheet_detail_label.setText("")
        self.status_label.setText(str(message or ""))
        self._sync_editor(None)
        self._sync_actions()

    def _populate_codes(self, codes: list[PromoCodeRecord]) -> None:
        self._code_rows_by_id = {int(code.id): code for code in codes}
        self.model.removeRows(0, self.model.rowCount())
        for code in codes:
            status_text = "Redeemed" if code.redeemed else "Available"
            row_items = [
                QStandardItem(status_text),
                QStandardItem(code.code),
                QStandardItem(code.recipient_name or ""),
                QStandardItem(code.recipient_email or ""),
                QStandardItem(code.redeemed_at or ""),
                QStandardItem(code.ledger_notes or ""),
            ]
            search_text = " ".join(
                item
                for item in (
                    status_text,
                    code.code,
                    code.recipient_name,
                    code.recipient_email,
                    code.ledger_notes,
                    code.provided_at,
                    code.redeemed_at,
                )
                if item
            )
            for column, item in enumerate(row_items):
                item.setEditable(False)
                item.setData(int(code.id), _CODE_ID_ROLE)
                item.setData(bool(code.redeemed), _REDEEMED_ROLE)
                item.setData(search_text, _SEARCH_TEXT_ROLE)
                if column == 0:
                    item.setData(1 if code.redeemed else 0, _SORT_ROLE)
                elif column == 1:
                    item.setData(int(code.sort_order), _SORT_ROLE)
                else:
                    item.setData(str(item.text() or "").casefold(), _SORT_ROLE)
            self.model.appendRow(row_items)
        self._apply_filters()
        self.table.resizeColumnsToContents()
        if self.proxy.rowCount() > 0:
            self.table.selectRow(0)
        else:
            self._sync_editor(None)
        self._sync_actions()
        self._refresh_visible_count_label()

    def _apply_filters(self) -> None:
        self.proxy.set_search_text(self.search_edit.text())
        self.proxy.set_status_filter(str(self.status_combo.currentData() or "available"))
        self._refresh_visible_count_label()
        self._sync_actions()

    def _refresh_visible_count_label(self) -> None:
        total = self.model.rowCount()
        visible = self.proxy.rowCount()
        self.status_label.setText(f"Showing {visible} of {total} code(s).")

    def _selected_code_id(self) -> int | None:
        index = self.table.currentIndex()
        if not index.isValid():
            selection_model = self.table.selectionModel()
            if selection_model is not None and selection_model.selectedRows():
                index = selection_model.selectedRows()[0]
        if not index.isValid():
            return None
        source_index = self.proxy.mapToSource(index)
        if not source_index.isValid():
            return None
        code_id = self.model.data(self.model.index(source_index.row(), 0), _CODE_ID_ROLE)
        try:
            return int(code_id)
        except (TypeError, ValueError):
            return None

    def _selected_code(self) -> PromoCodeRecord | None:
        code_id = self._selected_code_id()
        if code_id is None:
            return None
        return self._code_rows_by_id.get(int(code_id))

    def _on_code_selection_changed(self) -> None:
        if self._suspend_selection_sync:
            return
        self._sync_editor(self._selected_code())
        self._sync_actions()

    def _sync_editor(self, code: PromoCodeRecord | None) -> None:
        self._suspend_selection_sync = True
        try:
            enabled = code is not None
            for widget in (
                self.recipient_name_edit,
                self.recipient_email_edit,
                self.redeemed_check,
                self.notes_edit,
                self.save_ledger_button,
            ):
                widget.setEnabled(enabled)
            if code is None:
                self.selected_code_label.setText("No code selected")
                self.recipient_name_edit.clear()
                self.recipient_email_edit.clear()
                self.redeemed_check.setChecked(False)
                self.notes_edit.clear()
                return
            self.selected_code_label.setText(code.code)
            self.recipient_name_edit.setText(code.recipient_name or "")
            self.recipient_email_edit.setText(code.recipient_email or "")
            self.redeemed_check.setChecked(bool(code.redeemed))
            self.notes_edit.setPlainText(code.ledger_notes or "")
        finally:
            self._suspend_selection_sync = False

    def _sync_actions(self) -> None:
        has_code = self._selected_code_id() is not None
        for button in (
            self.copy_button,
            self.mark_redeemed_button,
            self.mark_available_button,
            self.save_ledger_button,
        ):
            button.setEnabled(has_code)

    def _choose_import_file(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import or Update Bandcamp Promo Codes",
            str(Path.home()),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        if self.import_handler is None:
            QMessageBox.warning(self, "Promo Code Ledger", "Import is unavailable.")
            return
        self.import_handler(path, self, self._handle_import_complete)

    def _handle_import_complete(self, result: PromoCodeImportResult) -> None:
        self.refresh()
        index = self.sheet_combo.findData(int(result.sheet_id))
        if index >= 0:
            self.sheet_combo.setCurrentIndex(index)
        if result.updated_existing_sheet:
            changes: list[str] = []
            if result.marked_redeemed_codes:
                changes.append(f"{result.marked_redeemed_codes} marked redeemed")
            if result.inserted_codes:
                changes.append(f"{result.inserted_codes} new")
            if result.reactivated_codes:
                changes.append(f"{result.reactivated_codes} reactivated")
            change_summary = ", ".join(changes) if changes else "no status changes"
            self.status_label.setText(
                f"Updated '{result.sheet_name}': {result.active_codes} active code(s), "
                f"{change_summary}."
            )
        else:
            self.status_label.setText(
                f"Imported '{result.sheet_name}' with {result.inserted_codes} code(s)."
            )

    def copy_selected_code(self) -> None:
        code = self._selected_code()
        if code is None:
            return
        app = QApplication.instance()
        if app is not None and app.clipboard() is not None:
            app.clipboard().setText(code.code)
        self.status_label.setText(f"Copied code {code.code}.")

    def _save_selected_code(self, redeemed: bool | None = None) -> None:
        service = self._service()
        code_id = self._selected_code_id()
        if service is None or code_id is None:
            return
        redeemed_value = self.redeemed_check.isChecked() if redeemed is None else bool(redeemed)
        try:
            if self.ledger_update_handler is not None:
                updated = self.ledger_update_handler(
                    int(code_id),
                    redeemed_value,
                    self.recipient_name_edit.text(),
                    self.recipient_email_edit.text(),
                    self.notes_edit.toPlainText(),
                )
            else:
                updated = service.update_code_ledger(
                    int(code_id),
                    redeemed=redeemed_value,
                    recipient_name=self.recipient_name_edit.text(),
                    recipient_email=self.recipient_email_edit.text(),
                    ledger_notes=self.notes_edit.toPlainText(),
                )
        except Exception as exc:
            QMessageBox.critical(self, "Promo Code Ledger", str(exc))
            return
        self._replace_code_row(updated)
        self._sync_editor(updated)
        self.status_label.setText(f"Updated code {updated.code}.")
        self._refresh_current_sheet_summary()

    def _replace_code_row(self, updated: PromoCodeRecord) -> None:
        self._code_rows_by_id[int(updated.id)] = updated
        for row in range(self.model.rowCount()):
            code_id = self.model.data(self.model.index(row, 0), _CODE_ID_ROLE)
            if int(code_id or 0) != int(updated.id):
                continue
            values = [
                "Redeemed" if updated.redeemed else "Available",
                updated.code,
                updated.recipient_name or "",
                updated.recipient_email or "",
                updated.redeemed_at or "",
                updated.ledger_notes or "",
            ]
            search_text = " ".join(
                item
                for item in (
                    values[0],
                    updated.code,
                    updated.recipient_name,
                    updated.recipient_email,
                    updated.ledger_notes,
                    updated.provided_at,
                    updated.redeemed_at,
                )
                if item
            )
            for column, value in enumerate(values):
                item = self.model.item(row, column)
                if item is None:
                    continue
                item.setText(value)
                item.setData(bool(updated.redeemed), _REDEEMED_ROLE)
                item.setData(search_text, _SEARCH_TEXT_ROLE)
                if column == 0:
                    item.setData(1 if updated.redeemed else 0, _SORT_ROLE)
                elif column == 1:
                    item.setData(int(updated.sort_order), _SORT_ROLE)
                else:
                    item.setData(str(value or "").casefold(), _SORT_ROLE)
            break
        self._apply_filters()
        self._restore_selection(updated.id)

    def _restore_selection(self, code_id: int) -> None:
        for row in range(self.proxy.rowCount()):
            source_index = self.proxy.mapToSource(self.proxy.index(row, 0))
            current_id = self.model.data(self.model.index(source_index.row(), 0), _CODE_ID_ROLE)
            if int(current_id or 0) == int(code_id):
                self.table.selectRow(row)
                return
        self.table.clearSelection()
        self._sync_editor(None)
        self._sync_actions()

    def _refresh_current_sheet_summary(self) -> None:
        service = self._service()
        sheet_id = self.current_sheet_id()
        if service is None or sheet_id is None:
            return
        self._sheet_rows = service.list_sheets()
        sheet = next((item for item in self._sheet_rows if int(item.id) == int(sheet_id)), None)
        if sheet is not None:
            self.sheet_detail_label.setText(self._sheet_summary(sheet))

    def _open_table_context_menu(self, pos) -> None:
        code = self._selected_code()
        if code is None:
            return
        menu = QMenu(self)
        copy_action = QAction("Copy Code", menu)
        copy_action.triggered.connect(self.copy_selected_code)
        mark_redeemed_action = QAction("Mark Redeemed", menu)
        mark_redeemed_action.triggered.connect(lambda: self._save_selected_code(redeemed=True))
        mark_available_action = QAction("Mark Available", menu)
        mark_available_action.triggered.connect(lambda: self._save_selected_code(redeemed=False))
        menu.addAction(copy_action)
        menu.addSeparator()
        menu.addAction(mark_redeemed_action)
        menu.addAction(mark_available_action)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def focus_sheet(self, sheet_id: int | None) -> None:
        if sheet_id is None:
            return
        index = self.sheet_combo.findData(int(sheet_id))
        if index >= 0:
            self.sheet_combo.setCurrentIndex(index)
