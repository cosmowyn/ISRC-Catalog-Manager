import unittest
from unittest import mock

from PySide6.QtCore import QModelIndex, QPoint
from PySide6.QtGui import QStandardItem, QStandardItemModel

from isrc_manager.promo_codes import dialogs as promo_dialogs
from isrc_manager.promo_codes.models import (
    PromoCodeImportResult,
    PromoCodeRecord,
    PromoCodeSheetRecord,
)
from tests.qt_test_helpers import require_qapplication

_SORT_ROLE = promo_dialogs._SORT_ROLE
_REDEEMED_ROLE = promo_dialogs._REDEEMED_ROLE
_SEARCH_TEXT_ROLE = promo_dialogs._SEARCH_TEXT_ROLE


def _build_model(rows: list[dict[str, object]]) -> QStandardItemModel:
    model = QStandardItemModel()
    for row_index, data in enumerate(rows):
        item = QStandardItem(str(data.get("label", "")))
        item.setData(bool(data.get("redeemed", False)), _REDEEMED_ROLE)
        item.setData(str(data.get("search", "")), _SEARCH_TEXT_ROLE)
        item.setData(data.get("sort", 0), _SORT_ROLE)
        model.setItem(row_index, 0, item)
    return model


class PromoCodeFilterProxyModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def test_clean_search_text_and_search_tokens(self):
        self.assertEqual(
            promo_dialogs._clean_search_text("  Hello   WORLD!  "),
            "hello world!",
        )
        self.assertEqual(
            promo_dialogs._search_tokens("abc-DEF  test@EXAMPLE.com\nfoo_bar"),
            ["abc-", "test@", ".com", "foo_bar"],
        )

    def test_filter_status_mode_and_short_query_behaviour(self):
        model = _build_model(
            [
                {"label": "Code A", "redeemed": False, "search": "alpha first", "sort": 1},
                {"label": "Code B", "redeemed": True, "search": "beta second", "sort": 2},
            ]
        )
        proxy = promo_dialogs._PromoCodeFilterProxyModel()
        proxy.setSourceModel(model)

        proxy.set_status_filter("available")
        self.assertTrue(proxy.filterAcceptsRow(0, QModelIndex()))
        self.assertFalse(proxy.filterAcceptsRow(1, QModelIndex()))

        proxy.set_status_filter("redeemed")
        self.assertFalse(proxy.filterAcceptsRow(0, QModelIndex()))
        self.assertTrue(proxy.filterAcceptsRow(1, QModelIndex()))

        proxy.set_status_filter("invalid-mode")
        self.assertTrue(proxy.filterAcceptsRow(0, QModelIndex()))
        self.assertFalse(proxy.filterAcceptsRow(1, QModelIndex()))

        proxy.set_search_text("alx")
        self.assertFalse(proxy.filterAcceptsRow(0, QModelIndex()))

    def test_filter_uses_exact_and_fuzzy_search_paths(self):
        model = _build_model(
            [
                {
                    "label": "One",
                    "redeemed": False,
                    "search": "promo alpha code",
                    "sort": 1,
                },
                {
                    "label": "Two",
                    "redeemed": False,
                    "search": "watermark ledger",
                    "sort": 2,
                },
            ]
        )
        proxy = promo_dialogs._PromoCodeFilterProxyModel()
        proxy.set_status_filter("all")
        proxy.setSourceModel(model)

        proxy.set_search_text("promo alpha")
        self.assertTrue(proxy.filterAcceptsRow(0, QModelIndex()))
        self.assertFalse(proxy.filterAcceptsRow(1, QModelIndex()))

        proxy.set_search_text("promp")
        self.assertTrue(proxy.filterAcceptsRow(0, QModelIndex()))

    def test_less_than_uses_sort_role_and_row_tie_breaker(self):
        model = _build_model(
            [
                {"label": "A", "redeemed": False, "search": "", "sort": 1},
                {"label": "B", "redeemed": False, "search": "", "sort": 1},
                {"label": "C", "redeemed": False, "search": "", "sort": 2},
            ]
        )
        proxy = promo_dialogs._PromoCodeFilterProxyModel()
        proxy.setSourceModel(model)

        self.assertTrue(
            promo_dialogs._PromoCodeFilterProxyModel.lessThan(
                proxy,
                model.index(0, 0),
                model.index(2, 0),
            )
        )
        self.assertTrue(
            promo_dialogs._PromoCodeFilterProxyModel.lessThan(
                proxy,
                model.index(0, 0),
                model.index(1, 0),
            )
        )
        self.assertFalse(
            promo_dialogs._PromoCodeFilterProxyModel.lessThan(
                proxy,
                model.index(1, 0),
                model.index(0, 0),
            )
        )


