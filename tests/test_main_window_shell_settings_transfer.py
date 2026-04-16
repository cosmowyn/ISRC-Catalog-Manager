import unittest

try:
    from PySide6.QtWidgets import QApplication, QMainWindow
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QMainWindow = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.main_window_shell import _build_actions_and_menus


class _ShellStub(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_db_path = ""
        self._triggered = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def _noop(*args, **kwargs):
            self._triggered.append((name, args, kwargs))
            return None

        return _noop

    def _create_action(
        self,
        text,
        *,
        slot=None,
        toggled_slot=None,
        checkable=False,
        checked=None,
        shortcuts=(),
        standard_key=None,
        role=None,
    ):
        from PySide6.QtGui import QAction, QKeySequence

        action = QAction(text, self)
        if role is not None:
            action.setMenuRole(role)
        if checkable:
            action.setCheckable(True)
            if checked is not None:
                action.setChecked(bool(checked))
        if standard_key is not None:
            action.setShortcuts(QKeySequence.keyBindings(standard_key))
        elif shortcuts:
            action.setShortcuts([QKeySequence(seq) for seq in shortcuts])
        if slot is not None:
            action.triggered.connect(slot)
        if toggled_slot is not None:
            action.toggled.connect(toggled_slot)
        self.addAction(action)
        return action


class MainWindowShellSettingsTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_menu_exposes_export_and_import_actions(self):
        shell = _ShellStub()
        try:
            _build_actions_and_menus(shell, movable=False)

            settings_action = next(
                action
                for action in shell.menu_bar.actions()
                if action.text() == "Settings" and action.menu() is not None
            )
            settings_menu = settings_action.menu()
            self.assertIsNotNone(settings_menu)
            assert settings_menu is not None

            settings_texts = [action.text() for action in settings_menu.actions() if action.text()]
            self.assertEqual(
                settings_texts,
                [
                    "Application Settings…",
                    "Export Settings…",
                    "Import Settings…",
                    "Audio Authenticity Keys…",
                ],
            )

            shell.export_settings_action.trigger()
            shell.import_settings_action.trigger()
            self.app.processEvents()

            self.assertTrue(
                any(
                    name == "export_application_settings_bundle"
                    for name, _args, _kwargs in shell._triggered
                )
            )
            self.assertTrue(
                any(
                    name == "import_application_settings_bundle"
                    for name, _args, _kwargs in shell._triggered
                )
            )
        finally:
            shell.close()


if __name__ == "__main__":
    unittest.main()
