import unittest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import QApplication, QMainWindow
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QAction = None
    QKeySequence = None
    QMainWindow = None
    Qt = None
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


class MainWindowShellConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_file_menu_places_conversion_after_export_and_wires_slot(self):
        shell = _ShellStub()
        try:
            _build_actions_and_menus(shell, movable=False)

            file_action = next(
                action
                for action in shell.menu_bar.actions()
                if action.text() == "File" and action.menu() is not None
            )
            file_menu = file_action.menu()
            self.assertIsNotNone(file_menu)
            assert file_menu is not None

            file_texts = [action.text() for action in file_menu.actions() if action.text()]
            self.assertIn("Conversion…", file_texts)
            self.assertLess(file_texts.index("Export"), file_texts.index("Conversion…"))
            self.assertTrue(hasattr(shell, "conversion_action"))
            self.assertEqual(shell.conversion_action.text(), "Conversion…")

            shell.conversion_action.trigger()
            self.app.processEvents()

            self.assertTrue(
                any(name == "open_conversion_dialog" for name, _args, _kwargs in shell._triggered)
            )
        finally:
            shell.close()


if __name__ == "__main__":
    unittest.main()
