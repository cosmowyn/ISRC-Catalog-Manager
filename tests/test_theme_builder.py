import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtWidgets import QMessageBox, QWidget

    import ISRC_manager as app_module
    from isrc_manager.starter_themes import starter_theme_library, starter_theme_names
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


class _ThemeApplyHost(QWidget):
    _normalize_theme_settings = app_module.App._normalize_theme_settings
    _effective_theme_settings = app_module.App._effective_theme_settings
    _build_theme_stylesheet = app_module.App._build_theme_stylesheet
    _prepare_theme_application_payload = app_module.App._prepare_theme_application_payload
    _apply_prepared_theme_payload = app_module.App._apply_prepared_theme_payload
    _apply_theme_with_loading = app_module.App._apply_theme_with_loading

    def __init__(self):
        super().__init__()
        self.theme_settings = {}
        self.submissions = []
        self.boundary_refresh_count = 0

    def _queue_top_chrome_boundary_refresh(self):
        self.boundary_refresh_count += 1

    def _submit_background_task(self, **kwargs):
        self.submissions.append(dict(kwargs))

        class _Ctx:
            def set_status(self, _message):
                return None

        payload = kwargs["task_fn"](_Ctx())
        on_success = kwargs.get("on_success")
        if on_success is not None:
            on_success(payload)
        return "task-1"


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
            "workspace_bg",
            "group_title_fg",
            "compact_group_bg",
            "compact_group_border",
            "button_hover_bg",
            "button_pressed_border",
            "help_button_hover_bg",
            "input_focus_border",
            "indicator_checked_bg",
            "scrollbar_handle_bg",
            "menu_selected_bg",
            "toolbar_bg",
            "action_ribbon_bg",
            "action_ribbon_fg",
            "action_ribbon_border",
            "statusbar_bg",
            "header_border",
            "tab_selected_border",
            "tab_bar_bg",
            "tab_pane_bg",
            "progress_fg",
            "progress_chunk_bg",
            "help_button_size",
            "menu_radius",
        ):
            self.assertIn(key, defaults)

        self.assertEqual(set(defaults), set(theme_setting_keys()))

    def test_starter_themes_expose_requested_bundled_presets(self):
        library = starter_theme_library()
        self.assertEqual(
            starter_theme_names(),
            (
                "Apple Light",
                "Apple Dark",
                "High Visibility",
                "Aeon Emerald Gold",
                "Subconscious Cosmos",
                "VS Code Dark",
                "Pastel Studio",
            ),
        )
        for name in starter_theme_names():
            self.assertIn(name, library)
            self.assertEqual(library[name]["selected_name"], "")
            self.assertTrue(library[name]["window_bg"])
            self.assertTrue(library[name]["window_fg"])
            self.assertTrue(library[name]["accent"])
            self.assertTrue(library[name]["action_ribbon_bg"])
            self.assertTrue(library[name]["action_ribbon_fg"])
            self.assertTrue(library[name]["action_ribbon_border"])

    def test_high_visibility_theme_keeps_explicit_readable_ribbon_colors(self):
        library = starter_theme_library()
        effective = effective_theme_settings(library["High Visibility"])
        self.assertEqual(effective["action_ribbon_bg"], "#FFD60A")
        self.assertEqual(effective["action_ribbon_fg"], "#000000")
        self.assertEqual(effective["action_ribbon_border"], "#FFFFFF")

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
        self.assertEqual(effective["workspace_bg"], "#20242A")
        self.assertEqual(effective["group_title_fg"], "#F7FAFC")
        self.assertEqual(effective["compact_group_bg"], effective["panel_bg"])
        self.assertEqual(effective["toolbar_bg"], effective["panel_bg"])
        self.assertEqual(effective["action_ribbon_bg"], effective["toolbar_bg"])
        self.assertEqual(effective["action_ribbon_fg"], effective["toolbar_fg"])
        self.assertEqual(effective["action_ribbon_border"], effective["toolbar_border"])
        self.assertEqual(effective["statusbar_fg"], "#F7FAFC")
        self.assertEqual(effective["tab_bar_bg"], "#20242A")
        self.assertEqual(effective["tab_pane_bg"], effective["panel_bg"])
        self.assertEqual(effective["progress_fg"], "#F9FAFB")
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
        self.assertIn("color: #F9FAFB", stylesheet)
        self.assertIn("QTabWidget {", stylesheet)
        self.assertIn("QTabWidget::tab-bar {", stylesheet)
        self.assertIn("qproperty-drawBase: 0", stylesheet)
        self.assertIn("QTabBar {", stylesheet)
        self.assertIn("QTabBar::tab:selected", stylesheet)
        self.assertIn("QTabWidget::pane", stylesheet)
        self.assertIn('QWidget[role="workspaceCanvas"]', stylesheet)
        self.assertIn('QWidget[role="tabPaneCanvas"]', stylesheet)
        self.assertIn("QHeaderView {", stylesheet)
        self.assertIn("QTableCornerButton::section", stylesheet)
        self.assertIn("QToolBar", stylesheet)
        self.assertIn("QToolBar#actionRibbonToolbar", stylesheet)
        self.assertIn('QToolBar[role="actionRibbonToolbar"]', stylesheet)
        self.assertIn('QToolBar[role="actionRibbonToolbar"]::separator', stylesheet)
        self.assertIn("QStatusBar", stylesheet)
        self.assertIn('QFrame[role="compactControlGroup"]', stylesheet)
        self.assertIn('QWidget[role="compactControlGroup"]', stylesheet)
        self.assertIn("QComboBox::drop-down", stylesheet)
        self.assertIn("QComboBox::down-arrow", stylesheet)
        self.assertIn("QComboBox QAbstractItemView", stylesheet)
        self.assertIn("background-color:", stylesheet)
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
            self.assertIn("Action Ribbon", labels)
            self.assertIn("Blob Icons", labels)
            self.assertIn("Advanced QSS", labels)
            for key in (
                "workspace_bg",
                "group_title_fg",
                "compact_group_bg",
                "progress_fg",
                "header_border",
                "toolbar_bg",
                "action_ribbon_bg",
                "action_ribbon_fg",
                "action_ribbon_border",
                "statusbar_bg",
                "tab_bar_bg",
                "tab_pane_bg",
            ):
                self.assertIn(key, dialog._theme_color_edits)

            dialog._theme_color_edits["button_hover_bg"].setText("#224488")
            dialog._theme_color_edits["menu_selected_bg"].setText("#BB5500")
            dialog._theme_color_edits["toolbar_bg"].setText("#1F2937")
            dialog._theme_color_edits["action_ribbon_bg"].setText("#0F4C81")
            dialog._theme_color_edits["tab_pane_bg"].setText("#0F172A")
            dialog._theme_metric_spins["menu_radius"].setValue(14)
            dialog._theme_metric_spins["dialog_title_font_size"].setValue(22)
            dialog._blob_icon_editors["audio"].emoji_edit.setText("🎧")
            dialog._blob_icon_editors["audio_lossy"].emoji_edit.setText("📼")
            values = dialog.values()

            self.assertEqual(values["theme_settings"]["button_hover_bg"], "#224488")
            self.assertEqual(values["theme_settings"]["menu_selected_bg"], "#BB5500")
            self.assertEqual(values["theme_settings"]["toolbar_bg"], "#1F2937")
            self.assertEqual(values["theme_settings"]["action_ribbon_bg"], "#0F4C81")
            self.assertEqual(values["theme_settings"]["tab_pane_bg"], "#0F172A")
            self.assertEqual(values["theme_settings"]["menu_radius"], 14)
            self.assertEqual(values["theme_settings"]["dialog_title_font_size"], 22)
            self.assertEqual(values["blob_icon_settings"]["audio"]["emoji"], "🎧")
            self.assertEqual(values["blob_icon_settings"]["audio_lossy"]["emoji"], "📼")
            self.assertEqual(sorted(dialog._blob_icon_editors), ["audio", "audio_lossy", "image"])
        finally:
            dialog.close()
            host.close()

    def test_application_settings_dialog_applies_history_retention_presets(self):
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
            history_retention_mode="balanced",
            parent=host,
        )
        try:
            self.assertEqual(dialog.values()["history_retention_mode"], "balanced")
            lean_index = next(
                index
                for index in range(dialog.history_retention_mode_combo.count())
                if dialog.history_retention_mode_combo.itemData(index) == "lean"
            )
            dialog.history_retention_mode_combo.setCurrentIndex(lean_index)
            self.assertEqual(dialog.values()["history_retention_mode"], "lean")
            self.assertEqual(dialog.values()["history_auto_snapshot_keep_latest"], 10)
            self.assertEqual(dialog.values()["history_prune_pre_restore_copies_after_days"], 7)

            dialog.history_auto_snapshot_keep_latest_spin.setValue(13)
            self.assertEqual(dialog.values()["history_retention_mode"], "custom")
        finally:
            dialog.close()
            host.close()

    def test_apply_theme_with_loading_prepares_payload_before_ui_apply(self):
        host = _ThemeApplyHost()
        previous_stylesheet = self.app.styleSheet()
        previous_font = self.app.font()
        try:
            host._apply_theme_with_loading(
                {
                    "font_family": "Courier New",
                    "font_size": 13,
                    "window_bg": "#101820",
                    "window_fg": "#F8FAFC",
                    "accent": "#F97316",
                }
            )

            self.assertEqual(len(host.submissions), 1)
            submission = host.submissions[0]
            self.assertTrue(submission["show_dialog"])
            self.assertEqual(submission["unique_key"], "theme.apply.prepare")
            self.assertEqual(self.app.font().pointSize(), 13)
            self.assertTrue(self.app.styleSheet())
            self.assertGreater(host.boundary_refresh_count, 0)
        finally:
            self.app.setStyleSheet(previous_stylesheet)
            self.app.setFont(previous_font)
            host.close()

    def test_application_settings_dialog_lists_bundled_themes_and_protects_delete(self):
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
            combo_names = [
                dialog.theme_preset_combo.itemText(index)
                for index in range(dialog.theme_preset_combo.count())
            ]
            for name in starter_theme_names():
                self.assertIn(name, combo_names)

            apple_light_index = dialog.theme_preset_combo.findData("Apple Light")
            self.assertGreaterEqual(apple_light_index, 0)
            dialog.theme_preset_combo.setCurrentIndex(apple_light_index)
            dialog._update_theme_preset_actions()
            self.assertFalse(dialog.theme_delete_button.isEnabled())
        finally:
            dialog.close()
            host.close()

    def test_color_swatch_uses_explicit_color_fill(self):
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
            dialog._theme_color_edits["button_hover_bg"].setText("#224488")
            swatch = dialog._theme_color_swatches["button_hover_bg"]
            self.assertEqual(swatch.text(), "")
            self.assertIn("background-color: #224488".lower(), swatch.styleSheet().lower())
            self.assertEqual(swatch.toolTip(), "#224488".upper())
        finally:
            dialog.close()
            host.close()

    def test_auto_color_swatch_uses_effective_resolved_color(self):
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
            theme_settings={"accent": "#118AB2"},
            stored_themes={},
            current_profile_path="",
            parent=host,
        )
        try:
            dialog._theme_color_edits["help_button_bg"].clear()
            swatch = dialog._theme_color_swatches["help_button_bg"]
            self.assertEqual(swatch.text(), "A")
            self.assertIn("background-color: #118ab2", swatch.styleSheet().lower())
            self.assertIn("Resolved preview: #118AB2", swatch.toolTip())
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

            action_ribbon_index = next(
                index
                for index in range(dialog.theme_builder_tabs.count())
                if dialog.theme_builder_tabs.tabText(index) == "Action Ribbon"
            )
            dialog.theme_builder_tabs.setCurrentIndex(action_ribbon_index)
            self.app.processEvents()
            self.assertEqual(
                dialog.theme_preview_tabs.tabText(dialog.theme_preview_tabs.currentIndex()),
                "Action Ribbon",
            )

            blob_icons_index = next(
                index
                for index in range(dialog.theme_builder_tabs.count())
                if dialog.theme_builder_tabs.tabText(index) == "Blob Icons"
            )
            dialog.theme_builder_tabs.setCurrentIndex(blob_icons_index)
            self.app.processEvents()
            self.assertEqual(
                dialog.theme_preview_tabs.tabText(dialog.theme_preview_tabs.currentIndex()),
                "Blob Icons",
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
