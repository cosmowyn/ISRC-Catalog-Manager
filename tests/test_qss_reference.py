import unittest

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

    from isrc_manager.qss_reference import (
        build_qss_completion_tokens,
        collect_qss_reference_entries,
        ensure_widget_object_names,
    )
except Exception as exc:  # pragma: no cover - environment-specific fallback
    QSS_REFERENCE_IMPORT_ERROR = exc
else:
    QSS_REFERENCE_IMPORT_ERROR = None


class QssReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QSS_REFERENCE_IMPORT_ERROR is not None:
            raise unittest.SkipTest(
                f"QSS reference helpers unavailable: {QSS_REFERENCE_IMPORT_ERROR}"
            )
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
            kinds = {(entry.selector, entry.selector_kind): entry for entry in entries}
            tokens = set(build_qss_completion_tokens(entries))

            self.assertIn("QPushButton", selectors)
            self.assertIn("#save_button", selectors)
            self.assertIn("QPushButton#save_button", selectors)
            self.assertIn('[role="secondary"]', selectors)
            self.assertIn('QLabel[role="secondary"]', selectors)
            self.assertEqual(kinds[("#save_button", "object_name")].widget_class, "QPushButton")
            self.assertEqual(
                kinds[('QLabel[role="secondary"]', "typed_role")].role_name,
                "secondary",
            )
            self.assertIn("#save_button", tokens)
            self.assertIn("QDockWidget::title", tokens)
            self.assertIn("QToolBar#actionRibbonToolbar", selectors)
            self.assertIn('QToolBar[role="actionRibbonToolbar"]', selectors)
            self.assertIn('QToolButton[role="actionRibbonButton"]', selectors)
            self.assertIn("QToolBar#actionRibbonToolbar", tokens)
        finally:
            root.close()


if __name__ == "__main__":
    unittest.main()
