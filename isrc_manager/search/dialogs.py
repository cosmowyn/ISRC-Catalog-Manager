"""Global search and relationship explorer dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .service import GlobalSearchService, RelationshipExplorerService


class GlobalSearchDialog(QDialog):
    """Search across works, tracks, releases, contracts, rights, parties, documents, and assets."""

    open_entity_requested = Signal(str, int)

    def __init__(
        self,
        *,
        search_service: GlobalSearchService,
        relationship_service: RelationshipExplorerService,
        parent=None,
    ):
        super().__init__(parent)
        self.search_service = search_service
        self.relationship_service = relationship_service
        self.setWindowTitle("Global Search and Relationship Explorer")
        self.resize(1120, 700)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Search the complete catalog knowledge graph and inspect everything linked to the selected record from one place."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        search_row = QHBoxLayout()
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
        save_search_button = QPushButton("Save Search")
        save_search_button.clicked.connect(self.save_current_search)
        search_row.addWidget(save_search_button)
        root.addLayout(search_row)

        splitter = QSplitter(Qt.Horizontal, self)
        root.addWidget(splitter, 1)

        left_widget = QListWidget()
        self.saved_searches_list = left_widget
        self.saved_searches_list.itemDoubleClicked.connect(self.apply_saved_search)
        left_container = QDialog(self)
        left_container_layout = QVBoxLayout(left_container)
        left_container_layout.addWidget(QLabel("Saved Searches"))
        left_container_layout.addWidget(self.saved_searches_list)
        delete_saved_button = QPushButton("Delete Saved Search")
        delete_saved_button.clicked.connect(self.delete_saved_search)
        left_container_layout.addWidget(delete_saved_button)
        splitter.addWidget(left_container)

        middle_container = QDialog(self)
        middle_layout = QVBoxLayout(middle_container)
        middle_layout.addWidget(QLabel("Search Results"))
        self.results_table = QTableWidget(0, 5, middle_container)
        self.results_table.setHorizontalHeaderLabels(["Type", "ID", "Title", "Subtitle", "Status"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.itemSelectionChanged.connect(self.refresh_relationships)
        self.results_table.doubleClicked.connect(lambda _index: self.open_selected_result())
        middle_layout.addWidget(self.results_table, 1)
        open_button = QPushButton("Open Selected Record")
        open_button.clicked.connect(self.open_selected_result)
        middle_layout.addWidget(open_button)
        splitter.addWidget(middle_container)

        right_container = QDialog(self)
        right_layout = QVBoxLayout(right_container)
        right_layout.addWidget(QLabel("Relationship Explorer"))
        self.relationships_edit = QPlainTextEdit()
        self.relationships_edit.setReadOnly(True)
        right_layout.addWidget(self.relationships_edit, 1)
        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 4)

        self.refresh_saved_searches()

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

    def refresh_saved_searches(self) -> None:
        self.saved_searches_list.clear()
        for saved in self.search_service.list_saved_searches():
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
        results = self.search_service.search(
            self.search_edit.text(),
            entity_types=self._entity_filter(),
            limit=200,
        )
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
        self.results_table.resizeColumnsToContents()
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
            self.relationships_edit.setPlainText("Select a result to inspect its links.")
            return
        entity_type, entity_id = selected
        sections = self.relationship_service.describe_links(entity_type, entity_id)
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
        query = self.search_edit.text().strip()
        if not query:
            QMessageBox.information(self, "Global Search", "Enter a query first.")
            return
        name = query if len(query) <= 40 else query[:40]
        try:
            self.search_service.save_search(name, query, self._entity_filter())
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
        item = self.saved_searches_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Global Search", "Select a saved search first.")
            return
        self.search_service.delete_saved_search(int(item.data(Qt.UserRole)))
        self.refresh_saved_searches()
