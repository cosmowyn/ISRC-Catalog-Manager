"""PySide6 dialogs for crash and manual report review."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .models import ManualBugReportFields, ReportPayload


class CrashReportPromptDialog(QDialog):
    """Ask for consent before generating and previewing a crash report."""

    def __init__(self, *, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Send Crash Report?")
        layout = QVBoxLayout(self)
        heading = QLabel("The previous application session appears to have ended unexpectedly.")
        heading.setWordWrap(True)
        heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(heading)

        body = QLabel(
            "A crash report can include the app version, operating system, Python and Qt "
            "versions, the last recorded workflow event, and recent sanitised application logs. "
            "It will not include catalog databases, audio files, documents, credentials, tokens, "
            "or raw private file paths. You can review the exact report before anything is sent."
        )
        body.setWordWrap(True)
        layout.addWidget(body)

        self.include_os_context_checkbox = QCheckBox(
            "Include optional sanitised operating-system crash context"
        )
        self.include_os_context_checkbox.setChecked(False)
        self.include_os_context_checkbox.setToolTip(
            "Runs a short, read-only native OS log query for the previous app session. "
            "No shell, script, or administrator access is used."
        )
        layout.addWidget(self.include_os_context_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        review_button = buttons.addButton("Review Report", QDialogButtonBox.AcceptRole)
        review_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def include_os_context(self) -> bool:
        return self.include_os_context_checkbox.isChecked()


class ManualBugReportDialog(QDialog):
    """Collect user-authored bug report details."""

    def __init__(self, *, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Report a Bug")
        self.resize(760, 640)
        layout = QVBoxLayout(self)

        notice = QLabel(
            "Reports are sanitised locally before preview and submission. Do not paste secrets, "
            "private contract terms, catalogue exports, raw database rows, or audio/document content."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)

        form = QFormLayout()
        self.summary_edit = QLineEdit()
        self.summary_edit.setPlaceholderText("Short summary")
        form.addRow("Summary", self.summary_edit)

        self.description_edit = _large_text_edit("Describe the problem.")
        form.addRow("Description", self.description_edit)

        self.steps_edit = _large_text_edit("List the exact steps that reproduce the issue.")
        form.addRow("Steps to reproduce", self.steps_edit)

        self.expected_edit = _large_text_edit("What should have happened?")
        form.addRow("Expected behaviour", self.expected_edit)

        self.actual_edit = _large_text_edit("What happened instead?")
        form.addRow("Actual behaviour", self.actual_edit)
        layout.addLayout(form)

        self.include_logs_checkbox = QCheckBox("Include sanitised recent application logs")
        self.include_logs_checkbox.setChecked(True)
        self.include_system_checkbox = QCheckBox("Include technical system details")
        self.include_system_checkbox.setChecked(True)
        self.include_os_context_checkbox = QCheckBox(
            "Include optional sanitised operating-system event context"
        )
        self.include_os_context_checkbox.setChecked(False)
        self.include_os_context_checkbox.setToolTip(
            "Runs a short, read-only native OS log query for the current app process. "
            "No shell, script, or administrator access is used."
        )
        layout.addWidget(self.include_logs_checkbox)
        layout.addWidget(self.include_system_checkbox)
        layout.addWidget(self.include_os_context_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("Preview Report")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def fields(self) -> ManualBugReportFields:
        return ManualBugReportFields(
            summary=self.summary_edit.text().strip(),
            description=self.description_edit.toPlainText().strip(),
            steps_to_reproduce=self.steps_edit.toPlainText().strip(),
            expected_behavior=self.expected_edit.toPlainText().strip(),
            actual_behavior=self.actual_edit.toPlainText().strip(),
            include_logs=self.include_logs_checkbox.isChecked(),
            include_system_details=self.include_system_checkbox.isChecked(),
            include_os_context=self.include_os_context_checkbox.isChecked(),
        )

    def _accept_if_valid(self) -> None:
        if not self.summary_edit.text().strip():
            QMessageBox.warning(self, "Report a Bug", "Enter a short summary before previewing.")
            return
        self.accept()


class ReportPreviewDialog(QDialog):
    """Show the exact markdown that will be submitted or saved."""

    def __init__(self, report: ReportPayload, preview_text: str, *, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Report Preview")
        self.resize(900, 700)
        self.submit_requested = False

        layout = QVBoxLayout(self)
        summary = QLabel(
            "Review the sanitised report below. This is the exact Markdown payload prepared for "
            "submission. You can cancel without sending anything."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        title = QLabel(report.issue_title)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        self.preview_edit = QPlainTextEdit()
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setPlainText(preview_text)
        layout.addWidget(self.preview_edit, 1)

        button_row = QHBoxLayout()
        self.copy_button = QPushButton("Copy Report")
        self.copy_button.clicked.connect(self._copy_report)
        button_row.addWidget(self.copy_button)
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        submit_button = QPushButton("Submit Report")
        submit_button.setDefault(True)
        submit_button.clicked.connect(self._submit)
        button_row.addWidget(cancel_button)
        button_row.addWidget(submit_button)
        layout.addLayout(button_row)

    def _copy_report(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.preview_edit.toPlainText())

    def _submit(self) -> None:
        self.submit_requested = True
        self.accept()


def _large_text_edit(placeholder: str) -> QPlainTextEdit:
    edit = QPlainTextEdit()
    edit.setPlaceholderText(placeholder)
    edit.setMinimumHeight(86)
    return edit
