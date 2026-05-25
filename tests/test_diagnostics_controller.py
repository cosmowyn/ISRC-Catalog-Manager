import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isrc_manager.diagnostics.controller import (
    _apply_diagnostics_repair_result,
    _load_application_storage_audit_async,
    _load_diagnostics_report_async,
    _preview_diagnostics_repair,
    _run_application_storage_cleanup_async,
    _run_bundle_diagnostics_repair,
    _run_diagnostics_repair,
    _run_diagnostics_repair_async,
)
from isrc_manager.storage_migration import (
    PREFERRED_STATE_CONFLICT,
    PREFERRED_STATE_RESUMABLE_STAGE,
    PREFERRED_STATE_VALID_COMPLETE,
    StorageMigrationResult,
)


class _TaskContext:
    def __init__(self):
        self.statuses = []
        self.progress = []

    def set_status(self, message):
        self.statuses.append(str(message))

    def report_progress(self, value, maximum, message):
        self.progress.append((int(value), int(maximum), str(message)))


class _Inspection(SimpleNamespace):
    pass


class _Candidate(SimpleNamespace):
    pass


class _Bundle(SimpleNamespace):
    pass


class _RepairResult(SimpleNamespace):
    pass


class DiagnosticsControllerTests(unittest.TestCase):
    def test_preview_storage_layout_migrate_no_legacy_root(self):
        app = SimpleNamespace(
            storage_migration_service=SimpleNamespace(
                inspect=mock.Mock(
                    return_value=_Inspection(
                        legacy_root=None,
                        preferred_state="legacy_only",
                        conflict_items=(),
                        legacy_items=("db", "cache"),
                    )
                )
            ),
            storage_layout=SimpleNamespace(preferred_data_root=Path("/preferred")),
        )

        self.assertEqual(
            _preview_diagnostics_repair(app, "storage_layout_migrate"),
            "No legacy app-owned storage was detected, so no migration is needed.",
        )

    def test_preview_storage_layout_migrate_valid_complete_and_conflict(self):
        app = SimpleNamespace(
            storage_migration_service=SimpleNamespace(
                inspect=mock.Mock(
                    return_value=_Inspection(
                        legacy_root=None,
                        preferred_state=PREFERRED_STATE_VALID_COMPLETE,
                        conflict_items=(),
                        legacy_items=("db",),
                    )
                )
            ),
            storage_layout=SimpleNamespace(preferred_data_root=Path("/preferred")),
        )
        self.assertIn(
            "verified app-owned data", _preview_diagnostics_repair(app, "storage_layout_migrate")
        )

        app.storage_migration_service.inspect.return_value = _Inspection(
            legacy_root=Path("/legacy"),
            preferred_state=PREFERRED_STATE_RESUMABLE_STAGE,
            conflict_items=(),
            legacy_items=("db",),
        )
        self.assertIn(
            "resume the preserved staged app-data migration",
            _preview_diagnostics_repair(app, "storage_layout_migrate"),
        )

        app.storage_migration_service.inspect.return_value = _Inspection(
            legacy_root=Path("/legacy"),
            preferred_state=PREFERRED_STATE_CONFLICT,
            conflict_items=("conflict-a", "conflict-b"),
            legacy_items=("db",),
        )
        self.assertIn(
            "conflicting managed content",
            _preview_diagnostics_repair(app, "storage_layout_migrate"),
        )

    def test_preview_schema_and_cleanup_text_branches(self):
        app = SimpleNamespace(
            storage_migration_service=SimpleNamespace(
                inspect=mock.Mock(
                    return_value=_Inspection(
                        legacy_root=Path("/legacy"),
                        preferred_state="other",
                        conflict_items=(),
                        legacy_items=("db", "media"),
                    )
                )
            ),
            storage_layout=SimpleNamespace(preferred_data_root=Path("/preferred")),
            _count_orphaned_custom_values=mock.Mock(return_value=7),
            _legacy_promoted_field_repair_candidates=mock.Mock(
                return_value=[
                    _Candidate(
                        field_name="artist",
                        eligible=True,
                        non_empty_value_count=2,
                        blank_target_count=1,
                        conflicting_track_ids=[1, 2],
                    ),
                    _Candidate(
                        field_name="title",
                        eligible=False,
                        non_empty_value_count=0,
                        blank_target_count=3,
                        conflicting_track_ids=[4],
                    ),
                ]
            ),
        )

        self.assertEqual(
            _preview_diagnostics_repair(app, "schema_migrate"),
            "This will re-run the schema bootstrap and migrations for the current profile.",
        )
        self.assertIn(
            "orphaned custom value", _preview_diagnostics_repair(app, "custom_value_cleanup")
        )
        self.assertEqual(app._count_orphaned_custom_values.call_count, 1)

        self.assertIn(
            "This will delete",
            _preview_diagnostics_repair(app, "waveform_cache_cleanup", {"issue_count": 3}),
        )
        self.assertIn(
            "Safe candidates: 1", _preview_diagnostics_repair(app, "legacy_promoted_field_repair")
        )
        self.assertIn(
            "Blocked by", _preview_diagnostics_repair(app, "legacy_promoted_field_repair")
        )
        self.assertIn(
            "history and recovery issue",
            _preview_diagnostics_repair(app, "history_reconcile", {"issue_count": 4}),
        )

    def test_preview_unknown_repair_raises(self):
        app = SimpleNamespace()
        with self.assertRaises(ValueError):
            _preview_diagnostics_repair(app, "unknown")

    def test_run_storage_layout_repair_uses_result_fields(self):
        app = SimpleNamespace()
        app._run_storage_layout_migration = mock.Mock(
            return_value=StorageMigrationResult(
                action="copied",
                source_root=Path("/legacy"),
                target_root=Path("/preferred"),
                copied_items=("db", "media"),
                rewritten_files=(),
                verified_databases=(),
                journal_path=Path("/journal"),
            )
        )
        result = _run_diagnostics_repair(app, "storage_layout_migrate")
        self.assertIn("App-owned data was copied", result)
        self.assertIn("/legacy", result)
        self.assertIn("db, media", result)

    def test_run_schema_repair_refreshes_services(self):
        app = SimpleNamespace(
            init_db=mock.Mock(),
            migrate_schema=mock.Mock(),
            load_active_custom_fields=mock.Mock(return_value=("fields",)),
            refresh_table_preserve_view=mock.Mock(),
            populate_all_comboboxes=mock.Mock(),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            _log_event=mock.Mock(),
            current_db_path="/tmp/catalog.db",
        )

        result = _run_diagnostics_repair(app, "schema_migrate")

        app.init_db.assert_called_once()
        app.migrate_schema.assert_called_once()
        app._audit.assert_called_once_with(
            "REPAIR",
            "Schema",
            ref_id="/tmp/catalog.db",
            details="schema_migrate",
        )
        self.assertEqual(
            result,
            "Schema bootstrap and migration completed successfully.",
        )

    def test_run_orphan_cleanup_and_waveform_cache(self):
        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.__exit__.return_value = None
        app = SimpleNamespace(
            conn=conn,
            track_service=mock.Mock(),
            _custom_value_field_column_name=mock.Mock(return_value="CustomFieldDefID"),
            _count_orphaned_custom_values=mock.Mock(side_effect=[9, 4]),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            _log_event=mock.Mock(),
        )

        self.assertEqual(
            _run_diagnostics_repair(app, "custom_value_cleanup"),
            "Removed 5 orphaned custom value row(s).",
        )
        conn.execute.assert_called_once()
        self.assertEqual(
            app._log_event.call_args,
            mock.call(
                "diagnostics.repair.custom_value_cleanup",
                "Diagnostics repair applied",
                repair_key="custom_value_cleanup",
                removed=5,
                remaining=4,
            ),
        )

        with mock.patch("isrc_manager.diagnostics.controller.AudioWaveformCacheService") as service:
            service.return_value.cleanup_invalid_caches.return_value = 7
            app._audit.reset_mock()
            app._audit_commit.reset_mock()
            app._log_event.reset_mock()
            result = _run_diagnostics_repair(app, "waveform_cache_cleanup")

        self.assertEqual(result, "Removed 7 stale or orphaned cached waveform row(s).")
        self.assertEqual(app._audit.call_args.kwargs.get("details"), "removed=7")

    def test_run_bundle_repair_history_conflicts(self):
        bundle = _Bundle(
            conn=mock.MagicMock(),
            track_service=mock.Mock(),
            history_manager=SimpleNamespace(
                repair_recovery_state=mock.Mock(
                    return_value=_RepairResult(
                        changes=("updated one", "removed two"),
                        unresolved=("missing three",),
                    )
                )
            ),
            database_maintenance=mock.Mock(),
            license_service=mock.Mock(),
        )
        app = SimpleNamespace(
            _custom_value_field_column_name=mock.Mock(return_value="colX"),
            _count_orphaned_custom_values=mock.Mock(return_value=2),
            load_active_custom_fields=mock.Mock(return_value=("fields",)),
            refresh_table_preserve_view=mock.Mock(),
            populate_all_comboboxes=mock.Mock(),
            settings=mock.Mock(),
            data_root="/tmp/data",
            storage_layout=SimpleNamespace(preferred_data_root=Path("/preferred")),
        )

        history_result = _run_bundle_diagnostics_repair(
            app,
            "history_reconcile",
            bundle=bundle,
            current_db_path="/tmp/catalog.db",
            data_root=Path("/tmp/data"),
        )

        self.assertIn("updated one", history_result["result_text"])
        self.assertIn("Unresolved:", history_result["result_text"])
        self.assertEqual(history_result["audit_entity"], "History")

    def test_apply_diagnostics_repair_result_refreshes_schema_history_and_logs(self):
        app = SimpleNamespace(
            conn=mock.MagicMock(),
            load_active_custom_fields=mock.Mock(return_value=("fields",)),
            refresh_table_preserve_view=mock.Mock(),
            populate_all_comboboxes=mock.Mock(),
            _refresh_history_actions=mock.Mock(),
            history_dialog=SimpleNamespace(
                isVisible=mock.Mock(return_value=True),
                refresh_data=mock.Mock(),
            ),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            _log_event=mock.Mock(),
        )

        result = _apply_diagnostics_repair_result(
            app,
            "history_reconcile",
            {
                "post_action": "refresh_history",
                "audit_entity": "History",
                "audit_ref_id": "/tmp/catalog.db",
                "audit_details": "history_reconcile",
                "log_event": "diagnostics.repair.history_reconcile",
                "log_message": "History diagnostics repair applied",
                "log_fields": {"changes": 1, "unresolved": 0},
                "result_text": "Repaired",
            },
        )

        self.assertEqual(result, "Repaired")
        app._refresh_history_actions.assert_called_once()
        app.history_dialog.refresh_data.assert_called_once()
        app._audit.assert_called_once()
        app._log_event.assert_called_once()

    def test_load_and_run_storage_async_wrappers_submit_expected_task_calls(self):
        app = SimpleNamespace(
            current_db_path="",
            storage_layout=SimpleNamespace(preferred_data_root=Path("/preferred")),
            settings=mock.Mock(),
            data_root="/tmp/data",
            logs_dir="/tmp/logs",
            _app_version_text=mock.Mock(return_value="1.0"),
            _build_application_storage_audit_payload=mock.Mock(return_value={"items": 1}),
            _build_diagnostics_report=mock.Mock(return_value={"_diagnostics_progress_total": 9}),
            _application_storage_admin_service=mock.Mock(
                return_value=SimpleNamespace(
                    cleanup_selected=mock.Mock(
                        return_value=SimpleNamespace(
                            removed_item_keys=("a",),
                            skipped_item_keys=("b",),
                            removed_bytes=10,
                            removed_history_entry_ids=(1, 2),
                            removed_session_entry_ids=(3,),
                        )
                    )
                )
            ),
            _submit_background_task=mock.Mock(return_value="task-ok"),
            _submit_background_bundle_task=mock.Mock(return_value="bundle-ok"),
            _apply_diagnostics_repair_result=mock.Mock(return_value="done"),
        )

        result_audit = _load_application_storage_audit_async(
            app,
            owner=None,
            on_success=mock.Mock(),
            on_error=mock.Mock(),
            on_finished=mock.Mock(),
            on_status=mock.Mock(),
        )

        self.assertEqual(result_audit, "task-ok")
        self.assertEqual(app._submit_background_task.call_count, 1)

        result_cleanup = _run_application_storage_cleanup_async(
            app,
            item_keys=["a", "b"],
            allow_warning_deletes=True,
            on_success=mock.Mock(),
            on_error=mock.Mock(),
            on_finished=mock.Mock(),
            on_status=mock.Mock(),
            owner=None,
        )
        self.assertEqual(result_cleanup, "task-ok")
        self.assertEqual(app._submit_background_task.call_count, 2)

        result_report = _load_diagnostics_report_async(
            app,
            owner=None,
            on_success=mock.Mock(),
            on_error=mock.Mock(),
            on_cancelled=mock.Mock(),
            on_finished=mock.Mock(),
            on_progress=mock.Mock(),
            on_status=mock.Mock(),
        )
        self.assertEqual(result_report, "task-ok")
        app.current_db_path = "/tmp/catalog.db"
        app.conn = mock.Mock()
        app.track_service = mock.Mock()
        app.license_service = mock.Mock()
        app.database_maintenance = mock.Mock()

        app._submit_background_bundle_task.reset_mock()
        result_report_bundled = _load_diagnostics_report_async(
            app,
            owner=None,
            on_success=mock.Mock(),
            on_error=mock.Mock(),
            on_cancelled=mock.Mock(),
            on_finished=mock.Mock(),
            on_progress=mock.Mock(),
            on_status=mock.Mock(),
        )
        self.assertEqual(result_report_bundled, "bundle-ok")
        app._submit_background_bundle_task.assert_called()

    def test_run_diagnostics_repair_async_invokes_apply_result(self):
        bundle = SimpleNamespace()
        ctx = SimpleNamespace(set_status=mock.Mock())

        def submit_background_bundle_task(**kwargs):
            task_fn = kwargs["task_fn"]
            result = task_fn(bundle, ctx)
            kwargs["on_success"](result)
            return "bundle-run"

        on_success = mock.Mock()
        app = SimpleNamespace(
            data_root="/tmp/data",
            history_manager=mock.Mock(),
            _apply_diagnostics_repair_result=mock.Mock(return_value="ok"),
            current_db_path="/tmp/catalog.db",
            _run_bundle_diagnostics_repair=mock.Mock(return_value={"result_text": "Done"}),
            _submit_background_bundle_task=mock.Mock(side_effect=submit_background_bundle_task),
        )

        result = _run_diagnostics_repair_async(
            app,
            "schema_migrate",
            check={"repair_label": "Run schema migration"},
            owner=None,
            on_success=on_success,
            on_error=mock.Mock(),
            on_cancelled=mock.Mock(),
            on_finished=mock.Mock(),
            on_status=mock.Mock(),
        )

        self.assertEqual(result, "bundle-run")
        self.assertEqual(app._run_bundle_diagnostics_repair.call_count, 1)
        on_success.assert_called_once_with("ok")
