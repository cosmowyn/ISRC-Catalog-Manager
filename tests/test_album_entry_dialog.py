import sqlite3
import unittest
from types import SimpleNamespace
from unittest import mock

from isrc_manager.tracks import album_entry_dialog as album_module
from isrc_manager.tracks.album_entry_dialog import AlbumEntryDialog
from tests.qt_test_helpers import pump_events, require_qapplication


class _WorkService:
    def __init__(self, *, raise_on_list=False, records=(), details=None):
        self.raise_on_list = raise_on_list
        self.records = list(records)
        self.details = dict(details or {})

    def list_works(self):
        if self.raise_on_list:
            raise RuntimeError("work lookup failed")
        return list(self.records)

    def fetch_work_detail(self, work_id):
        return self.details.get(int(work_id))


class _AlbumHost(album_module.QWidget):
    def __init__(self, *, auto_isrc_ready=False, work_service=None):
        super().__init__()
        self.conn = sqlite3.connect(":memory:")
        self._create_lookup_schema()
        self.cursor = self.conn.cursor()
        self.code_registry_service = None
        self.work_service = work_service or _WorkService()
        self.track_service = object()
        self.auto_isrc_ready = bool(auto_isrc_ready)
        self.confirm_audio = True
        self.chosen_media_modes = ("managed_file", "database")
        self.next_generated_isrc = "NL-C01-23-00001"
        self.taken_isrcs: set[str] = set()
        self.duplicate_warnings = []
        self.reservation_results: list[bool] = []
        self.reserved_claims = []
        self.released_claims = []
        self.submitted_tasks = []
        self.artist_configurations = []
        self.track_titles = {7: ""}

    def _create_lookup_schema(self):
        self.conn.execute("CREATE TABLE Albums(title TEXT)")
        self.conn.execute("CREATE TABLE Tracks(upc TEXT, genre TEXT, catalog_number TEXT)")
        self.conn.execute("CREATE TABLE Releases(upc TEXT, catalog_number TEXT)")
        self.conn.executemany("INSERT INTO Albums(title) VALUES (?)", [("Existing Album",)])
        self.conn.executemany(
            "INSERT INTO Tracks(upc, genre, catalog_number) VALUES (?, ?, ?)",
            [("8720892724990", "Ambient", "CAT-001")],
        )
        self.conn.executemany(
            "INSERT INTO Releases(upc, catalog_number) VALUES (?, ?)",
            [("8720892724990", "REL-001")],
        )
        self.conn.commit()

    def close(self):
        super().close()
        self.conn.close()

    def _isrc_generation_state(self):
        if self.auto_isrc_ready:
            return "ready", ""
        return "disabled", "Automatic ISRC generation is unavailable in this test profile."

    def _work_track_relationship_choices(self):
        return ("original", "remix", "alternate_master")

    def _work_track_relationship_label(self, value):
        return {
            "original": "Original",
            "remix": "Remix",
            "alternate_master": "Alternate Master",
        }.get(str(value or ""), "Original")

    def _normalize_work_track_relationship(self, value):
        clean_value = str(value or "").strip()
        return clean_value if clean_value in self._work_track_relationship_choices() else "original"

    def _get_track_title(self, track_id):
        return self.track_titles.get(int(track_id), "")

    def _configure_artist_party_combo(
        self,
        combo,
        *,
        allow_empty,
        selected_party_id=None,
        current_text="",
    ):
        self.artist_configurations.append((allow_empty, selected_party_id, str(current_text or "")))
        combo.setEditable(True)
        combo.clear()
        if allow_empty:
            combo.addItem("", None)
        combo.addItem("Moonwake", 41)
        combo.addItem("Signal Guest", 42)
        if current_text:
            combo.setCurrentText(current_text)
        elif selected_party_id is not None:
            index = combo.findData(selected_party_id)
            if index >= 0:
                combo.setCurrentIndex(index)

    def _resolve_artist_party_choice(self, combo):
        data = combo.currentData()
        return combo.currentText(), int(data) if isinstance(data, int) else None

    def _resolve_party_backed_artist_name(self, name, *, selected_party_id=None, cursor=None):
        return str(name or "").strip(), selected_party_id

    def _parse_additional_artists(self, text):
        return [part.strip() for part in str(text or "").split(",") if part.strip()]

    def _resolve_party_backed_additional_artist_names(self, names, *, cursor=None):
        return [str(name).strip() for name in names if str(name).strip()]

    def _refresh_line_edit_lossy_audio_warning(self, line_edit):
        label = getattr(line_edit, "_lossy_audio_warning_label", None)
        if label is not None:
            label.setVisible(False)

    def _choose_media_into_line_edit(self, *_args, **_kwargs):
        return None

    def _confirm_lossy_primary_audio_selection(self, paths, **kwargs):
        self.last_lossy_paths = list(paths)
        self.last_lossy_kwargs = dict(kwargs)
        return self.confirm_audio

    def _choose_track_media_storage_modes(self, **kwargs):
        self.last_media_mode_request = dict(kwargs)
        return self.chosen_media_modes

    def _next_generated_isrc(self, **kwargs):
        self.last_generated_isrc_kwargs = dict(kwargs)
        return self.next_generated_isrc

    def is_isrc_taken_normalized(self, isrc):
        return str(isrc or "") in self.taken_isrcs

    def _warn_duplicate_track_numbers(self, **kwargs):
        self.duplicate_warnings.append(dict(kwargs))

    def _reserve_isrc_claim_for_profile(self, isrc, **kwargs):
        self.reserved_claims.append((isrc, dict(kwargs)))
        if self.reservation_results:
            return self.reservation_results.pop(0)
        return True

    def _release_reserved_isrc_claim(self, isrc):
        self.released_claims.append(isrc)

    def _capture_catalog_refresh_request(self):
        return {"scope": "current"}

    def _current_profile_name(self):
        return "Album Test Profile"

    def _submit_background_bundle_task(self, **kwargs):
        self.submitted_tasks.append(dict(kwargs))
        return "submitted"


class AlbumEntryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def setUp(self):
        self._hosts = []
        self._dialogs = []

    def tearDown(self):
        for dialog in reversed(self._dialogs):
            dialog.close()
            dialog.deleteLater()
        for host in reversed(self._hosts):
            host.close()
            host.deleteLater()
        pump_events(app=self.app, cycles=2)

    def _host(self, **kwargs):
        host = _AlbumHost(**kwargs)
        self._hosts.append(host)
        return host

    def _dialog(self, host=None, **kwargs):
        dialog = AlbumEntryDialog(host or self._host(), **kwargs)
        self._dialogs.append(dialog)
        pump_events(app=self.app, cycles=1)
        return dialog

    @staticmethod
    def _set_combo_data(combo, data):
        index = combo.findData(data)
        if index < 0:
            raise AssertionError(f"Missing combo data: {data!r}")
        combo.setCurrentIndex(index)

    @staticmethod
    def _fill_valid_section(section, *, title="Track One", artist="Moonwake"):
        section.track_title.setText(title)
        section.artist_name.setCurrentText(artist)

    def test_section_governance_date_and_artist_refresh_edges(self):
        broken_record = SimpleNamespace(id=object(), title="Broken")
        zero_record = SimpleNamespace(id=0, title="Zero")
        missing_host = self._host(
            auto_isrc_ready=True,
            work_service=_WorkService(records=(broken_record, zero_record)),
        )
        missing_dialog = self._dialog(missing_host, work_id=99, relationship_type="bad")
        section = missing_dialog._track_sections[0]

        self.assertEqual(section.isrc.placeholderText(), "Leave blank to auto-generate on save")
        self.assertGreaterEqual(section.parent_work.findText("Missing Work #99"), 0)
        section.parent_work.addItem("Bad Work Data", object())
        section.parent_work.setCurrentIndex(section.parent_work.count() - 1)
        self.assertIsNone(section.selected_work_id())
        section.parent_track.addItem("Bad Parent Data", object())
        section.parent_track.setCurrentIndex(section.parent_track.count() - 1)
        self.assertIsNone(section.selected_parent_track_id())

        section.set_release_date_iso(" 2026-06-07 ")
        self.assertEqual(section.release_date_iso(), "2026-06-07")
        section.set_release_date_iso(None)
        self.assertIsNone(section.release_date_iso())

        class _AcceptedDateDialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return album_module.QDialog.Accepted

            def selected_iso(self):
                return "2026-06-08"

        with mock.patch.object(album_module, "DatePickerDialog", _AcceptedDateDialog):
            section._pick_release_date()
        self.assertEqual(section.release_date_iso(), "2026-06-08")

        section._setting_track_number_default = True
        section._handle_track_number_changed(8)
        self.assertFalse(section._track_number_dirty)
        section._setting_track_number_default = False
        section._handle_track_number_changed(9)
        self.assertTrue(section._track_number_dirty)

        class _BadSizingWidget:
            def sizeHint(self):
                raise RuntimeError("no hint")

            def fontMetrics(self):
                raise RuntimeError("no font")

        self.assertEqual(
            AlbumEntryDialog._scaled_control_height(_BadSizingWidget(), extra_padding=6),
            6,
        )
        missing_host.work_service.raise_on_list = True
        self.assertEqual(missing_dialog._available_work_records(), [])

        valid_detail = SimpleNamespace(
            work=SimpleNamespace(id=5, title=""),
            track_ids=[7],
        )
        valid_host = self._host(
            work_service=_WorkService(
                records=(SimpleNamespace(id=5, title="", iswc="T-123.456.789-0"),),
                details={5: valid_detail},
            )
        )
        valid_dialog = self._dialog(valid_host, work_id=5, relationship_type="remix")
        valid_section = valid_dialog._track_sections[0]

        self.assertEqual(valid_section.selected_work_id(), 5)
        self.assertEqual(valid_section.selected_relationship_type(), "remix")
        self.assertGreaterEqual(valid_section.parent_track.findText("Track #7"), 0)
        self.assertIn("1 governed track already", valid_section.governance_hint.text())
        valid_dialog._focus_track_section(object())
        valid_dialog._focus_track_section(valid_section)
        self.assertIs(valid_dialog.primary_tabs.currentWidget(), valid_dialog.track_workspace_tab)

        valid_dialog._track_sections.append(
            SimpleNamespace(
                artist_name=object(),
                additional_artists=valid_section.additional_artists,
            )
        )
        valid_dialog._refresh_artist_party_combos()
        self.assertTrue(valid_host.artist_configurations)

    def test_track_section_tab_management_and_basic_validation_paths(self):
        dialog = self._dialog()
        with mock.patch.object(
            album_module.QMessageBox,
            "warning",
            return_value=album_module.QMessageBox.Ok,
        ) as warning:
            dialog.save_album()
        self.assertEqual(warning.call_args.args[1], "Missing Album Title")
        self.assertEqual(dialog.app.submitted_tasks, [])

        dialog.add_track_section()
        self.assertEqual(len(dialog._track_sections), 3)
        self.assertIn("3 track tabs", dialog.track_count_label.text())
        dialog.remove_track_section(object())
        self.assertEqual(len(dialog._track_sections), 3)
        dialog.remove_current_track_section()
        self.assertEqual(len(dialog._track_sections), 2)
        dialog.remove_track_section(dialog._track_sections[0])
        self.assertEqual(len(dialog._track_sections), 1)
        self.assertFalse(dialog.remove_track_button.isEnabled())
        dialog.remove_track_section(dialog._track_sections[0])
        self.assertEqual(len(dialog._track_sections), 1)

        no_current_dialog = self._dialog()
        while no_current_dialog.track_tabs.count():
            no_current_dialog.track_tabs.removeTab(0)
        no_current_dialog.remove_current_track_section()

        validation_dialog = self._dialog()
        validation_dialog.album_title.setCurrentText("Validation Album")
        validation_dialog.upc.setCurrentText("bad-upc")
        with mock.patch.object(album_module.QMessageBox, "warning") as warning:
            self.assertIsNone(validation_dialog._build_track_payloads())
        self.assertEqual(warning.call_args.args[1], "Invalid UPC/EAN")

        validation_dialog.upc.setCurrentText("")
        with mock.patch.object(album_module.QMessageBox, "warning") as warning:
            self.assertIsNone(validation_dialog._build_track_payloads())
        self.assertEqual(warning.call_args.args[1], "No Tracks")

        validation_dialog._track_sections[0].track_title.setText("Title Without Artist")
        with mock.patch.object(album_module.QMessageBox, "warning") as warning:
            self.assertIsNone(validation_dialog._build_track_payloads())
        self.assertEqual(warning.call_args.args[1], "Missing Track Data")

    def test_payload_validation_media_governance_identifier_and_success_paths(self):
        audio_host = self._host()
        audio_host.confirm_audio = False
        audio_dialog = self._dialog(audio_host)
        audio_dialog.album_title.setCurrentText("Audio Album")
        self._fill_valid_section(audio_dialog._track_sections[0])
        audio_dialog._track_sections[0].audio_file.setText("/tmp/source.wav")
        self.assertIsNone(audio_dialog._build_track_payloads())
        self.assertEqual(audio_host.last_lossy_paths, ["/tmp/source.wav"])

        storage_host = self._host()
        storage_host.chosen_media_modes = None
        storage_dialog = self._dialog(storage_host)
        storage_dialog.album_title.setCurrentText("Storage Album")
        self._fill_valid_section(storage_dialog._track_sections[0])
        self.assertIsNone(storage_dialog._build_track_payloads())

        work_dialog = self._dialog()
        work_dialog.album_title.setCurrentText("Missing Work Album")
        section = work_dialog._track_sections[0]
        self._fill_valid_section(section)
        self._set_combo_data(section.governance_mode, "link_existing_work")
        with mock.patch.object(album_module.QMessageBox, "warning") as warning:
            self.assertIsNone(work_dialog._build_track_payloads())
        self.assertEqual(warning.call_args.args[1], "Missing Work")

        invalid_isrc_dialog = self._dialog()
        invalid_isrc_dialog.album_title.setCurrentText("Invalid ISRC Album")
        self._fill_valid_section(invalid_isrc_dialog._track_sections[0])
        invalid_isrc_dialog._track_sections[0].isrc.setText("BAD")
        with mock.patch.object(album_module.QMessageBox, "warning") as warning:
            self.assertIsNone(invalid_isrc_dialog._build_track_payloads())
        self.assertEqual(warning.call_args.args[1], "Invalid ISRC")

        exhausted_host = self._host(auto_isrc_ready=True)
        exhausted_host.next_generated_isrc = ""
        exhausted_dialog = self._dialog(exhausted_host)
        exhausted_dialog.album_title.setCurrentText("Exhausted ISRC Album")
        self._fill_valid_section(exhausted_dialog._track_sections[0])
        with mock.patch.object(album_module.QMessageBox, "warning") as warning:
            self.assertIsNone(exhausted_dialog._build_track_payloads())
        self.assertEqual(warning.call_args.args[1], "ISRC Exhausted")
        self.assertIsNone(exhausted_host.last_generated_isrc_kwargs["release_date"])

        duplicate_host = self._host()
        duplicate_host.taken_isrcs.add("NL-C01-23-00001")
        duplicate_dialog = self._dialog(duplicate_host)
        duplicate_dialog.album_title.setCurrentText("Duplicate ISRC Album")
        self._fill_valid_section(duplicate_dialog._track_sections[0])
        duplicate_dialog._track_sections[0].isrc.setText("NL-C01-23-00001")
        with mock.patch.object(album_module.QMessageBox, "warning") as warning:
            self.assertIsNone(duplicate_dialog._build_track_payloads())
        self.assertEqual(warning.call_args.args[1], "Duplicate ISRC")

        invalid_iswc_dialog = self._dialog()
        invalid_iswc_dialog.album_title.setCurrentText("Invalid ISWC Album")
        self._fill_valid_section(invalid_iswc_dialog._track_sections[0])
        invalid_iswc_dialog._track_sections[0].iswc.setText("bad-iswc")
        with mock.patch.object(album_module.QMessageBox, "warning") as warning:
            self.assertIsNone(invalid_iswc_dialog._build_track_payloads())
        self.assertEqual(warning.call_args.args[1], "Invalid ISWC")

        success_dialog = self._dialog()
        success_dialog.album_title.setCurrentText("Success Album")
        success_dialog.upc.setCurrentText("8720892724990")
        success_dialog.genre.setCurrentText("Ambient")
        success_dialog.catalog_number.setCurrentText("CAT-777")
        success_dialog.album_art.setText("/tmp/cover.png")
        success_section = success_dialog._track_sections[0]
        self._fill_valid_section(success_section, title="Success Track")
        success_section.additional_artists.setCurrentText("Signal Guest, Guest Two")
        success_section.release_date.setText("2026-06-07")
        success_section.len_m.setValue(3)
        success_section.len_s.setValue(5)
        success_section.isrc.setText("NL-C01-23-00002")
        success_section.iswc.setText("T-123.456.789-0")
        success_section.buma_work_number.setText("WRK-1")
        success_section.audio_file.setText("/tmp/audio.wav")

        payloads = success_dialog._build_track_payloads()

        self.assertIsNotNone(payloads)
        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        self.assertEqual(payload.track_title, "Success Track")
        self.assertEqual(payload.additional_artists, ["Signal Guest", "Guest Two"])
        self.assertEqual(payload.release_date, "2026-06-07")
        self.assertEqual(payload.track_length_sec, 185)
        self.assertEqual(payload.upc, "8720892724990")
        self.assertEqual(payload.genre, "Ambient")
        self.assertEqual(payload.catalog_number, "CAT-777")
        self.assertEqual(payload.buma_work_number, "WRK-1")
        self.assertEqual(payload.relationship_type, "original")
        self.assertEqual(payload.audio_file_storage_mode, "managed_file")
        self.assertEqual(payload.album_art_storage_mode, "database")
        self.assertEqual(success_dialog.app.duplicate_warnings[0]["album_title"], "Success Album")

    def test_save_album_reservation_failure_releases_prior_claims(self):
        host = self._host()
        host.reservation_results = [True, False]
        dialog = self._dialog(host)
        dialog.album_title.setCurrentText("Reservation Album")
        first, second = dialog._track_sections
        self._fill_valid_section(first, title="Reserved One")
        first.isrc.setText("NL-C01-23-00001")
        self._fill_valid_section(second, title="Reserved Two")
        second.isrc.setText("NL-C01-23-00002")

        dialog.save_album()

        self.assertEqual(
            [isrc for isrc, _kwargs in host.reserved_claims],
            ["NL-C01-23-00001", "NL-C01-23-00002"],
        )
        self.assertEqual(host.released_claims, ["NL-C01-23-00001"])
        self.assertEqual(host.submitted_tasks, [])


if __name__ == "__main__":
    unittest.main()
