"""Shared selection-scope widgets for catalog managers."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _apply_standard_widget_chrome,
    _create_action_button_cluster,
    _create_standard_section,
)


@dataclass(frozen=True, slots=True)
class TrackChoice:
    track_id: int
    title: str
    subtitle: str = ""


@dataclass(frozen=True, slots=True)
class SelectionScopeState:
    source_label: str
    track_ids: tuple[int, ...]
    preview_text: str
    override_active: bool = False

    @property
    def count(self) -> int:
        return len(self.track_ids)


def build_selection_preview(
    track_ids: list[int] | tuple[int, ...],
    title_lookup,
    *,
    max_titles: int = 3,
) -> str:
    titles: list[str] = []
    seen: set[str] = set()
    for track_id in track_ids:
        try:
            title = str(title_lookup(int(track_id)) or "").strip()
        except Exception:
            title = ""
        if not title:
            title = f"Track {track_id}"
        if title in seen:
            continue
        seen.add(title)
        titles.append(title)
        if len(titles) >= max_titles:
            break
    if not titles:
        return "No tracks selected."
    if len(track_ids) > max_titles:
        return f"{', '.join(titles)} +{len(track_ids) - max_titles} more"
    return ", ".join(titles)


class SelectionScopeBanner(QWidget):
    """Compact banner that explains which track selection a manager will use."""

    def __init__(
        self,
        *,
        chooser_label: str = "Choose Tracks",
        parent=None,
        show_header: bool = True,
        content_margins: tuple[int, int, int, int] = (12, 12, 12, 12),
    ):
        super().__init__(parent)
        self._syncing_height = False
        self.setObjectName("selectionScopeBanner")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        _apply_standard_widget_chrome(self, "selectionScopeBanner")

        root = QVBoxLayout(self)
        root.setContentsMargins(*content_margins)
        root.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)
        self.scope_label = QLabel("Catalog selection")
        self.scope_label.setProperty("role", "sectionTitle")
        self.count_label = QLabel("0 tracks")
        self.count_label.setProperty("role", "secondary")
        if show_header:
            header_row.addWidget(self.scope_label)
            header_row.addStretch(1)
            header_row.addWidget(self.count_label)
            root.addLayout(header_row)
        else:
            self.scope_label.setVisible(False)
            root.addWidget(self.count_label, 0, Qt.AlignRight)

        self.preview_label = QLabel("No tracks selected.")
        self.preview_label.setWordWrap(True)
        self.preview_label.setProperty("role", "secondary")
        root.addWidget(self.preview_label)

        self.use_current_button = QPushButton("Use Current Selection")
        self.choose_button = QPushButton(chooser_label)
        self.clear_override_button = QPushButton("Clear Override")
        self.action_cluster = _create_action_button_cluster(
            self,
            [
                self.use_current_button,
                self.choose_button,
                self.clear_override_button,
            ],
            columns=2,
            min_button_width=160,
            outer_margins=(3, 3, 3, 3),
            horizontal_spacing=3,
            vertical_spacing=3,
            lock_minimum_height=False,
        )
        root.addWidget(self.action_cluster)

        self.clear_override_button.setEnabled(False)
        self.clear_override_button.setVisible(False)
        _apply_compact_dialog_control_heights(self)
        self._sync_layout_height()

    def set_state(self, state: SelectionScopeState) -> None:
        self.scope_label.setText(state.source_label)
        self.count_label.setText(f"{state.count} track{'s' if state.count != 1 else ''}")
        self.preview_label.setText(state.preview_text or "No tracks selected.")
        override_active = bool(state.override_active)
        self.clear_override_button.setEnabled(override_active)
        self.clear_override_button.setVisible(override_active)
        self.action_cluster.updateGeometry()
        self._sync_layout_height()

    def _sync_layout_height(self) -> None:
        if getattr(self, "_syncing_height", False):
            return
        self._syncing_height = True
        try:
            layout = self.layout()
            if layout is not None:
                layout.activate()
            target_height = max(
                0,
                int(self.minimumSizeHint().height()),
                int(self.sizeHint().height()),
            )
            if self.minimumHeight() != target_height:
                self.setMinimumHeight(target_height)
                self.updateGeometry()
        finally:
            self._syncing_height = False

    def event(self, event) -> bool:
        result = super().event(event)
        if event.type() in (
            QEvent.FontChange,
            QEvent.LayoutRequest,
            QEvent.StyleChange,
        ):
            self._sync_layout_height()
        return result


class TrackSelectionChooserDialog(QDialog):
    """Pick a pinned track batch from the current catalog table state."""

    def __init__(
        self,
        *,
        track_choices: list[TrackChoice],
        initial_track_ids: list[int] | tuple[int, ...] | None = None,
        title: str = "Choose Tracks",
        subtitle: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._track_choices = list(track_choices)
        self._initial_ids = {int(track_id) for track_id in (initial_track_ids or [])}
        self.setWindowTitle(title)
        self.resize(760, 560)
        self.setMinimumSize(680, 460)
        _apply_standard_dialog_chrome(self, "trackSelectionChooserDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title=title,
            subtitle=subtitle
            or "Choose a pinned set of tracks from the current catalog table. This override stays active until you clear it.",
        )

        controls_box, controls_layout = _create_standard_section(
            self,
            "Filter and Select",
            "Review the current catalog table rows, then keep only the tracks this manager should act on.",
        )
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(8)
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter by title or context...")
        self.filter_edit.textChanged.connect(self._apply_filter)
        controls_row.addWidget(self.filter_edit, 1)
        select_all_button = QPushButton("Select All")
        clear_button = QPushButton("Clear")
        select_all_button.clicked.connect(self._select_all_visible)
        clear_button.clicked.connect(self._clear_all)
        controls_row.addWidget(select_all_button)
        controls_row.addWidget(clear_button)
        controls_layout.addLayout(controls_row)

        self.selection_table = QTableWidget(0, 3, self)
        self.selection_table.setHorizontalHeaderLabels(["Use", "Title", "Context"])
        self.selection_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.selection_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.selection_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.selection_table.verticalHeader().setVisible(False)
        self.selection_table.horizontalHeader().setStretchLastSection(True)
        self.selection_table.horizontalHeader().resizeSection(0, 58)
        controls_layout.addWidget(self.selection_table, 1)
        root.addWidget(controls_box, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setText("Use Chosen Tracks")
            ok_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._populate_rows()
        _apply_compact_dialog_control_heights(self)

    def _populate_rows(self) -> None:
        self.selection_table.setRowCount(0)
        for choice in self._track_choices:
            row = self.selection_table.rowCount()
            self.selection_table.insertRow(row)

            check_item = QTableWidgetItem("")
            check_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            check_item.setCheckState(
                Qt.Checked if int(choice.track_id) in self._initial_ids else Qt.Unchecked
            )
            check_item.setData(Qt.UserRole, int(choice.track_id))
            self.selection_table.setItem(row, 0, check_item)
            self.selection_table.setItem(row, 1, QTableWidgetItem(choice.title))
            self.selection_table.setItem(row, 2, QTableWidgetItem(choice.subtitle))

    def _row_text(self, row: int) -> str:
        parts = []
        for column in (1, 2):
            item = self.selection_table.item(row, column)
            if item is not None:
                parts.append(item.text().strip())
        return " ".join(part for part in parts if part).casefold()

    def _apply_filter(self) -> None:
        search_text = self.filter_edit.text().strip().casefold()
        for row in range(self.selection_table.rowCount()):
            match = not search_text or search_text in self._row_text(row)
            self.selection_table.setRowHidden(row, not match)

    def _select_all_visible(self) -> None:
        for row in range(self.selection_table.rowCount()):
            if self.selection_table.isRowHidden(row):
                continue
            item = self.selection_table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.Checked)

    def _clear_all(self) -> None:
        for row in range(self.selection_table.rowCount()):
            item = self.selection_table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.Unchecked)

    def selected_track_ids(self) -> list[int]:
        track_ids: list[int] = []
        for row in range(self.selection_table.rowCount()):
            item = self.selection_table.item(row, 0)
            if item is None or item.checkState() != Qt.Checked:
                continue
            try:
                track_ids.append(int(item.data(Qt.UserRole)))
            except (TypeError, ValueError):
                continue
        return track_ids
