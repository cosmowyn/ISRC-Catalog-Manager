import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from isrc_manager.history import HistoryRecoveryError
from isrc_manager.history.models import HistoryEntry
from tests.history._support import HistoryManagerTestCase


class HistoryRecoveryTests(HistoryManagerTestCase):
    test_repair_recovery_state_relinks_missing_snapshot_and_registers_orphan_backup = (
        HistoryManagerTestCase.case_repair_recovery_state_relinks_missing_snapshot_and_registers_orphan_backup
    )
    test_repair_recovery_state_rebuilds_missing_backup_history_artifacts = (
        HistoryManagerTestCase.case_repair_recovery_state_rebuilds_missing_backup_history_artifacts
    )
    test_repair_recovery_state_removes_missing_backup_with_invalid_history_artifact = (
        HistoryManagerTestCase.case_repair_recovery_state_removes_missing_backup_with_invalid_history_artifact
    )
    test_repair_recovery_state_relinks_moved_backup_sidecar = (
        HistoryManagerTestCase.case_repair_recovery_state_relinks_moved_backup_sidecar
    )
    test_repair_recovery_state_recovers_removes_and_rebuilds_snapshot_archives = (
        HistoryManagerTestCase.case_repair_recovery_state_recovers_removes_and_rebuilds_snapshot_archives
    )
    test_inspect_recovery_state_reports_dangling_snapshot_references = (
        HistoryManagerTestCase.case_inspect_recovery_state_reports_dangling_snapshot_references
    )
    test_repair_recovery_state_handles_orphan_sidecar_conflicts = (
        HistoryManagerTestCase.case_repair_recovery_state_handles_orphan_sidecar_conflicts
    )
    test_repair_recovery_state_quarantines_referenced_missing_snapshot = (
        HistoryManagerTestCase.case_repair_recovery_state_quarantines_referenced_missing_snapshot
    )
    test_backup_registration_delete_and_file_restore_errors_are_explicit = (
        HistoryManagerTestCase.case_backup_registration_delete_and_file_restore_errors_are_explicit
    )

    def _history_entry(self, **overrides):
        values = {
            "entry_id": 9001,
            "parent_id": None,
            "created_at": "2026-05-26 08:30:00",
            "label": "Synthetic History Entry",
            "action_type": "settings.synthetic",
            "entity_type": None,
            "entity_id": None,
            "reversible": True,
            "strategy": "inverse",
            "payload": {},
            "inverse_payload": None,
            "redo_payload": None,
            "snapshot_before_id": None,
            "snapshot_after_id": None,
            "status": self.history.STATUS_APPLIED,
            "visible_in_history": True,
            "is_current": False,
        }
        values.update(overrides)
        return HistoryEntry(**values)

    def test_snapshot_action_failure_keeps_original_error_when_rollback_cleanup_fails(self):
        snapshot = self.history.create_manual_snapshot("Rollback Target")

        with (
            patch.object(
                self.history,
                "record_snapshot_action",
                side_effect=RuntimeError("record failed"),
            ),
            patch.object(
                self.history,
                "restore_snapshot",
                side_effect=RuntimeError("rollback restore failed"),
            ) as restore_snapshot,
            patch.object(
                self.history,
                "delete_snapshot",
                side_effect=RuntimeError("cleanup failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "record failed"):
                self.history.restore_snapshot_as_action(snapshot.snapshot_id)

        restore_snapshot.assert_called_once()

    def test_entry_payload_replay_boundaries_cover_noops_files_and_errors(self):
        snapshot_entry_without_id = self._history_entry(
            strategy="snapshot",
            snapshot_before_id=None,
            snapshot_after_id=None,
        )
        self.history._apply_entry_payload(snapshot_entry_without_id, {}, direction="undo")

        missing_snapshot_entry = self._history_entry(
            strategy="snapshot",
            snapshot_before_id=999999,
        )
        with self.assertRaisesRegex(HistoryRecoveryError, "Snapshot 999999"):
            self.history._apply_entry_payload(missing_snapshot_entry, {}, direction="undo")

        self.history._apply_entry_payload(
            self._history_entry(action_type="track.create"),
            None,
            direction="undo",
        )
        with self.assertRaisesRegex(ValueError, "Undo/redo not implemented"):
            self.history._apply_entry_payload(
                self._history_entry(action_type="unknown.action"),
                {"value": "ignored"},
                direction="undo",
            )

        target = self.root / "history-payload.txt"
        target.write_text("before", encoding="utf-8")
        before_state = self.history.capture_file_state(target)
        target.write_text("after", encoding="utf-8")

        self.history._apply_entry_payload(
            self._history_entry(action_type="file.write"),
            {"target_path": str(target), "state": before_state},
            direction="undo",
        )

        self.assertEqual(target.read_text(encoding="utf-8"), "before")

        target.write_text("side-effect-before", encoding="utf-8")
        side_effect_state = self.history.capture_file_state(target)
        target.write_text("side-effect-after", encoding="utf-8")

        self.history._apply_snapshot_side_effects(None, direction="undo")
        self.history._apply_snapshot_side_effects(
            {"file_effects": [{"target_path": str(target), "before_state": None}]},
            direction="undo",
        )
        self.assertEqual(target.read_text(encoding="utf-8"), "side-effect-after")

        self.history._apply_snapshot_side_effects(
            {"file_effects": [{"target_path": str(target), "before_state": side_effect_state}]},
            direction="undo",
        )
        self.assertEqual(target.read_text(encoding="utf-8"), "side-effect-before")

        action_entry = self._history_entry(action_type="snapshot.create")
        missing_payload_cases = (
            (
                self.history._apply_snapshot_create_undo,
                {},
                "Missing snapshot_id for snapshot.create undo",
            ),
            (
                self.history._apply_snapshot_create_redo,
                {},
                "Missing archived snapshot for snapshot.create redo",
            ),
            (
                self.history._apply_snapshot_delete_undo,
                {},
                "Missing archived snapshot for snapshot.delete undo",
            ),
            (
                self.history._apply_snapshot_delete_redo,
                {},
                "Missing snapshot_id for snapshot.delete redo",
            ),
        )
        for apply_payload, payload, message in missing_payload_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    apply_payload(action_entry, payload)

    def test_snapshot_replay_failure_attempts_file_and_snapshot_rollbacks_when_they_fail(self):
        before = self.history.capture_snapshot(kind="before_failed_replay", label="Before Replay")
        after = self.history.capture_snapshot(kind="after_failed_replay", label="After Replay")
        target = self.root / "snapshot-side-effect.txt"
        target.write_text("side effect", encoding="utf-8")
        entry = self.history.record_snapshot_action(
            label="Replay Failure",
            action_type="snapshot.failure",
            snapshot_before_id=before.snapshot_id,
            snapshot_after_id=after.snapshot_id,
            payload={
                "file_effects": [
                    {
                        "target_path": str(target),
                        "before_state": {"companion_suffixes": []},
                        "after_state": {"companion_suffixes": []},
                    }
                ]
            },
        )

        with (
            patch.object(
                self.history,
                "_restore_snapshot_state",
                side_effect=[
                    RuntimeError("restore failed"),
                    RuntimeError("rollback restore failed"),
                ],
            ) as restore_snapshot,
            patch.object(
                self.history,
                "restore_file_state",
                side_effect=RuntimeError("file rollback failed"),
            ) as restore_file_state,
        ):
            with self.assertRaisesRegex(RuntimeError, "restore failed"):
                self.history._replay_entry(
                    entry,
                    entry.inverse_payload,
                    direction="undo",
                    next_current_entry_id=entry.parent_id,
                    next_entry_status=self.history.STATUS_UNDONE,
                )

        self.assertEqual(restore_snapshot.call_count, 2)
        self.assertEqual(restore_file_state.call_count, 1)

    def test_repair_history_invariants_handles_stale_head_events_and_dangling_snapshots(
        self,
    ):
        with self.conn:
            self.conn.execute(
                "INSERT INTO HistoryHead (id, current_entry_id) VALUES (1, 987654)"
                "ON CONFLICT(id) DO UPDATE SET current_entry_id=excluded.current_entry_id"
            )

        stale_head_result = self.history.repair_recovery_state()

        self.assertIsNone(self.history.get_current_entry_id())
        self.assertTrue(
            any("Cleared stale HistoryHead" in change for change in stale_head_result.changes)
        )

        parent = self.history.record_setting_change(
            key="isrc_prefix",
            label="Set ISRC Prefix",
            before_value="",
            after_value="NLABC",
        )
        event_id = self.history.record_event(label="Audit Note", action_type="audit.note")
        child = self.history.record_setting_change(
            key="artist_code",
            label="Set Artist Code",
            before_value="",
            after_value="ART",
        )
        with self.conn:
            self.conn.execute(
                "UPDATE HistoryEntries SET parent_id=?, reversible=1, status=? WHERE id=?",
                (parent.entry_id, self.history.STATUS_UNDONE, event_id),
            )
            self.conn.execute(
                "UPDATE HistoryEntries SET parent_id=? WHERE id=?",
                (event_id, child.entry_id),
            )
            self.conn.execute(
                "UPDATE HistoryHead SET current_entry_id=? WHERE id=1",
                (event_id,),
            )

        with patch.object(
            self.history,
            "_entry_affects_state",
            side_effect=lambda *, action_type, strategy, reversible: bool(reversible)
            and action_type != "audit.note",
        ):
            relink_result = self.history.repair_recovery_state()
        repaired_event = self.history.fetch_entry(event_id)
        repaired_child = self.history.fetch_entry(child.entry_id)

        self.assertIsNotNone(repaired_event)
        self.assertFalse(repaired_event.reversible)
        self.assertEqual(repaired_event.status, self.history.STATUS_APPLIED)
        self.assertIsNotNone(repaired_child)
        self.assertEqual(repaired_child.parent_id, parent.entry_id)
        self.assertTrue(
            any("Converted non-state history entry" in change for change in relink_result.changes)
        )
        self.assertTrue(
            any("Re-linked history entry" in change for change in relink_result.changes)
        )

        before = self.history.capture_snapshot(kind="before_dangling", label="Before Dangling")
        after = self.history.capture_snapshot(kind="after_dangling", label="After Dangling")
        dangling = self.history.record_snapshot_action(
            label="Dangling Snapshot Action",
            action_type="snapshot.dangling",
            snapshot_before_id=before.snapshot_id,
            snapshot_after_id=after.snapshot_id,
        )
        for snapshot in (before, after):
            Path(snapshot.db_snapshot_path).unlink()
            self.history._snapshot_sidecar_path(Path(snapshot.db_snapshot_path)).unlink(
                missing_ok=True
            )
        with self.conn:
            self.conn.execute(
                "DELETE FROM HistorySnapshots WHERE id IN (?, ?)",
                (before.snapshot_id, after.snapshot_id),
            )

        dangling_result = self.history.repair_recovery_state()
        repaired_dangling = self.history.fetch_entry(dangling.entry_id)

        self.assertIsNotNone(repaired_dangling)
        self.assertFalse(repaired_dangling.reversible)
        self.assertEqual(repaired_dangling.status, self.history.STATUS_ARTIFACT_MISSING)
        self.assertIsNone(repaired_dangling.snapshot_before_id)
        self.assertIsNone(repaired_dangling.snapshot_after_id)
        self.assertTrue(any("Disabled undo/redo" in change for change in dangling_result.changes))

    def test_recovery_metadata_fallbacks_handle_corrupted_sidecars_and_inferred_assets(
        self,
    ):
        self.history_root.mkdir(parents=True, exist_ok=True)
        corrupt_sidecar = self.history_root / "corrupt.json"
        corrupt_sidecar.write_text("{", encoding="utf-8")
        list_sidecar = self.history_root / "list.json"
        list_sidecar.write_text("[]", encoding="utf-8")

        self.assertEqual(self.history._read_json_sidecar(corrupt_sidecar), {})
        self.assertEqual(self.history._read_json_sidecar(list_sidecar), {})

        snapshot_path = self.history_root / "snapshots" / self.db_path.stem / "20260526_manual.db"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(b"snapshot")
        license_assets = snapshot_path.with_suffix(".assets") / "licenses"
        license_assets.mkdir(parents=True)

        snapshot_metadata = self.history._load_snapshot_metadata(snapshot_path)

        self.assertEqual(snapshot_metadata["kind"], "manual")
        self.assertEqual(snapshot_metadata["label"], snapshot_path.stem)
        self.assertTrue(snapshot_metadata["manifest"]["managed_directories"]["licenses"]["exists"])
        self.assertEqual(
            snapshot_metadata["manifest"]["managed_directories"]["licenses"]["snapshot_path"],
            str(license_assets),
        )

        backup_path = self.backups_root / "library_pre_restore.db"
        backup_path.write_bytes(b"backup")
        backup_metadata = self.history._load_backup_metadata(backup_path)

        self.assertEqual(backup_metadata["kind"], "pre_restore")
        self.assertEqual(backup_metadata["label"], backup_path.name)
        self.assertEqual(
            self.history._infer_snapshot_kind(self.root / "loose.db"), "recovered_orphan"
        )
        self.assertEqual(self.history._infer_backup_kind(self.root / "manual.db"), "manual")
        self.assertIsNone(self.history._int_or_none("not-an-int"))
        self.assertEqual(self.history._loads(None), {})
        self.assertEqual(self.history._loads("[1, 2, 3]"), {})

    def test_artifact_quarantine_scrubs_nested_payloads_and_rehomes_current_head(self):
        self.assertEqual(self.history._quarantine_artifact_references(), [])

        snapshot = self.history.capture_snapshot(kind="quarantine", label="Quarantine")
        artifact_root = self.history_root / "file_states" / self.db_path.stem
        artifact_root.mkdir(parents=True, exist_ok=True)
        leaked_artifact = artifact_root / "stored.bin"
        leaked_artifact.write_bytes(b"artifact")
        action = self.history.record_snapshot_action(
            label="Snapshot Action With Artifact Payloads",
            action_type="snapshot.artifact_payload",
            snapshot_before_id=snapshot.snapshot_id,
            snapshot_after_id=snapshot.snapshot_id,
            payload={
                "snapshot_id": snapshot.snapshot_id,
                "path": str(leaked_artifact),
                "items": [{"snapshot_id": snapshot.snapshot_id}],
            },
        )
        self.history._update_entry_payloads(
            action.entry_id,
            inverse_payload={"snapshot_id": snapshot.snapshot_id, "path": str(leaked_artifact)},
            redo_payload={
                "items": [{"snapshot_id": snapshot.snapshot_id, "path": str(leaked_artifact)}]
            },
        )

        affected = self.history._quarantine_artifact_references(
            snapshot_ids={snapshot.snapshot_id},
            artifact_roots=(artifact_root,),
        )
        repaired = self.history.fetch_entry(action.entry_id)

        self.assertEqual(affected, [action.entry_id])
        self.assertIsNotNone(repaired)
        self.assertFalse(repaired.reversible)
        self.assertEqual(repaired.status, self.history.STATUS_ARTIFACT_MISSING)
        self.assertIsNone(repaired.snapshot_before_id)
        self.assertIsNone(repaired.snapshot_after_id)
        self.assertIsNone(repaired.payload["snapshot_id"])
        self.assertIsNone(repaired.payload["path"])
        self.assertIsNone(repaired.payload["items"][0]["snapshot_id"])
        self.assertIsNone(repaired.inverse_payload["path"])
        self.assertIsNone(repaired.redo_payload["items"][0]["path"])
        self.assertIsNone(self.history.get_current_entry_id())

    def test_managed_state_boundaries_clone_restore_and_report_external_rollback_errors(self):
        original_managed_root = self.history.managed_root
        try:
            self.history.managed_root = None
            self.assertEqual(self.history._capture_managed_state(self.root / "unused"), {})
            self.history._restore_managed_state(
                {
                    "managed_directories": {
                        "licenses": {"exists": True, "snapshot_path": str(self.root / "missing")}
                    }
                }
            )

            self.history.managed_root = original_managed_root
            self.history._restore_managed_state({})

            source_dir = self.data_root / "licenses"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "license.pdf").write_bytes(b"license")
            assets_dir = self.root / "managed-snapshot"
            stale_dest = assets_dir / "licenses"
            stale_dest.mkdir(parents=True, exist_ok=True)
            (stale_dest / "stale.txt").write_text("stale", encoding="utf-8")

            manifest = self.history._capture_managed_state(assets_dir)

            self.assertTrue(manifest["managed_directories"]["licenses"]["exists"])
            self.assertFalse((stale_dest / "stale.txt").exists())
            self.assertTrue((stale_dest / "license.pdf").exists())

            missing_manifest = {
                "managed_directories": {
                    "licenses": {
                        "exists": True,
                        "snapshot_path": str(self.root / "missing-assets"),
                    }
                }
            }
            with self.assertRaises(FileNotFoundError):
                self.history._clone_managed_manifest(missing_manifest, self.root / "clone")
            with self.assertRaises(FileNotFoundError):
                self.history._restore_managed_state(missing_manifest)

            with (
                patch.object(
                    self.history,
                    "_restore_managed_state",
                    side_effect=RuntimeError("managed failed"),
                ),
                patch.object(
                    self.history,
                    "_apply_settings_state",
                    side_effect=RuntimeError("settings failed"),
                ),
            ):
                rollback_error = self.history._restore_external_state(
                    rollback_manifest={}, settings_state={}
                )

            self.assertIn("managed files: managed failed", rollback_error)
            self.assertIn("settings: settings failed", rollback_error)
        finally:
            self.history.managed_root = original_managed_root

    def test_setting_payload_boundaries_restore_profile_identity_and_reject_bad_keys(self):
        self.history._apply_setting_payload(
            {
                "key": "identity",
                "value": {"window_title": "Legacy Window", "icon_path": "icon.ico"},
            }
        )
        self.assertEqual(self.settings.value("identity/window_title_override"), "Legacy Window")
        self.assertEqual(self.settings.value("identity/icon_path"), "icon.ico")

        self.history._apply_setting_payload({"key": "artist_code", "value": "ART"})
        artist_code = self.conn.execute(
            "SELECT value FROM app_kv WHERE key='isrc_artist_code'"
        ).fetchone()
        self.assertEqual(artist_code[0], "ART")

        with self.assertRaisesRegex(ValueError, "Theme settings payload must be a dict"):
            self.history._apply_setting_payload({"key": "theme_settings", "value": "invalid"})

        self.history._apply_setting_payload(
            {"key": "theme_library", "value": {"studio": {"accent": "#112233"}}}
        )
        self.assertEqual(
            json.loads(self.settings.value("theme/library_json")),
            {"studio": {"accent": "#112233"}},
        )

        self.history._apply_setting_payload({"key": "sena_number", "value": "SENA-1"})
        self.history._apply_setting_payload({"key": "btw_number", "value": "NL001"})
        self.history._apply_setting_payload({"key": "buma_relatie_nummer", "value": "BUMA-1"})
        self.history._apply_setting_payload({"key": "buma_ipi", "value": "IPI-1"})
        self.history._apply_setting_payload({"key": "owner_party_id", "value": ""})

        self.assertEqual(
            self.conn.execute("SELECT number FROM SENA WHERE id=1").fetchone()[0],
            "SENA-1",
        )
        self.assertEqual(
            self.conn.execute("SELECT nr FROM BTW WHERE id=1").fetchone()[0],
            "NL001",
        )
        self.assertEqual(
            self.conn.execute("SELECT relatie_nummer, ipi FROM BUMA_STEMRA WHERE id=1").fetchone(),
            ("BUMA-1", "IPI-1"),
        )
        self.assertIsNone(
            self.conn.execute("SELECT party_id FROM ApplicationOwnerBinding").fetchone()
        )

        with self.assertRaisesRegex(ValueError, "Unknown setting history key"):
            self.history._apply_setting_payload({"key": "unknown", "value": "ignored"})

    def test_recovery_artifact_metadata_helpers_handle_missing_invalid_and_archive_edges(self):
        invalid_missing = self.history._file_state_missing_paths("not-a-state")
        self.assertEqual(invalid_missing, [Path("<invalid file state>")])
        self.assertFalse(self.history._state_has_all_artifacts("not-a-state"))
        self.assertFalse(self.history._state_has_all_artifacts({"files": []}))

        missing_artifact = self.root / "missing-artifact.bin"
        missing_paths = self.history._file_state_missing_paths(
            {"files": [{}, {"artifact_path": str(missing_artifact)}]}
        )
        self.assertIn(Path("<missing artifact path>"), missing_paths)
        self.assertIn(missing_artifact, missing_paths)

        archived_snapshot = {
            "db_snapshot_path": str(self.root / "missing-snapshot.db"),
            "manifest": {
                "managed_directories": {
                    "licenses": {
                        "exists": True,
                        "snapshot_path": str(self.root / "missing-assets"),
                    },
                    "media": {"exists": False, "snapshot_path": None},
                }
            },
        }
        archived_missing = self.history._archived_snapshot_missing_paths(archived_snapshot)
        self.assertIn(self.root / "missing-snapshot.db", archived_missing)
        self.assertIn(self.root / "missing-assets", archived_missing)

        snapshot = self.history.capture_snapshot(kind="archive_probe", label="Archive Probe")
        self.assertFalse(self.history._restore_snapshot_from_archive_if_possible(snapshot))
        self.history._insert_entry(
            label="Broken Archived Snapshot",
            action_type="snapshot.delete",
            entity_type="Snapshot",
            entity_id=str(snapshot.snapshot_id),
            reversible=True,
            strategy="inverse",
            payload={
                "snapshot_id": snapshot.snapshot_id,
                "archived_snapshot": archived_snapshot,
            },
            inverse_payload=None,
            redo_payload=None,
            snapshot_before_id=None,
            snapshot_after_id=None,
            move_head=False,
        )
        self.assertFalse(self.history._restore_snapshot_from_archive_if_possible(snapshot))

        class BrokenPath:
            def __fspath__(self):
                raise RuntimeError("broken path")

        self.assertEqual(
            self.history._normalize_artifact_roots((self.root, BrokenPath())), (self.root,)
        )
        self.assertFalse(self.history._path_value_matches_roots("", (self.root,)))
        self.assertFalse(self.history._path_value_matches_roots("relative/file", (self.root,)))
        artifact_root = self.root / "artifact-root"
        nested_artifact = artifact_root / "nested" / "artifact.json"
        self.assertTrue(
            self.history._path_value_matches_roots(str(nested_artifact), (artifact_root,))
        )
        self.assertEqual(
            self.history._collect_int_values(
                {"items": [{"snapshot_id": "7"}, {"snapshot_id": "bad"}]},
                "snapshot_id",
            ),
            {7},
        )

        assets_root = Path(snapshot.db_snapshot_path).with_suffix(".assets")
        managed_dir_name = next(iter(self.history.MANAGED_DIRECTORIES))
        (assets_root / managed_dir_name).mkdir(parents=True)
        inferred_manifest = self.history._infer_snapshot_manifest(Path(snapshot.db_snapshot_path))
        self.assertTrue(inferred_manifest["managed_directories"][managed_dir_name]["exists"])
        self.assertIsNone(
            self.history._restore_external_state(
                rollback_manifest={},
                settings_state={},
            )
        )

    def test_snapshot_backup_sidecar_and_reload_boundaries_are_explicit(self):
        snapshot_path = self.root / "explicit-snapshot.db"
        snapshot_path.write_bytes(b"snapshot")
        snapshot = self.history._insert_snapshot_row(
            snapshot_id=910,
            kind="manual",
            label="Explicit Snapshot",
            db_snapshot_path=str(snapshot_path),
            settings_state={},
            manifest={},
        )
        self.assertEqual(snapshot.snapshot_id, 910)
        self.assertTrue(self.history._snapshot_sidecar_path(snapshot_path).exists())

        with patch.object(self.history, "fetch_snapshot", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Snapshot 911 could not be reloaded"):
                self.history._insert_snapshot_row(
                    snapshot_id=911,
                    kind="manual",
                    label="Missing Reload Snapshot",
                    db_snapshot_path=str(self.root / "missing-reload-snapshot.db"),
                    settings_state={},
                    manifest={},
                )

        backup_path = self.backups_root / "explicit-backup.db"
        backup_path.write_bytes(b"backup")
        backup = self.history._insert_backup_row(
            backup_id=710,
            kind="manual",
            label="Explicit Backup",
            backup_path=str(backup_path),
            source_db_path=str(self.db_path),
            metadata={"source": "test"},
        )
        self.assertEqual(backup.backup_id, 710)
        self.assertTrue(self.history._backup_sidecar_path(backup_path).exists())

        with patch.object(self.history, "fetch_backup", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Backup record 711 could not be reloaded"):
                self.history._insert_backup_row(
                    backup_id=711,
                    kind="manual",
                    label="Missing Reload Backup",
                    backup_path=str(self.backups_root / "missing-reload-backup.db"),
                    source_db_path=str(self.db_path),
                    metadata={},
                )

        with patch.object(
            self.history,
            "_write_json_sidecar",
            side_effect=RuntimeError("sidecar failed"),
        ):
            self.history._write_snapshot_sidecar(snapshot)
            self.history._write_backup_sidecar(backup)

    def test_history_invariant_bootstrap_and_helper_boundaries_are_stable(self):
        bare_conn = sqlite3.connect(":memory:")
        try:
            bare_history = self.history.__class__(
                bare_conn,
                self.settings,
                self.root / "bare.db",
                self.root / "bare-history",
            )
            bare_history._ensure_history_invariants(changes=[])
        finally:
            bare_conn.close()

        self.history._set_current_entry_id(123456)
        with self.conn:
            self.conn.execute("DELETE FROM HistoryEntries")
        changes: list[str] = []
        self.history._ensure_history_invariants(changes=changes)
        self.assertIsNone(self.history.get_current_entry_id())
        self.assertTrue(any("no history entries remain" in change for change in changes))

        first = self.history.record_setting_change(
            key="isrc_prefix",
            label="Set ISRC Prefix",
            before_value="",
            after_value="NLAAA",
        )
        second = self.history.record_setting_change(
            key="artist_code",
            label="Set Artist Code",
            before_value="",
            after_value="ART",
        )
        self.assertTrue(self.history._history_statuses_need_bootstrap())
        self.history._bootstrap_history_statuses()
        self.assertEqual(
            self.history.fetch_entry(first.entry_id).status, self.history.STATUS_APPLIED
        )
        self.assertEqual(
            self.history.fetch_entry(second.entry_id).status, self.history.STATUS_APPLIED
        )

        current_stamp = self.history._history_timestamp_now()
        self.assertFalse(self.history._can_coalesce_setting_bundle(None, "display/key", True))
        self.assertFalse(
            self.history._can_coalesce_setting_bundle(
                self._history_entry(
                    action_type="settings.bundle",
                    entity_id="display/key",
                    reversible=False,
                    created_at=current_stamp,
                ),
                "display/key",
                True,
            )
        )
        self.assertFalse(
            self.history._can_coalesce_setting_bundle(
                self._history_entry(
                    action_type="settings.bundle",
                    entity_id="display/other",
                    created_at=current_stamp,
                ),
                "display/key",
                True,
            )
        )
        self.assertFalse(
            self.history._can_coalesce_setting_bundle(
                self._history_entry(
                    action_type="settings.bundle",
                    entity_id="display/key",
                    created_at=current_stamp,
                    visible_in_history=False,
                ),
                "display/key",
                True,
            )
        )
        self.assertFalse(
            self.history._can_coalesce_setting_bundle(
                self._history_entry(
                    action_type="settings.bundle",
                    entity_id="display/key",
                    created_at="",
                ),
                "display/key",
                True,
            )
        )
        self.assertFalse(
            self.history._can_coalesce_setting_bundle(
                self._history_entry(
                    action_type="settings.bundle",
                    entity_id="display/key",
                    created_at="not-a-date",
                ),
                "display/key",
                True,
            )
        )

        class WeirdValue:
            def __str__(self):
                return "weird-value"

        self.assertEqual(
            self.history._normalize_json_value({"values": [WeirdValue()]}),
            {"values": ["weird-value"]},
        )
        with self.assertRaisesRegex(ValueError, "History entry 123456789 not found"):
            self.history._update_entry_payloads(123456789, payload={})
        missing_path = self.root / "already-missing"
        self.history._remove_path(missing_path)
        self.assertEqual(self.history._loads(None), {})
        self.assertEqual(self.history._loads("[1, 2, 3]"), {})
        self.assertRegex(self.history._now_stamp(), r"\d{4}-\d{2}-\d{2}")


del HistoryManagerTestCase
