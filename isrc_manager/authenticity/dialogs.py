"""Qt dialogs for authenticity key management, export preview, and verification results."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
)

from .models import AuthenticityExportPlan, AuthenticityVerificationReport
from .service import AuthenticityKeyService


class AuthenticityKeysDialog(QDialog):
    """Manage local signing keys and default-key selection."""

    def __init__(self, *, key_service: AuthenticityKeyService, parent=None):
        super().__init__(parent)
        self.key_service = key_service
        self.setWindowTitle("Audio Authenticity Keys")
        self.resize(820, 520)
        _apply_standard_dialog_chrome(self, "authenticityKeysDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title="Audio Authenticity Keys",
            subtitle=(
                "Ed25519 public keys are stored in the profile database. Private signing keys stay in the app settings folder and are not tamper-proof."
            ),
        )

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setProperty("role", "secondary")
        root.addWidget(self.summary_label)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["Default", "Key ID", "Signer", "Algorithm", "Private Key", "Created"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.generate_button = QPushButton("Generate Key")
        self.generate_button.clicked.connect(self._generate_key)
        self.default_button = QPushButton("Set Default")
        self.default_button.clicked.connect(self._set_default)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(self.generate_button)
        buttons.addWidget(self.default_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        self.refresh()
        _apply_compact_dialog_control_heights(self)

    def refresh(self) -> None:
        keys = self.key_service.list_keys()
        self.table.setRowCount(len(keys))
        for row_index, record in enumerate(keys):
            values = [
                "Yes" if record.is_default else "",
                record.key_id,
                record.signer_label or "",
                record.algorithm,
                "Present" if record.has_private_key else "Missing",
                record.created_at or "",
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))
        if not keys:
            self.summary_label.setText(
                "No authenticity signing keys exist yet. Generate one before exporting watermarked audio."
            )
        else:
            self.summary_label.setText(
                "Local private keys enable signing and keyed watermark extraction. Public keys are kept in the profile for verification."
            )

    def _selected_key_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        return item.text().strip() if item is not None else None

    def _generate_key(self) -> None:
        try:
            record = self.key_service.generate_keypair()
        except Exception as exc:
            QMessageBox.critical(self, "Audio Authenticity Keys", str(exc))
            return
        self.refresh()
        QMessageBox.information(
            self,
            "Audio Authenticity Keys",
            f"Generated authenticity key '{record.key_id}'.",
        )

    def _set_default(self) -> None:
        key_id = self._selected_key_id()
        if not key_id:
            QMessageBox.information(
                self,
                "Audio Authenticity Keys",
                "Select a key first.",
            )
            return
        self.key_service.set_default_key(key_id)
        self.refresh()


class AuthenticityExportPreviewDialog(QDialog):
    """Preview supported and unsupported watermark export items."""

    def __init__(self, *, plan: AuthenticityExportPlan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("Export Authenticity Watermarked Audio")
        self.resize(920, 620)
        _apply_standard_dialog_chrome(self, "authenticityExportPreviewDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title="Export Authenticity Watermarked Audio",
            subtitle=(
                "This workflow writes watermarked export copies and sidecar manifests. Original reference audio stays unchanged."
            ),
        )
        summary = QLabel(
            f"Signing key: {plan.key_id}" + (f" ({plan.signer_label})" if plan.signer_label else "")
        )
        summary.setProperty("role", "secondary")
        root.addWidget(summary)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            ["Status", "Track", "Reference Source", "Output Name", "Warning"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.table.setRowCount(len(plan.items))
        for row_index, item in enumerate(plan.items):
            values = [
                item.status,
                item.track_title,
                item.source_label,
                f"{item.suggested_name}{item.source_suffix or ''}",
                item.warning or "",
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        continue_button = QPushButton("Continue")
        continue_button.clicked.connect(self.accept)
        continue_button.setDefault(True)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(continue_button)
        buttons.addWidget(cancel_button)
        root.addLayout(buttons)
        _apply_compact_dialog_control_heights(self)


class AuthenticityVerificationDialog(QDialog):
    """Display a verification report in a readable form."""

    def __init__(self, *, report: AuthenticityVerificationReport, parent=None):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("Audio Authenticity Verification")
        self.resize(780, 520)
        _apply_standard_dialog_chrome(self, "authenticityVerificationDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        _add_standard_dialog_header(
            root,
            self,
            title="Audio Authenticity Verification",
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
        if report.manifest_id:
            detail_lines.append(f"Manifest ID: {report.manifest_id}")
        if report.watermark_id is not None:
            detail_lines.append(f"Watermark ID: {report.watermark_id}")
        if report.key_id:
            detail_lines.append(f"Key ID: {report.key_id}")
        if report.resolution_source:
            detail_lines.append(f"Resolved From: {report.resolution_source}")
        if report.signature_valid is not None:
            detail_lines.append(f"Signature Valid: {report.signature_valid}")
        if report.exact_hash_match is not None:
            detail_lines.append(f"Exact Hash Match: {report.exact_hash_match}")
        if report.fingerprint_similarity is not None:
            detail_lines.append(f"Fingerprint Similarity: {report.fingerprint_similarity:.3f}")
        if report.extraction_confidence is not None:
            detail_lines.append(f"Extraction Confidence: {report.extraction_confidence:.3f}")
        if report.sidecar_path:
            detail_lines.append(f"Sidecar: {report.sidecar_path}")
        if report.details:
            detail_lines.append("")
            detail_lines.append("Details:")
            detail_lines.extend(report.details)
        details.setPlainText("\n".join(detail_lines))
        root.addWidget(details, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        root.addLayout(buttons)
        _apply_compact_dialog_control_heights(self)
