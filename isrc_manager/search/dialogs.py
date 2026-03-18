"""Global search and relationship explorer dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _apply_standard_widget_chrome,
    _create_scrollable_dialog_content,
    _create_standard_section,
)

from .models import GlobalSearchResult
from .service import GlobalSearchService, RelationshipExplorerService


class GlobalSearchPanel(QWidget):
    """Search across works, tracks, releases, contracts, rights, parties, documents, and assets."""

    open_entity_requested = Signal(str, int)

    def __init__(
        self,
        *,
        search_service_provider,
        relationship_service_provider,
        parent=None,
    ):
        super().__init__(parent)
        self.search_service_provider = search_service_provider
        self.relationship_service_provider = relationship_service_provider
        self.setObjectName("globalSearchPanel")
        _apply_standard_widget_chrome(self, "globalSearchPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title="Global Search and Relationship Explorer",
            subtitle=(
                "Search the complete catalog knowledge graph and inspect everything linked "
                "to the selected record from one place."
            ),
        )

        search_box, search_box_layout = _create_standard_section(
            self,
            "Search Query",
            "Filter across all supported entities or narrow the search to a specific entity type.",
        )
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search works, tracks, releases, contracts, rights, parties, documents, and assets..."
        )
        self.search_edit.textChanged.connect(self.refresh_results)
        self.entity_combo = QComboBox()
        self.entity_combo.addItems(
            [
                "All Entities",
                "Works",
                "Tracks",
                "Releases",
                "Contracts",
                "Rights",
                "Parties",
                "Documents",
                "Assets",
            ]
        )
        self.entity_combo.currentIndexChanged.connect(self.refresh_results)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.entity_combo)
        self.save_search_button = QPushButton("Save Search")
        self.save_search_button.clicked.connect(self.save_current_search)
        search_row.addWidget(self.save_search_button)
        search_box_layout.addLayout(search_row)
        self.results_status_label = QLabel("Enter a query to search the catalog.")
        self.results_status_label.setProperty("role", "secondary")
        self.results_status_label.setWordWrap(True)
        search_box_layout.addWidget(self.results_status_label)
        root.addWidget(search_box)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        self.saved_searches_scroll_area, _, left_content_layout = _create_scrollable_dialog_content(
            splitter
        )
        self.saved_searches_scroll_area.setObjectName("globalSearchSavedSearchesScrollArea")
        saved_box, saved_layout = _create_standard_section(
            self,
            "Saved Searches",
            "Store useful queries and quickly re-apply them later.",
        )
        self.saved_searches_list = QListWidget(saved_box)
        self.saved_searches_list.itemDoubleClicked.connect(self.apply_saved_search)
        saved_layout.addWidget(self.saved_searches_list, 1)
        self.delete_saved_button = QPushButton("Delete Saved Search")
        self.delete_saved_button.clicked.connect(self.delete_saved_search)
        saved_layout.addWidget(self.delete_saved_button)
        left_content_layout.addWidget(saved_box)
        left_content_layout.addStretch(1)
        splitter.addWidget(self.saved_searches_scroll_area)

        right_container = QWidget(self)
        right_container.setProperty("role", "workspaceCanvas")
        self.right_container = right_container
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        detail_tabs = QTabWidget(right_container)
        right_layout.addWidget(detail_tabs, 1)

        results_tab = QWidget(detail_tabs)
        results_tab.setProperty("role", "workspaceCanvas")
        self.results_tab = results_tab
        results_tab_layout = QVBoxLayout(results_tab)
        results_tab_layout.setContentsMargins(0, 0, 0, 0)
        results_tab_layout.setSpacing(0)
        results_box, results_box_layout = _create_standard_section(
            self,
            "Search Results",
            "Select a row to inspect linked records or double-click to open the selected item.",
        )
        self.results_table = QTableWidget(0, 5, results_box)
        self.results_table.setHorizontalHeaderLabels(["Type", "ID", "Title", "Subtitle", "Status"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.results_table.itemSelectionChanged.connect(self.refresh_relationships)
        self.results_table.doubleClicked.connect(lambda _index: self.open_selected_result())
        results_box_layout.addWidget(self.results_table, 1)
        open_button = QPushButton("Open Selected Record")
        open_button.clicked.connect(self.open_selected_result)
        results_box_layout.addWidget(open_button)
        results_tab_layout.addWidget(results_box, 1)
        detail_tabs.addTab(results_tab, "Results")

        relationships_tab = QWidget(detail_tabs)
        relationships_tab.setProperty("role", "workspaceCanvas")
        self.relationships_tab = relationships_tab
        relationships_tab_layout = QVBoxLayout(relationships_tab)
        relationships_tab_layout.setContentsMargins(0, 0, 0, 0)
        relationships_tab_layout.setSpacing(0)
        relationships_box, relationships_box_layout = _create_standard_section(
            self,
            "Relationship Explorer",
            "Everything currently linked to the selected result appears here.",
        )
        self.relationship_summary_label = QLabel("Select a result to inspect its links.")
        self.relationship_summary_label.setProperty("role", "secondary")
        self.relationship_summary_label.setWordWrap(True)
        relationships_box_layout.addWidget(self.relationship_summary_label)
        self.relationships_edit = QPlainTextEdit()
        self.relationships_edit.setReadOnly(True)
        relationships_box_layout.addWidget(self.relationships_edit, 1)
        relationships_tab_layout.addWidget(relationships_box, 1)
        detail_tabs.addTab(relationships_tab, "Relationships")

        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)

        _apply_compact_dialog_control_heights(self)
        self.refresh_saved_searches()
        self.refresh_results()

    def _search_service(self) -> GlobalSearchService | None:
        service = self.search_service_provider()
        return service

    def _relationship_service(self) -> RelationshipExplorerService | None:
        service = self.relationship_service_provider()
        return service

    def _entity_filter(self) -> list[str] | None:
        mapping = {
            "Works": ["work"],
            "Tracks": ["track"],
            "Releases": ["release"],
            "Contracts": ["contract"],
            "Rights": ["right"],
            "Parties": ["party"],
            "Documents": ["document"],
            "Assets": ["asset"],
        }
        return mapping.get(self.entity_combo.currentText())

    def _entity_filter_label(self) -> str | None:
        mapping = {
            "Works": "work",
            "Tracks": "track",
            "Releases": "release",
            "Contracts": "contract",
            "Rights": "right",
            "Parties": "party",
            "Documents": "document",
            "Assets": "asset",
        }
        return mapping.get(self.entity_combo.currentText())

    @staticmethod
    def _pluralize_entity(entity_type: str) -> str:
        mapping = {
            "work": "works",
            "track": "tracks",
            "release": "releases",
            "contract": "contracts",
            "right": "rights",
            "party": "parties",
            "document": "documents",
            "asset": "assets",
        }
        return mapping.get(entity_type, entity_type + "s")

    def _default_status_text(self, *, query: str, results: list[GlobalSearchResult]) -> str:
        if query:
            return (
                f"Showing {len(results)} search result{'s' if len(results) != 1 else ''} "
                f"for '{query}'."
                if results
                else f"No results found for '{query}'."
            )

        entity_filter = self._entity_filter_label()
        if not results:
            if entity_filter is None:
                return "No catalog records are available yet. Type to search once data is added."
            return (
                f"No {self._pluralize_entity(entity_filter)} are available yet. "
                "Type to search once data is added."
            )

        if entity_filter is not None:
            count = len(results)
            return f"Showing {count} {entity_filter} preview{'s' if count != 1 else ''}. Type to narrow results."

        counts: dict[str, int] = {}
        for result in results:
            counts[result.entity_type] = counts.get(result.entity_type, 0) + 1
        ordered_types = [
            "work",
            "track",
            "release",
            "contract",
            "right",
            "party",
            "document",
            "asset",
        ]
        preview_parts = [
            f"{counts[entity_type]} {self._pluralize_entity(entity_type)}"
            for entity_type in ordered_types
            if entity_type in counts
        ]
        if len(preview_parts) > 4:
            preview_text = (
                ", ".join(preview_parts[:4]) + f", and {len(preview_parts) - 4} more types"
            )
        else:
            preview_text = ", ".join(preview_parts)
        return f"Showing catalog overview: {preview_text}. Type to narrow results."

    def _browse_results(self, service: GlobalSearchService) -> list[GlobalSearchResult]:
        entity_filter = self._entity_filter()
        if entity_filter is None:
            return service.browse_default_view(limit=200, preview_limit=8)
        return service.browse_default_view(
            entity_types=entity_filter,
            limit=200,
            preview_limit=24,
        )

    def _clear_result_selection(self) -> None:
        self.results_table.clearSelection()
        selection_model = self.results_table.selectionModel()
        if selection_model is not None:
            try:
                selection_model.clearCurrentIndex()
            except Exception:
                pass

    def refresh_saved_searches(self) -> None:
        self.saved_searches_list.clear()
        service = self._search_service()
        if service is None:
            return
        for saved in service.list_saved_searches():
            item_text = f"{saved.name} | {saved.query_text}"
            self.saved_searches_list.addItem(item_text)
            self.saved_searches_list.item(self.saved_searches_list.count() - 1).setData(
                Qt.UserRole, saved.id
            )
            self.saved_searches_list.item(self.saved_searches_list.count() - 1).setData(
                Qt.UserRole + 1, saved.query_text
            )
            self.saved_searches_list.item(self.saved_searches_list.count() - 1).setData(
                Qt.UserRole + 2, saved.entity_types
            )

    def refresh_results(self) -> None:
        service = self._search_service()
        if service is None:
            self.results_table.setRowCount(0)
            self.results_status_label.setText(
                "Open a profile first to search or browse the catalog."
            )
            self._clear_result_selection()
            self.refresh_relationships()
            return
        query = self.search_edit.text().strip()
        if query:
            results = service.search(
                query,
                entity_types=self._entity_filter(),
                limit=200,
            )
        else:
            results = self._browse_results(service)
        self.results_table.setRowCount(0)
        for result in results:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            values = [
                result.entity_type.title(),
                str(result.entity_id),
                result.title,
                result.subtitle,
                result.status or "",
            ]
            for column, value in enumerate(values):
                self.results_table.setItem(row, column, QTableWidgetItem(value))
        self._clear_result_selection()
        self.results_status_label.setText(self._default_status_text(query=query, results=results))
        self.refresh_relationships()

    def _selected_result(self) -> tuple[str, int] | None:
        rows = self.results_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        entity_type_item = self.results_table.item(row, 0)
        entity_id_item = self.results_table.item(row, 1)
        if entity_type_item is None or entity_id_item is None:
            return None
        return entity_type_item.text().strip().lower(), int(entity_id_item.text())

    def refresh_relationships(self) -> None:
        selected = self._selected_result()
        if selected is None:
            self.relationship_summary_label.setText("Select a result to inspect its links.")
            self.relationships_edit.setPlainText("Select a result to inspect its links.")
            return
        entity_type, entity_id = selected
        relationship_service = self._relationship_service()
        if relationship_service is None:
            self.relationship_summary_label.setText("Open a profile first to inspect links.")
            self.relationships_edit.setPlainText("Open a profile first to inspect links.")
            return
        self.relationship_summary_label.setText(
            f"Showing links for {entity_type.title()} #{entity_id}."
        )
        sections = relationship_service.describe_links(entity_type, entity_id)
        if not sections:
            self.relationships_edit.setPlainText("No linked records found.")
            return
        lines: list[str] = []
        for section in sections:
            if not section.results:
                continue
            lines.append(section.section_title)
            for result in section.results:
                subtitle = f" ({result.subtitle})" if result.subtitle else ""
                status = f" [{result.status}]" if result.status else ""
                lines.append(
                    f"  - {result.entity_type.title()} #{result.entity_id}: {result.title}{subtitle}{status}"
                )
            lines.append("")
        self.relationships_edit.setPlainText("\n".join(lines).strip())

    def open_selected_result(self) -> None:
        selected = self._selected_result()
        if selected is None:
            QMessageBox.information(self, "Global Search", "Select a result first.")
            return
        self.open_entity_requested.emit(selected[0], selected[1])

    def save_current_search(self) -> None:
        service = self._search_service()
        if service is None:
            QMessageBox.warning(self, "Global Search", "Open a profile first.")
            return
        query = self.search_edit.text().strip()
        if not query:
            QMessageBox.information(self, "Global Search", "Enter a query first.")
            return
        name = query if len(query) <= 40 else query[:40]
        try:
            service.save_search(name, query, self._entity_filter())
        except Exception as exc:
            QMessageBox.critical(self, "Global Search", str(exc))
            return
        self.refresh_saved_searches()

    def apply_saved_search(self, _item=None) -> None:
        item = self.saved_searches_list.currentItem()
        if item is None:
            return
        self.search_edit.setText(str(item.data(Qt.UserRole + 1) or ""))
        entity_types = item.data(Qt.UserRole + 2) or []
        if not entity_types:
            self.entity_combo.setCurrentText("All Entities")
        else:
            reverse_mapping = {
                ("work",): "Works",
                ("track",): "Tracks",
                ("release",): "Releases",
                ("contract",): "Contracts",
                ("right",): "Rights",
                ("party",): "Parties",
                ("document",): "Documents",
                ("asset",): "Assets",
            }
            self.entity_combo.setCurrentText(
                reverse_mapping.get(tuple(entity_types), "All Entities")
            )
        self.refresh_results()

    def delete_saved_search(self) -> None:
        service = self._search_service()
        if service is None:
            QMessageBox.warning(self, "Global Search", "Open a profile first.")
            return
        item = self.saved_searches_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Global Search", "Select a saved search first.")
            return
        service.delete_saved_search(int(item.data(Qt.UserRole)))
        self.refresh_saved_searches()


class GlobalSearchDialog(QDialog):
    """Compatibility dialog wrapper around the reusable global search panel."""

    open_entity_requested = Signal(str, int)

    def __init__(
        self,
        *,
        search_service: GlobalSearchService,
        relationship_service: RelationshipExplorerService,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Global Search and Relationship Explorer")
        self.resize(1180, 760)
        self.setMinimumSize(1040, 680)
        _apply_standard_dialog_chrome(self, "globalSearchDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.panel = GlobalSearchPanel(
            search_service_provider=lambda: search_service,
            relationship_service_provider=lambda: relationship_service,
            parent=self,
        )
        self.panel.open_entity_requested.connect(self.open_entity_requested.emit)
        root.addWidget(self.panel)

    def __getattr__(self, name: str):
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            return getattr(panel, name)
        raise AttributeError(name)