class _FakePromoService:
    def __init__(
        self,
        sheets: list[PromoCodeSheetRecord] | None = None,
        codes_by_sheet: dict[int, list[PromoCodeRecord]] | None = None,
        *,
        list_codes_error: Exception | None = None,
        update_error: Exception | None = None,
    ) -> None:
        self._sheets = list(sheets or [])
        self._codes_by_sheet = dict(codes_by_sheet or {})
        self.list_codes_error = list_codes_error
        self.update_error = update_error
        self.updated_codes: list[tuple[int, bool, str | None, str | None, str | None]] = []
        self.list_sheets_calls = 0

    def list_sheets(self) -> list[PromoCodeSheetRecord]:
        self.list_sheets_calls += 1
        return list(self._sheets)

    def list_codes(self, sheet_id: int) -> list[PromoCodeRecord]:
        if self.list_codes_error is not None:
            raise self.list_codes_error
        return list(self._codes_by_sheet.get(int(sheet_id), []))

    def update_code_ledger(
        self,
        code_id: int,
        *,
        redeemed: bool,
        recipient_name: str | None,
        recipient_email: str | None,
        ledger_notes: str | None,
    ) -> PromoCodeRecord:
        if self.update_error is not None:
            raise self.update_error
        self.updated_codes.append(
            (code_id, redeemed, recipient_name, recipient_email, ledger_notes)
        )
        for codes in self._codes_by_sheet.values():
            for code in codes:
                if int(code.id) != int(code_id):
                    continue
                return PromoCodeRecord(
                    id=code.id,
                    sheet_id=code.sheet_id,
                    code=code.code,
                    sort_order=code.sort_order,
                    redeemed=redeemed,
                    recipient_name=recipient_name,
                    recipient_email=recipient_email,
                    ledger_notes=ledger_notes,
                    provided_at=code.provided_at,
                    redeemed_at=code.redeemed_at,
                    created_at=code.created_at,
                    updated_at=code.updated_at,
                )
        return PromoCodeRecord(
            id=code_id,
            sheet_id=999,
            code="UNKNOWN",
            sort_order=0,
            redeemed=redeemed,
            recipient_name=recipient_name,
            recipient_email=recipient_email,
            ledger_notes=ledger_notes,
            provided_at=None,
            redeemed_at=None,
            created_at=None,
            updated_at=None,
        )


def _sheet_record(
    sheet_id: int = 1, code_set_name: str = "Summer", album: str = "Promo"
) -> PromoCodeSheetRecord:
    return PromoCodeSheetRecord(
        id=sheet_id,
        code_set_name=code_set_name,
        album=album,
        bandcamp_date_created="2026-01-01",
        bandcamp_date_exported="2026-01-02",
        quantity_created=10,
        quantity_redeemed_to_date=2,
        redeem_url="https://bandcamp.com/redeem",
        source_filename="codes.csv",
        source_path="/tmp/codes.csv",
        source_sha256="sha256-a",
        code_sequence_sha256="seq-a",
        profile_name="default",
        imported_at="2026-01-03",
        updated_at="2026-01-03",
        total_codes=10,
        redeemed_codes=2,
    )


