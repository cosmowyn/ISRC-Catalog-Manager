import unittest

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

    from isrc_manager.qss_reference import (
        QssCodeEditor,
        build_qss_completion_tokens,
        collect_qss_reference_entries,
        ensure_widget_object_names,
    )
except Exception as exc:  # pragma: no cover - environment-specific fallback
    QSS_IMPORT_ERROR = exc
else:
    QSS_IMPORT_ERROR = None

try:
    import ISRC_manager as app_module
except Exception as exc:  # pragma: no cover - environment-specific fallback
    app_module = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None


class QssReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QSS_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f"QSS reference helpers unavailable: {QSS_IMPORT_ERROR}")
        cls.app = require_qapplication()

    def test_collect_qss_reference_entries_discovers_object_names_roles_and_types(self):
        root = QWidget()
        root.setObjectName("demoRoot")
        layout = QVBoxLayout(root)
        root.save_button = QPushButton("Save", root)
        root.filter_label = QLabel("Helper", root)
        root.filter_label.setProperty("role", "secondary")
        layout.addWidget(root.save_button)
        layout.addWidget(root.filter_label)
        try:
            ensure_widget_object_names(root)
            entries = collect_qss_reference_entries([root])
            selectors = {entry.selector for entry in entries}
            tokens = set(build_qss_completion_tokens(entries))

            self.assertIn("QPushButton", selectors)
            self.assertIn("#save_button", selectors)
            self.assertIn("QPushButton#save_button", selectors)
            self.assertIn('[role="secondary"]', selectors)
            self.assertIn('QLabel[role="secondary"]', selectors)
            self.assertIn("#save_button", tokens)
            self.assertIn("QDockWidget::title", tokens)
        finally:
            root.close()

    def test_qss_editor_completion_tokens_are_loaded_into_completer_model(self):
        editor = QssCodeEditor()
        try:
            editor.set_completion_tokens(["#save_button", "QPushButton", "QLineEdit"])
            model = editor._completer.model()
            completions = model.stringList()
            self.assertIn("#save_button", completions)
            self.assertIn("QPushButton", completions)
        finally:
            editor.close()

    def test_application_settings_dialog_exposes_selector_reference_and_insert_flow(self):
        if app_module is None:
            raise unittest.SkipTest(f"ISRC_manager import unavailable: {APP_IMPORT_ERROR}")

        dialog = app_module.ApplicationSettingsDialog(
            window_title="Catalog",
            icon_path="",
            artist_code="00",
            auto_snapshot_enabled=True,
            auto_snapshot_interval_minutes=30,
            isrc_prefix="NLABC",
            sena_number="",
            btw_number="",
            buma_relatie_nummer="",
            buma_ipi="",
            gs1_template_asset=None,
            gs1_contracts_csv_path="",
            gs1_contract_entries=(),
            gs1_active_contract_number="",
            gs1_target_market="",
            gs1_language="",
            gs1_brand="",
            gs1_subbrand="",
            gs1_packaging_type="",
            gs1_product_classification="",
            theme_settings={},
            stored_themes={},
            current_profile_path="",
            parent=None,
        )
        try:
            self.assertIsInstance(dialog.theme_custom_qss_edit, QssCodeEditor)
            self.assertGreater(dialog.qss_reference_table.rowCount(), 0)

            dialog.qss_reference_filter_edit.setText("#applicationSettingsDialog")
            self.app.processEvents()
            self.assertGreaterEqual(dialog.qss_reference_table.rowCount(), 1)

            dialog.qss_reference_table.selectRow(0)
            dialog._insert_selected_qss_selector()
            self.assertIn(
                "#applicationSettingsDialog",
                dialog.theme_custom_qss_edit.toPlainText(),
            )
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
