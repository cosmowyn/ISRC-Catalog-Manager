from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    normalize_storage_mode,
)


def get_name_from_editable_choice_dialog(
    parent: QWidget | None,
    *,
    title: str,
    label: str,
    choices: list[str],
    suggested_name: str = "",
    placeholder: str = "Enter a new name",
) -> tuple[str, bool]:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)

    root = QVBoxLayout(dialog)
    form = QFormLayout()
    root.addLayout(form)

    selector = QComboBox(dialog)
    selector.setEditable(True)
    selector.setInsertPolicy(QComboBox.NoInsert)
    selector.setMinimumContentsLength(24)
    selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    selector.addItem("", "")
    for choice in choices:
        clean_choice = str(choice or "").strip()
        if clean_choice:
            selector.addItem(clean_choice, clean_choice)

    line_edit = selector.lineEdit()
    if line_edit is not None:
        line_edit.setPlaceholderText(placeholder)

    clean_suggestion = str(suggested_name or "").strip()
    if clean_suggestion:
        suggestion_index = selector.findText(clean_suggestion, Qt.MatchFixedString)
        if suggestion_index >= 0:
            selector.setCurrentIndex(suggestion_index)
        else:
            selector.setCurrentIndex(0)
            selector.setEditText(clean_suggestion)
        if line_edit is not None:
            line_edit.selectAll()
    else:
        selector.setCurrentIndex(0)

    form.addRow(label, selector)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, dialog)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    root.addWidget(buttons)

    if dialog.exec() != QDialog.Accepted:
        return "", False
    return str(selector.currentText() or "").strip(), True


def storage_mode_choice_text(mode: str | None) -> str:
    normalized = normalize_storage_mode(mode, default=None)
    if normalized == STORAGE_MODE_DATABASE:
        return "Store in Database"
    return "Store as Managed File"


def prompt_storage_mode_choice(
    parent: QWidget | None,
    *,
    title: str,
    subject: str,
    default_mode: str | None = None,
) -> str | None:
    default_normalized = normalize_storage_mode(default_mode, default=STORAGE_MODE_MANAGED_FILE)
    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Question)
    dialog.setWindowTitle(title)
    dialog.setText(f"How should {subject} be stored?")
    dialog.setInformativeText(
        "Database mode keeps the raw file bytes in the profile database. "
        "Managed file mode copies the file into the app-controlled storage folder and stores "
        "only the managed path."
    )
    db_button = dialog.addButton("Store in Database", QMessageBox.AcceptRole)
    file_button = dialog.addButton("Store as Managed File", QMessageBox.AcceptRole)
    dialog.addButton(QMessageBox.Cancel)
    dialog.setDefaultButton(
        file_button if default_normalized == STORAGE_MODE_MANAGED_FILE else db_button
    )
    dialog.exec()
    clicked = dialog.clickedButton()
    if clicked is db_button:
        return STORAGE_MODE_DATABASE
    if clicked is file_button:
        return STORAGE_MODE_MANAGED_FILE
    return None


__all__ = [
    "get_name_from_editable_choice_dialog",
    "prompt_storage_mode_choice",
    "storage_mode_choice_text",
]