def _code_record(
    *,
    code_id: int = 1,
    sheet_id: int = 1,
    code: str = "ABC-1",
    redeemed: bool = False,
    sort_order: int = 1,
) -> PromoCodeRecord:
    return PromoCodeRecord(
        id=code_id,
        sheet_id=sheet_id,
        code=code,
        sort_order=sort_order,
        redeemed=redeemed,
        recipient_name="Alex",
        recipient_email="alex@example.com",
        ledger_notes="First wave",
        provided_at="2026-01-10",
        redeemed_at="2026-01-11" if redeemed else None,
        created_at="2026-01-09",
        updated_at="2026-01-10",
    )


class PromoCodeLedgerPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def test_refresh_handles_unavailable_service(self):
        panel = promo_dialogs.PromoCodeLedgerPanel(service_provider=lambda: 1 / 0)

        self.assertEqual(panel.sheet_combo.itemText(0), "Open a profile first")
        self.assertEqual(panel.status_label.text(), "Promo code service is unavailable.")
        self.assertFalse(panel.copy_button.isEnabled())
        self.assertEqual(panel.sheet_detail_label.text(), "")

    def test_refresh_handles_no_sheets(self):
        panel = promo_dialogs.PromoCodeLedgerPanel(
            service_provider=lambda: _FakePromoService(sheets=[])
        )

        self.assertEqual(panel.sheet_combo.itemText(0), "No promo-code sheets imported")
        self.assertEqual(panel.model.rowCount(), 0)
        self.assertFalse(panel.copy_button.isEnabled())
        self.assertIn("No Bandcamp promo-code sheets", panel.status_label.text())

    def test_populates_codes_and_summary_when_sheet_has_rows(self):
        service = _FakePromoService(
            sheets=[_sheet_record()],
            codes_by_sheet={
                1: [
                    _code_record(),
                    _code_record(code_id=2, code="ABC-2", redeemed=True, sort_order=2),
                ]
            },
        )
        panel = promo_dialogs.PromoCodeLedgerPanel(service_provider=lambda: service)

        self.assertEqual(panel.model.rowCount(), 2)
        self.assertEqual(panel.current_sheet_id(), 1)
        self.assertIn("10 total", panel.sheet_detail_label.text())
        self.assertIn("Bandcamp:", panel.sheet_detail_label.text())
        self.assertEqual(panel._selected_code_id(), 1)
        selected = panel._selected_code()
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.code, "ABC-1")

    def test_refresh_current_sheet_lists_codes(self):
        sheet = _sheet_record(sheet_id=7, code_set_name="Live", album="Night")
        service = _FakePromoService(
            sheets=[sheet],
            codes_by_sheet={7: [_code_record(code_id=42, sheet_id=7, code="LIVE-42")]},
        )
        panel = promo_dialogs.PromoCodeLedgerPanel(service_provider=lambda: service)

        summary = panel._sheet_summary(sheet)
        self.assertIn("10 total", summary)
        self.assertEqual(panel.current_sheet_id(), 7)
        self.assertEqual(int(panel.sheet_combo.itemData(0)), 7)

        with mock.patch("isrc_manager.promo_codes.dialogs.QMessageBox.critical") as critical:
            service_with_errors = _FakePromoService(
                sheets=[sheet],
                codes_by_sheet={},
                list_codes_error=RuntimeError("boom"),
            )
            panel_error = promo_dialogs.PromoCodeLedgerPanel(
                service_provider=lambda: service_with_errors
            )
            critical.assert_called_once()
            self.assertEqual(panel_error.status_label.text(), "Could not load promo-code rows.")

    def test_sheet_summary_reports_optional_fields(self):
        sheet = _sheet_record()
        panel = promo_dialogs.PromoCodeLedgerPanel(
            service_provider=lambda: _FakePromoService(
                sheets=[sheet], codes_by_sheet={1: [_code_record()]}
            )
        )
        summary = panel._sheet_summary(sheet)
        self.assertIn("10 total", summary)
        self.assertIn("8 available", summary)
        self.assertIn("2 redeemed", summary)
        self.assertIn("created 2026-01-01", summary)
        self.assertIn("2 redeemed on Bandcamp", summary)
        self.assertIn("https://bandcamp.com/redeem", summary)
        panel.close()

    def test_choose_import_file_branches(self):
        panel = promo_dialogs.PromoCodeLedgerPanel(
            service_provider=lambda: _FakePromoService(sheets=[])
        )
        with mock.patch(
            "isrc_manager.promo_codes.dialogs.QFileDialog.getOpenFileName", return_value=("", "")
        ):
            panel._choose_import_file()

        handler = mock.Mock()
        panel_with_handler = promo_dialogs.PromoCodeLedgerPanel(
            service_provider=lambda: _FakePromoService(sheets=[]),
            import_handler=handler,
        )
        with mock.patch(
            "isrc_manager.promo_codes.dialogs.QFileDialog.getOpenFileName",
            return_value=("/tmp/ok.csv", ""),
        ):
            panel_with_handler._choose_import_file()
            handler.assert_called_once()
            called_path, _parent, callback = handler.call_args.args
            self.assertEqual(called_path, "/tmp/ok.csv")
            self.assertIs(callback.__self__, panel_with_handler)
            self.assertIs(callback.__func__, panel_with_handler._handle_import_complete.__func__)

        with mock.patch(
            "isrc_manager.promo_codes.dialogs.QFileDialog.getOpenFileName",
            return_value=("/tmp/ok.csv", ""),
        ):
            with mock.patch("isrc_manager.promo_codes.dialogs.QMessageBox.warning") as warning:
                promo_dialogs.PromoCodeLedgerPanel(
                    service_provider=lambda: _FakePromoService(sheets=[]),
                    import_handler=None,
                )._choose_import_file()
                warning.assert_called_once_with(
                    mock.ANY,
                    "Promo Code Ledger",
                    "Import is unavailable.",
                )

    def test_handle_import_complete_updates_status_message(self):
        sheet = _sheet_record()
        service = _FakePromoService(sheets=[sheet], codes_by_sheet={1: [_code_record()]})
        panel = promo_dialogs.PromoCodeLedgerPanel(service_provider=lambda: service)

        imported = PromoCodeImportResult(
            sheet_id=1,
            sheet_name="Summer",
            album="Promo",
            total_codes=1,
            inserted_codes=1,
            updated_existing_sheet=False,
            source_path="codes.csv",
        )
        panel._handle_import_complete(imported)
        self.assertIn("Imported 'Summer' with 1 code(s).", panel.status_label.text())

        updated = PromoCodeImportResult(
            sheet_id=1,
            sheet_name="Summer",
            album="Promo",
            total_codes=1,
            inserted_codes=1,
            updated_existing_sheet=True,
            source_path="codes.csv",
            active_codes=3,
            marked_redeemed_codes=1,
            reactivated_codes=2,
        )
        panel._handle_import_complete(updated)
        self.assertIn("Updated 'Summer': 3 active code(s)", panel.status_label.text())
        self.assertIn("1 marked redeemed", panel.status_label.text())
        self.assertIn("1 new", panel.status_label.text())
        self.assertIn("2 reactivated", panel.status_label.text())

    def test_copy_and_save_selected_code_paths(self):
        service = _FakePromoService(sheets=[_sheet_record()], codes_by_sheet={1: [_code_record()]})
        panel = promo_dialogs.PromoCodeLedgerPanel(service_provider=lambda: service)

        fake_clipboard = mock.Mock()
        fake_app = mock.Mock()
        fake_app.clipboard.return_value = fake_clipboard
        with mock.patch(
            "isrc_manager.promo_codes.dialogs.QApplication.instance", return_value=fake_app
        ):
            panel.copy_selected_code()
            fake_clipboard.setText.assert_called_once_with("ABC-1")

        panel.recipient_name_edit.setText("New Name")
        panel.recipient_email_edit.setText("new@example.com")
        panel.notes_edit.setPlainText("Updated")
        panel._save_selected_code()
        self.assertEqual(panel._code_rows_by_id[1].recipient_name, "New Name")
        self.assertEqual(panel.status_label.text(), "Updated code ABC-1.")
        self.assertEqual(
            service.updated_codes[0], (1, False, "New Name", "new@example.com", "Updated")
        )

        # Exercise explicit branch that passes redeemed flag directly.
        panel._save_selected_code(redeemed=True)
        self.assertEqual(
            service.updated_codes[1], (1, True, "New Name", "new@example.com", "Updated")
        )

    def test_save_selected_code_uses_update_handler_and_handles_failures(self):
        service_with_code = _FakePromoService(
            sheets=[_sheet_record()],
            codes_by_sheet={1: [_code_record()]},
        )
        called: list[tuple[int, bool, str | None, str | None, str | None]] = []

        def handler(
            code_id: int,
            redeemed: bool,
            recipient_name: str | None,
            recipient_email: str | None,
            notes: str | None,
        ) -> PromoCodeRecord:
            called.append((code_id, redeemed, recipient_name, recipient_email, notes))
            return PromoCodeRecord(
                id=code_id,
                sheet_id=1,
                code="ABC-1",
                sort_order=1,
                redeemed=redeemed,
                recipient_name=recipient_name,
                recipient_email=recipient_email,
                ledger_notes=notes,
                provided_at=None,
                redeemed_at=None,
                created_at=None,
                updated_at=None,
            )

        panel_with_codes = promo_dialogs.PromoCodeLedgerPanel(
            service_provider=lambda: service_with_code,
            ledger_update_handler=handler,
        )
        panel_with_codes._save_selected_code()
        self.assertEqual(len(called), 1)
        self.assertEqual(called[0][1], False)

        service_with_error = _FakePromoService(
            sheets=[_sheet_record()],
            codes_by_sheet={1: [_code_record()]},
            update_error=RuntimeError("broken"),
        )
        panel_with_error = promo_dialogs.PromoCodeLedgerPanel(
            service_provider=lambda: service_with_error,
        )
        with mock.patch("isrc_manager.promo_codes.dialogs.QMessageBox.critical") as critical:
            panel_with_error._save_selected_code()
            critical.assert_called_once()

    def test_filter_and_selection_helpers(self):
        service = _FakePromoService(
            sheets=[_sheet_record()],
            codes_by_sheet={
                1: [
                    _code_record(),
                    _code_record(code_id=3, code="ABC-3", redeemed=True, sort_order=3),
                ]
            },
        )
        panel = promo_dialogs.PromoCodeLedgerPanel(service_provider=lambda: service)

        self.assertEqual(panel._selected_code_id(), 1)
        panel.table.clearSelection()
        if panel.table.selectionModel() is not None:
            panel.table.selectionModel().clearCurrentIndex()
        self.assertIsNone(panel._selected_code_id())
        panel.table.selectRow(0)

        panel._selected_code_id()
        self.assertEqual(panel._selected_code().code, "ABC-1")
        panel.search_edit.setText("missing")
        panel.status_combo.setCurrentIndex(panel.status_combo.findData("all"))
        panel._apply_filters()
        self.assertIn("Showing", panel.status_label.text())
        with mock.patch("isrc_manager.promo_codes.dialogs.QMessageBox.warning") as warning:
            panel._apply_filters()
            self.assertFalse(warning.called)

    def test_context_menu_and_focus_behaviors(self):
        service = _FakePromoService(
            sheets=[_sheet_record()],
            codes_by_sheet={1: [_code_record()]},
        )
        panel = promo_dialogs.PromoCodeLedgerPanel(service_provider=lambda: service)

        panel.focus_sheet(1)
        self.assertEqual(panel.current_sheet_id(), 1)
        panel.focus_sheet(999)
        with (
            mock.patch("isrc_manager.promo_codes.dialogs.QMenu") as menu_class,
            mock.patch("isrc_manager.promo_codes.dialogs.QAction") as action_class,
        ):
            menu = mock.Mock()
            menu_class.return_value = menu
            action_class.side_effect = lambda *args, **kwargs: mock.Mock(triggered=mock.Mock())
            panel._open_table_context_menu(QPoint(1, 2))
            menu.exec.assert_called_once()

            panel._selected_code_id()
            menu.reset_mock()
            panel.model.clear()
            panel._open_table_context_menu(QPoint(3, 4))
            menu.exec.assert_not_called()


if __name__ == "__main__":
    unittest.main()
