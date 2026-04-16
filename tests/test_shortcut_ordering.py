import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QMainWindow

import ISRC_manager as app_module


class _ShortcutOwner(QMainWindow):
    _create_action = app_module.App._create_action
    _install_explicit_action_shortcuts = app_module.App._install_explicit_action_shortcuts
    _ordered_custom_shortcuts = app_module.App._ordered_custom_shortcuts
    _platform_variant_shortcut_group = app_module.App._platform_variant_shortcut_group
    _should_register_explicit_action_shortcuts = (
        app_module.App._should_register_explicit_action_shortcuts
    )
    _trigger_explicit_action_shortcut = app_module.App._trigger_explicit_action_shortcut

    def _log_event(self, *_args, **_kwargs):
        return None


class ShortcutOrderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _shortcut_helper_owner(self):
        owner = type("ShortcutOwner", (), {})()
        owner._platform_variant_shortcut_group = (
            lambda portable_text: app_module.App._platform_variant_shortcut_group(
                owner, portable_text
            )
        )
        return owner

    def test_platform_specific_modifier_variant_becomes_primary(self):
        owner = self._shortcut_helper_owner()

        ordered = app_module.App._ordered_custom_shortcuts(
            owner,
            ["Ctrl+Alt+N", "Meta+Alt+N"],
        )

        self.assertEqual(
            [shortcut.toString(QKeySequence.PortableText) for shortcut in ordered],
            ["Ctrl+Alt+N", "Meta+Alt+N"],
        )

    def test_non_variant_shortcuts_keep_their_original_order(self):
        owner = self._shortcut_helper_owner()

        ordered = app_module.App._ordered_custom_shortcuts(
            owner,
            ["Delete", "Meta+Backspace"],
        )

        self.assertEqual(
            [shortcut.toString(QKeySequence.PortableText) for shortcut in ordered],
            [
                QKeySequence("Delete").toString(QKeySequence.PortableText),
                QKeySequence("Meta+Backspace").toString(QKeySequence.PortableText),
            ],
        )

    def test_multi_modifier_custom_actions_use_explicit_window_shortcuts(self):
        owner = _ShortcutOwner()

        action = owner._create_action(
            "Application Settings…",
            shortcuts=("Ctrl+,", "Meta+,"),
        )

        self.assertEqual(action.shortcutContext(), Qt.WidgetShortcut)
        registered = owner._explicit_action_shortcut_objects[action]
        self.assertEqual(
            [shortcut.key().toString(QKeySequence.PortableText) for shortcut in registered],
            [
                shortcut.toString(QKeySequence.PortableText)
                for shortcut in owner._ordered_custom_shortcuts(("Ctrl+,", "Meta+,"))
            ],
        )

    def test_single_key_custom_actions_keep_qaction_shortcut_handling(self):
        owner = _ShortcutOwner()

        action = owner._create_action(
            "Delete Selected Track",
            shortcuts=("Delete", "Meta+Backspace"),
        )

        self.assertEqual(action.shortcutContext(), Qt.WindowShortcut)
        self.assertFalse(hasattr(owner, "_explicit_action_shortcut_objects"))


if __name__ == "__main__":
    unittest.main()
