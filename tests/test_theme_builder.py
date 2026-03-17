import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtWidgets import QMessageBox, QWidget

    import ISRC_manager as app_module
    from isrc_manager.theme_builder import (
        build_theme_stylesheet,
        effective_theme_settings,
        theme_setting_defaults,
        theme_setting_keys,
    )
except Exception as exc:  # pragma: no cover - environment-specific fallback
    THEME_IMPORT_ERROR = exc
else:
    THEME_IMPORT_ERROR = None


class _ThemePreviewHost(QWidget):
    def __init__(self):
        super().__init__()
        self.applied = []
        self.gs1_integration_service = None

    def _apply_theme(self, values):
        self.applied.append(dict(values or {}))


class ThemeBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if THEME_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f"Theme helpers unavailable: {THEME_IMPORT_ERROR}")
        cls.app = require_qapplication()

    def test_theme_defaults_expose_expanded_control_surface(self):
        defaults = theme_setting_defaults()

        for key in (
            "dialog_title_font_size",
            "secondary_text_font_size",
            "button_hover_bg",
            "button_pressed_border",
            "help_button_hover_bg",
            "input_focus_border",
            "indicator_checked_bg",
            "scrollbar_handle_bg",
            "menu_selected_bg",
            "tab_selected_border",
            "progress_chunk_bg",
            "help_button_size",
            "menu_radius",
        ):
            self.assertIn(key, defaults)

        self.assertEqual(set(defaults), set(theme_setting_keys()))

    def test_effective_theme_settings_derive_blank_state_values(self):
        effective = effective_theme_settings(
            {
                "window_bg": "#20242A",
                "window_fg": "#F7FAFC",
                "accent": "#0EA5E9",
                "selection_bg": "",
                "selection_fg": "",
                "button_bg": "#334155",
                "button_fg": "#F8FAFC",
                "input_bg": "#0F172A",
                "input_fg": "#E2E8F0",
                "table_bg": "#111827",
                "table_fg": "#E5E7EB",
            }
        )

        self.assertEqual(effective["selection_bg"], "#0EA5E9")
        self.assertEqual(effective["help_button_bg"], "#0EA5E9")
        self.assertTrue(effective["button_hover_bg"])
        self.assertTrue(effective["button_pressed_bg"])
        self.assertTrue(effective["input_focus_border"])
        self.assertTrue(effective["menu_selected_bg"])
        self.assertTrue(effective["tab_selected_bg"])
        self.assertTrue(effective["scrollbar_handle_bg"])

    def test_stylesheet_covers_expanded_widget_families_and_states(self):
        stylesheet = build_theme_stylesheet(
            {
                "window_bg": "#1F2937",
                "window_fg": "#F9FAFB",
                "accent": "#F97316",
                "button_bg": "#374151",
                "button_fg": "#F9FAFB",
                "custom_qss": "QLabel#marker { color: #123456; }",
            }
        )

        self.assertIn('QToolButton[role="helpButton"]:hover', stylesheet)
        self.assertIn("QCheckBox::indicator", stylesheet)
        self.assertIn("QScrollBar::handle:hover:vertical", stylesheet)
        self.assertIn("QProgressBar::chunk", stylesheet)
        self.assertIn("QTabBar::tab:selected", stylesheet)
        self.assertIn("QMenuBar::item:selected", stylesheet)
        self.assertIn('QLabel[role="dialogTitle"]', stylesheet)
        self.assertIn("/* Advanced QSS */", stylesheet)
        self.assertIn("QLabel#marker { color: #123456; }", stylesheet)

    def test_application_settings_dialog_exposes_theme_builder_tabs_and_payload(self):
        host = _ThemePreviewHost()
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
            parent=host,
        )
        try:
            labels = [
                dialog.theme_builder_tabs.tabText(index)
                for index in range(dialog.theme_builder_tabs.count())
            ]
            self.assertIn("Buttons", labels)
            self.assertIn("Inputs", labels)
            self.assertIn("Data Views", labels)
            self.assertIn("Navigation", labels)
            self.assertIn("Advanced QSS", labels)

            dialog._theme_color_edits["button_hover_bg"].setText("#224488")
            dialog._theme_color_edits["menu_selected_bg"].setText("#BB5500")
            dialog._theme_metric_spins["menu_radius"].setValue(14)
            dialog._theme_metric_spins["dialog_title_font_size"].setValue(22)
            values = dialog.values()["theme_settings"]

            self.assertEqual(values["button_hover_bg"], "#224488")
            self.assertEqual(values["menu_selected_bg"], "#BB5500")
            self.assertEqual(values["menu_radius"], 14)
            self.assertEqual(values["dialog_title_font_size"], 22)
        finally:
            dialog.close()
            host.close()

    def test_theme_preview_switches_with_active_builder_tab(self):
        host = _ThemePreviewHost()
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
            parent=host,
        )
        try:
            buttons_index = next(
                index
                for index in range(dialog.theme_builder_tabs.count())
                if dialog.theme_builder_tabs.tabText(index) == "Buttons"
            )
            dialog.theme_builder_tabs.setCurrentIndex(buttons_index)
            self.app.processEvents()
            self.assertEqual(
                dialog.theme_preview_tabs.tabText(dialog.theme_preview_tabs.currentIndex()),
                "Buttons",
            )

            inputs_index = next(
                index
                for index in range(dialog.theme_builder_tabs.count())
                if dialog.theme_builder_tabs.tabText(index) == "Inputs"
            )
            dialog.theme_builder_tabs.setCurrentIndex(inputs_index)
            self.app.processEvents()
            self.assertEqual(
                dialog.theme_preview_tabs.tabText(dialog.theme_preview_tabs.currentIndex()),
                "Inputs",
            )
        finally:
            dialog.close()
            host.close()

    def test_live_preview_and_theme_export_import_round_trip(self):
        host = _ThemePreviewHost()
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
            parent=host,
        )
        try:
            dialog.theme_live_preview_check.setChecked(True)
            dialog._theme_color_edits["help_button_bg"].setText("#118AB2")
            dialog._theme_metric_spins["help_button_size"].setValue(32)
            dialog._refresh_theme_previews()

            self.assertTrue(host.applied)
            self.assertEqual(host.applied[-1]["help_button_bg"], "#118AB2")
            self.assertEqual(host.applied[-1]["help_button_size"], 32)

            with tempfile.TemporaryDirectory() as tmpdir:
                export_path = Path(tmpdir) / "theme.json"
                with (
                    mock.patch.object(
                        app_module.QFileDialog,
                        "getSaveFileName",
                        return_value=(str(export_path), "Theme JSON (*.json)"),
                    ),
                    mock.patch.object(QMessageBox, "information", return_value=None),
                ):
                    dialog._export_theme_to_file()

                payload = json.loads(export_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["version"], 2)
                self.assertEqual(payload["theme"]["help_button_bg"], "#118AB2")

                dialog._theme_color_edits["help_button_bg"].clear()
                with mock.patch.object(
                    app_module.QFileDialog,
                    "getOpenFileName",
                    return_value=(str(export_path), "Theme JSON (*.json)"),
                ):
                    dialog._import_theme_from_file()
                self.assertEqual(dialog._theme_color_edits["help_button_bg"].text(), "#118AB2")

            dialog.reject()
            self.app.processEvents()
            self.assertEqual(host.applied[-1]["accent"], dialog._theme_original_values["accent"])
        finally:
            dialog.close()
            host.close()

    def test_theme_reset_restores_defaults_without_crashing(self):
        host = _ThemePreviewHost()
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
            parent=host,
        )
        try:
            dialog._theme_color_edits["button_hover_bg"].setText("#225577")
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                dialog._reset_theme_to_defaults()
            self.assertEqual(dialog._theme_color_edits["button_hover_bg"].text(), "")
            self.assertEqual(
                dialog._theme_metric_spins["help_button_size"].value(),
                int(theme_setting_defaults()["help_button_size"]),
            )
        finally:
            dialog.close()
            host.close()


if __name__ == "__main__":
    unittest.main()
