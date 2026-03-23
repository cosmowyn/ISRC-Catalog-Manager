"""Qt dialogs for forensic watermark export and inspection workflows."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)

from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _configure_standard_form_layout,
)

from .models import ForensicInspectionReport


class ForensicExportDialog(QDialog):
    """Collect minimal recipient/share metadata for forensic exports."""

    def __init__(
        self,
        *,
        format_labels: list[tuple[str, str]],
        parent=None,
    ):
        super().__init__(parent)
        self._format_labels = list(format_labels)
        self.setWindowTitle("Export Forensic Watermarked Audio")
        self.resize(640, 360)
        _apply_standard_dialog_chrome(self, "forensicExportDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title="Export Forensic Watermarked Audio",
            subtitle=(
                "Create recipient-specific lossy delivery copies for leak tracing. "
                "These exports remain distinct from direct authenticity master exports."
            ),
        )

        summary = QLabel(
            "The app will export the selected catalog audio to a lossy delivery format, write database metadata, embed a recipient-specific forensic watermark, hash the final file, register derivative lineage, and ZIP bulk exports."
        )
        summary.setWordWrap(True)
        summary.setProperty("role", "secondary")
        root.addWidget(summary)

        form = QFormLayout()
        _configure_standard_form_layout(form)
        self.format_combo = QComboBox(self)
        for format_id, label in self._format_labels:
            self.format_combo.addItem(label, format_id)
        self.recipient_edit = QLineEdit(self)
        self.share_edit = QLineEdit(self)
        self.recipient_edit.setPlaceholderText("Optional recipient or reviewer label")
        self.share_edit.setPlaceholderText("Optional share or campaign label")
        form.addRow("Output Format", self.format_combo)
        form.addRow("Recipient Label", self.recipient_edit)
        form.addRow("Share Label", self.share_edit)
        root.addLayout(form)

        note = QLabel(
            "Forensic watermarking is intended for leak tracing of shared delivery copies. It is not DRM and it is not the same as signed authenticity verification."
        )
        note.setWordWrap(True)
        note.setProperty("role", "secondary")
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        _apply_compact_dialog_control_heights(self)

    def selected_format_id(self) -> str | None:
        return str(self.format_combo.currentData() or "").strip().lower() or None

    def recipient_label(self) -> str | None:
        text = self.recipient_edit.text().strip()
        return text or None

    def share_label(self) -> str | None:
        text = self.share_edit.text().strip()
        return text or None


class ForensicInspectionDialog(QDialog):
    """Display a forensic inspection report in a readable form."""

    def __init__(self, *, report: ForensicInspectionReport, parent=None):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("Forensic Watermark Inspection")
        self.resize(780, 520)
        _apply_standard_dialog_chrome(self, "forensicInspectionDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title="Forensic Watermark Inspection",
            subtitle=report.message,
        )
        summary = QLabel(f"Status: {report.status}\nInspected file: {report.inspected_path}")
        summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(summary)

        details = QTextEdit(self)
        details.setReadOnly(True)
        detail_lines = [
            f"Status: {report.status}",
            f"Message: {report.message}",
            f"Path: {report.inspected_path}",
        ]
        if report.forensic_export_id:
            detail_lines.append(f"Forensic Export ID: {report.forensic_export_id}")
        if report.batch_id:
            detail_lines.append(f"Batch ID: {report.batch_id}")
        if report.derivative_export_id:
            detail_lines.append(f"Derivative Export ID: {report.derivative_export_id}")
        if report.track_id is not None:
            detail_lines.append(f"Track ID: {report.track_id}")
        if report.recipient_label:
            detail_lines.append(f"Recipient: {report.recipient_label}")
        if report.share_label:
            detail_lines.append(f"Share Label: {report.share_label}")
        if report.output_format:
            detail_lines.append(f"Output Format: {report.output_format}")
        if report.token_id is not None:
            detail_lines.append(f"Token ID: {report.token_id}")
        if report.resolution_basis:
            detail_lines.append(f"Resolution Basis: {report.resolution_basis}")
        if report.confidence_score is not None:
            detail_lines.append(f"Confidence: {report.confidence_score:.3f}")
        if report.exact_hash_match is not None:
            detail_lines.append(f"Exact Hash Match: {report.exact_hash_match}")
        if report.details:
            detail_lines.append("")
            detail_lines.append("Details:")
            detail_lines.extend(str(line) for line in report.details)
        details.setPlainText("\n".join(detail_lines))
        root.addWidget(details, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, Qt.Horizontal, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)
        _apply_compact_dialog_control_heights(self)
