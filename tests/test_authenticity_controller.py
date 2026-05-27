import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isrc_manager.authenticity.controller import (
    _authenticity_signer_party_choices,
    _default_authenticity_signer_label,
    _pick_audio_authenticity_verification_file,
    _prompt_audio_authenticity_verification_source,
    _selected_track_audio_verification_candidate,
    _selected_track_audio_verification_option,
    export_authenticity_provenance_audio,
    export_authenticity_watermarked_audio,
    open_audio_authenticity_keys_dialog,
    verify_audio_authenticity,
)
from isrc_manager.authenticity.models import AuthenticityExportPlan, AuthenticityExportPlanItem


class AuthenticityControllerTests(unittest.TestCase):
    def test_default_authenticity_signer_label(self):
        app = SimpleNamespace(
            _current_owner_party_record=mock.Mock(return_value=None),
            _party_identity_primary_label=mock.Mock(),
        )
        self.assertIsNone(_default_authenticity_signer_label(app))

        record = SimpleNamespace()
        app._current_owner_party_record.return_value = record
        app._party_identity_primary_label.return_value = "Signer A"
        self.assertEqual(_default_authenticity_signer_label(app), "Signer A")
        app._party_identity_primary_label.assert_called_once_with(record)

    def test_authenticity_signer_party_choices(self):
        app = SimpleNamespace(
            party_service=None,
            _party_identity_primary_label=mock.Mock(),
        )
        self.assertEqual(_authenticity_signer_party_choices(app), [])

        app.party_service = mock.Mock(
            list_parties=mock.Mock(
                return_value=[
                    SimpleNamespace(id=1, name="A"),
                    SimpleNamespace(id=2, name="B"),
                ]
            )
        )
        app._party_identity_primary_label.side_effect = lambda record: record.name

        self.assertEqual(_authenticity_signer_party_choices(app), [(1, "A"), (2, "B")])

    def test_open_audio_authenticity_keys_dialog_warns_when_unavailable(self):
        app = SimpleNamespace(authenticity_key_service=mock.Mock())
        with mock.patch(
            "isrc_manager.authenticity.controller.AUTHENTICITY_FEATURE_AVAILABLE", False
        ):
            with mock.patch("isrc_manager.authenticity.controller._message_box") as message_box:
                box = mock.Mock()
                message_box.return_value = box
                open_audio_authenticity_keys_dialog(app)
                box.warning.assert_called_once()

    def test_open_audio_authenticity_keys_dialog_warns_when_no_service(self):
        app = SimpleNamespace(
            authenticity_key_service=None,
            _default_authenticity_signer_label=mock.Mock(return_value=None),
            _authenticity_signer_party_choices=mock.Mock(return_value=[]),
        )
        with (
            mock.patch("isrc_manager.authenticity.controller.AUTHENTICITY_FEATURE_AVAILABLE", True),
            mock.patch("isrc_manager.authenticity.controller._message_box") as message_box,
        ):
            box = mock.Mock()
            message_box.return_value = box
            open_audio_authenticity_keys_dialog(app)
            box.warning.assert_called_once_with(
                app,
                "Audio Authenticity Keys",
                "Open a profile first.",
            )

    def test_open_audio_authenticity_keys_dialog_executes_dialog(self):
        dialog_instance = mock.Mock(exec=mock.Mock())
        dialog_factory = mock.Mock(return_value=dialog_instance)
        app = SimpleNamespace(
            authenticity_key_service=mock.Mock(),
            _default_authenticity_signer_label=mock.Mock(return_value="Signer"),
            _authenticity_signer_party_choices=mock.Mock(return_value=[(1, "Signer A")]),
        )
        with (
            mock.patch("isrc_manager.authenticity.controller.AUTHENTICITY_FEATURE_AVAILABLE", True),
            mock.patch(
                "isrc_manager.authenticity.controller._root_attr", return_value=dialog_factory
            ),
        ):
            open_audio_authenticity_keys_dialog(app)

        dialog_factory.assert_called_once_with(
            key_service=app.authenticity_key_service,
            default_signer_label_provider=app._default_authenticity_signer_label,
            signer_party_choices_provider=app._authenticity_signer_party_choices,
            parent=app,
        )
        dialog_instance.exec.assert_called_once_with()

    def test_export_authenticity_watermarked_audio_warns_when_feature_unavailable(self):
        app = SimpleNamespace(audio_authenticity_service=mock.Mock())
        with mock.patch(
            "isrc_manager.authenticity.controller.AUTHENTICITY_FEATURE_AVAILABLE", False
        ):
            with mock.patch("isrc_manager.authenticity.controller._message_box") as message_box:
                box = mock.Mock()
                message_box.return_value = box
                export_authenticity_watermarked_audio(app)
                box.warning.assert_called_once()

    def test_export_authenticity_watermarked_audio_warns_when_no_service(self):
        app = SimpleNamespace(audio_authenticity_service=None)
        with (
            mock.patch("isrc_manager.authenticity.controller.AUTHENTICITY_FEATURE_AVAILABLE", True),
            mock.patch("isrc_manager.authenticity.controller._message_box") as message_box,
        ):
            box = mock.Mock()
            message_box.return_value = box
            export_authenticity_watermarked_audio(app)
            box.warning.assert_called_once_with(
                app,
                "Export Authentic Masters",
                "Open a profile first.",
            )

    def test_export_authenticity_watermarked_audio_warns_when_no_tracks(self):
        app = SimpleNamespace(
            audio_authenticity_service=mock.Mock(),
            _catalog_table_controller=mock.Mock(
                selected_or_visible_track_ids=mock.Mock(return_value=[1])
            ),
            _normalize_track_ids=mock.Mock(return_value=[]),
        )
        with (
            mock.patch("isrc_manager.authenticity.controller.AUTHENTICITY_FEATURE_AVAILABLE", True),
            mock.patch("isrc_manager.authenticity.controller._message_box") as message_box,
        ):
            box = mock.Mock()
            message_box.return_value = box
            export_authenticity_watermarked_audio(app)
            box.information.assert_called_once_with(
                app,
                "Export Authentic Masters",
                "Select one or more tracks or apply a filter first.",
            )

    def test_export_authenticity_watermarked_audio_launches_preview_and_submission(self):
        plan = AuthenticityExportPlan(
            key_id="k",
            signer_label="Signer",
            items=[
                AuthenticityExportPlanItem(
                    track_id=1,
                    track_title="Track One",
                    source_label="track.wav",
                    source_suffix=".wav",
                    suggested_name="track_one",
                    key_id="k",
                )
            ],
        )
        app = SimpleNamespace(
            audio_authenticity_service=mock.Mock(build_export_plan=mock.Mock(return_value=plan)),
            _catalog_table_controller=mock.Mock(
                selected_or_visible_track_ids=mock.Mock(return_value=[1])
            ),
            _normalize_track_ids=mock.Mock(return_value=[1]),
            _scaled_progress_callback=mock.Mock(side_effect=lambda callback, **kwargs: callback),
            _submit_background_bundle_task=mock.Mock(),
            exports_dir=Path("/tmp"),
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _show_background_task_error=mock.Mock(),
            _current_profile_name=mock.Mock(return_value="Profile"),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            _log_event=mock.Mock(),
        )
        file_dialog = mock.Mock(getExistingDirectory=mock.Mock(return_value="/tmp/out"))
        preview_dialog_instance = mock.Mock(exec=mock.Mock(return_value=1))
        preview_dialog_factory = mock.Mock(return_value=preview_dialog_instance)

        with (
            mock.patch("isrc_manager.authenticity.controller.AUTHENTICITY_FEATURE_AVAILABLE", True),
            mock.patch(
                "isrc_manager.authenticity.controller._root_attr",
                return_value=preview_dialog_factory,
            ),
            mock.patch(
                "isrc_manager.authenticity.controller._file_dialog", return_value=file_dialog
            ),
            mock.patch(
                "isrc_manager.authenticity.controller._message_box", return_value=mock.Mock()
            ),
        ):
            export_authenticity_watermarked_audio(app)
            first_call = app._submit_background_bundle_task.call_args_list[0].kwargs
            preview_success = first_call["on_success_after_cleanup"]
            preview_success(plan)

        self.assertEqual(app._submit_background_bundle_task.call_count, 2)
        second_call = app._submit_background_bundle_task.call_args_list[1].kwargs
        self.assertEqual(second_call["title"], "Export Authentic Masters")
        self.assertEqual(second_call["kind"], "write")
        self.assertEqual(second_call["unique_key"], "authenticity.export_audio")

        preview_dialog_factory.assert_called_once_with(plan=plan, parent=app)
        preview_dialog_instance.exec.assert_called_once_with()

    def test_export_authenticity_provenance_audio_handles_empty_cancel_and_success_paths(self):
        empty_plan = AuthenticityExportPlan(
            key_id="k",
            signer_label="Signer",
            items=[],
            warnings=["no provenance source"],
        )
        ready_plan = AuthenticityExportPlan(
            key_id="k",
            signer_label="Signer",
            items=[
                AuthenticityExportPlanItem(
                    track_id=2,
                    track_title="Provenance Track",
                    source_label="track.mp3",
                    source_suffix=".mp3",
                    suggested_name="track",
                    key_id="k",
                )
            ],
        )
        app = SimpleNamespace(
            audio_authenticity_service=mock.Mock(
                build_provenance_export_plan=mock.Mock(return_value=ready_plan)
            ),
            _catalog_table_controller=mock.Mock(
                selected_or_visible_track_ids=mock.Mock(return_value=[2])
            ),
            _normalize_track_ids=mock.Mock(return_value=[2]),
            _scaled_progress_callback=mock.Mock(side_effect=lambda callback, **kwargs: callback),
            _submit_background_bundle_task=mock.Mock(),
            exports_dir=Path("/tmp"),
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _show_background_task_error=mock.Mock(),
            _current_profile_name=mock.Mock(return_value="Profile"),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            _log_event=mock.Mock(),
            _advance_task_ui_progress=mock.Mock(),
        )
        file_dialog = mock.Mock(getExistingDirectory=mock.Mock(side_effect=["", "/tmp/out"]))
        messages = mock.Mock()
        preview_dialog_instance = mock.Mock(exec=mock.Mock(return_value=1))
        preview_dialog_factory = mock.Mock(return_value=preview_dialog_instance)

        with (
            mock.patch("isrc_manager.authenticity.controller.AUTHENTICITY_FEATURE_AVAILABLE", True),
            mock.patch(
                "isrc_manager.authenticity.controller._root_attr",
                return_value=preview_dialog_factory,
            ),
            mock.patch(
                "isrc_manager.authenticity.controller._file_dialog", return_value=file_dialog
            ),
            mock.patch("isrc_manager.authenticity.controller._message_box", return_value=messages),
        ):
            export_authenticity_provenance_audio(app, [2])
            first_call = app._submit_background_bundle_task.call_args_list[0].kwargs
            preview_success = first_call["on_success_after_cleanup"]
            preview_success(empty_plan)
            preview_success(ready_plan)
            self.assertEqual(app._submit_background_bundle_task.call_count, 1)
            preview_success(ready_plan)

        self.assertEqual(app._submit_background_bundle_task.call_count, 2)
        messages.information.assert_called()
        second_call = app._submit_background_bundle_task.call_args_list[1].kwargs
        self.assertEqual(second_call["title"], "Export Provenance Copies")
        self.assertEqual(second_call["unique_key"], "authenticity.export_provenance_audio")
        bundle = SimpleNamespace(
            audio_authenticity_service=mock.Mock(
                export_provenance_audio=mock.Mock(
                    return_value=SimpleNamespace(exported=1, skipped=0, warnings=["signed"])
                )
            )
        )
        ctx = SimpleNamespace(
            report_progress=mock.Mock(),
            is_cancelled=mock.Mock(return_value=False),
        )
        result = second_call["task_fn"](bundle, ctx)
        second_call["on_success_before_cleanup"](result, mock.Mock())
        with mock.patch(
            "isrc_manager.authenticity.controller._message_box",
            return_value=messages,
        ):
            second_call["on_success_after_cleanup"](result)
        second_call["on_cancelled"]()

        bundle.audio_authenticity_service.export_provenance_audio.assert_called_once()
        app._log_event.assert_called_once()
        app._audit.assert_called_once_with(
            "EXPORT",
            "AudioAuthenticityLineage",
            ref_id="/tmp/out",
            details="exported=1; skipped=0",
        )
        app.statusBar().showMessage.assert_called_with("Provenance export cancelled.", 5000)

    def test_selected_track_audio_verification_option_handles_invalid_selection(self):
        app = SimpleNamespace(
            track_service=mock.Mock(
                has_media=mock.Mock(),
                fetch_track_snapshot=mock.Mock(),
            ),
            _catalog_table_controller=mock.Mock(selected_track_ids=mock.Mock(return_value=[1, 2])),
            _normalize_track_ids=mock.Mock(return_value=[1, 2]),
        )
        self.assertIsNone(_selected_track_audio_verification_option(app))

    def test_selected_track_audio_verification_option_returns_track(self):
        app = SimpleNamespace(
            track_service=mock.Mock(
                has_media=mock.Mock(return_value=True),
                fetch_track_snapshot=mock.Mock(
                    return_value=SimpleNamespace(
                        audio_file_filename="track.wav",
                        audio_file_path="/tmp/track.wav",
                        track_title="Demo",
                    )
                ),
            ),
            _catalog_table_controller=mock.Mock(selected_track_ids=mock.Mock(return_value=[7])),
            _normalize_track_ids=mock.Mock(return_value=[7]),
        )
        result = _selected_track_audio_verification_option(app)
        self.assertEqual(result, (7, "Demo"))

    def test_selected_track_audio_verification_candidate_uses_resolved_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "track.wav"
            path.write_bytes(b"audio")
            app = SimpleNamespace(
                track_service=mock.Mock(
                    has_media=mock.Mock(return_value=True),
                    fetch_track_snapshot=mock.Mock(
                        return_value=SimpleNamespace(
                            audio_file_filename="track.wav",
                            audio_file_path=str(path),
                        )
                    ),
                    resolve_media_path=mock.Mock(return_value=path),
                )
            )

            selected, cleanup_root = _selected_track_audio_verification_candidate(app, 3)

            self.assertEqual(selected, path)
            self.assertIsNone(cleanup_root)

    def test_selected_track_audio_verification_candidate_materializes_blob_and_rejects_unsupported(
        self,
    ):
        app = SimpleNamespace(
            track_service=mock.Mock(
                has_media=mock.Mock(return_value=True),
                fetch_track_snapshot=mock.Mock(
                    side_effect=[
                        SimpleNamespace(
                            audio_file_filename="track.wav",
                            audio_file_path="managed/track.wav",
                        ),
                        SimpleNamespace(
                            audio_file_filename="track.txt",
                            audio_file_path="managed/track.txt",
                        ),
                        None,
                    ]
                ),
                resolve_media_path=mock.Mock(return_value=None),
                fetch_media_bytes=mock.Mock(return_value=(b"audio", "audio/wav")),
            )
        )

        selected, cleanup_root = _selected_track_audio_verification_candidate(app, 3)
        try:
            self.assertIsNotNone(selected)
            self.assertIsNotNone(cleanup_root)
            assert selected is not None
            self.assertEqual(selected.read_bytes(), b"audio")
        finally:
            if cleanup_root is not None:
                for child in Path(cleanup_root).iterdir():
                    child.unlink()
                Path(cleanup_root).rmdir()

        self.assertEqual(
            _selected_track_audio_verification_candidate(app, 4),
            (None, None),
        )
        self.assertEqual(
            _selected_track_audio_verification_candidate(app, 5),
            (None, None),
        )

    def test_prompt_audio_authenticity_verification_source_routes_choices(self):
        chooser = mock.Mock()
        chooser_factory = mock.Mock(return_value=chooser)
        selected_button = object()
        external_button = object()

        def _add_button(*args, **kwargs):
            if args[0] == "Selected Track Audio":
                return selected_button
            return external_button

        chooser.addButton.side_effect = _add_button
        chooser.clickedButton.side_effect = [selected_button, external_button, object()]

        with mock.patch(
            "isrc_manager.authenticity.controller._message_box",
            return_value=chooser_factory,
        ):
            self.assertEqual(
                _prompt_audio_authenticity_verification_source(mock.Mock(), "Track"), "selected"
            )
            self.assertEqual(
                _prompt_audio_authenticity_verification_source(mock.Mock(), "Track"), "external"
            )
            self.assertIsNone(_prompt_audio_authenticity_verification_source(mock.Mock(), "Track"))

    def test_pick_audio_authenticity_verification_file_returns_none_or_path(self):
        app = mock.Mock()
        with mock.patch(
            "isrc_manager.authenticity.controller._file_dialog",
            return_value=mock.Mock(getOpenFileName=mock.Mock(return_value=("", ""))),
        ):
            self.assertIsNone(_pick_audio_authenticity_verification_file(app))

        with mock.patch(
            "isrc_manager.authenticity.controller._file_dialog",
            return_value=mock.Mock(
                getOpenFileName=mock.Mock(return_value=("/tmp/audio.wav", "Audio Files"))
            ),
        ):
            resolved = _pick_audio_authenticity_verification_file(app)
            self.assertEqual(resolved, Path("/tmp/audio.wav").resolve())

    def test_verify_audio_authenticity_with_explicit_path_submits_task(self):
        dialog = mock.Mock(exec=mock.Mock())

        def fake_root_attr(name, fallback):
            if name == "AuthenticityVerificationDialog":
                return mock.Mock(return_value=dialog)
            return fallback

        app = SimpleNamespace(
            audio_authenticity_service=mock.Mock(),
            _selected_track_audio_verification_option=mock.Mock(return_value=None),
            _pick_audio_authenticity_verification_file=mock.Mock(
                return_value=Path("/tmp/audio.wav")
            ),
            _submit_background_bundle_task=mock.Mock(),
            _show_background_task_error=mock.Mock(),
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _log_event=mock.Mock(),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
        )
        with (
            mock.patch("isrc_manager.authenticity.controller.AUTHENTICITY_FEATURE_AVAILABLE", True),
            mock.patch("isrc_manager.authenticity.controller._root_attr", fake_root_attr),
        ):
            verify_audio_authenticity(app, path="/tmp/audio.wav")

        self.assertEqual(app._submit_background_bundle_task.call_count, 1)
        kwargs = app._submit_background_bundle_task.call_args.kwargs
        self.assertEqual(kwargs["title"], "Verify Audio Authenticity")
        self.assertEqual(kwargs["kind"], "read")
        self.assertEqual(kwargs["unique_key"], "authenticity.verify_audio")

        report = SimpleNamespace(status="valid", manifest_id="m1", key_id="k1")
        bundle = SimpleNamespace(
            audio_authenticity_service=mock.Mock(verify_file=mock.Mock(return_value=report))
        )
        self.assertIs(kwargs["task_fn"](bundle, mock.Mock()), report)
        with mock.patch("isrc_manager.authenticity.controller._root_attr", fake_root_attr):
            kwargs["on_success"](report)
        app._log_event.assert_called_once_with(
            "authenticity.verify_audio",
            "Verified audio authenticity",
            path=str(Path("/tmp/audio.wav").resolve()),
            status="valid",
            manifest_id="m1",
            key_id="k1",
        )
        app._audit.assert_called_once_with(
            "VERIFY",
            "AudioAuthenticity",
            ref_id=str(Path("/tmp/audio.wav").resolve()),
            details="valid",
        )
        dialog.exec.assert_called_once()

    def test_verify_audio_authenticity_cleans_up_temp_capture_path(self):
        temp_root = tempfile.TemporaryDirectory()
        temp_path = Path(temp_root.name) / "track.wav"
        temp_path.write_bytes(b"audio")

        app = SimpleNamespace(
            audio_authenticity_service=mock.Mock(),
            _selected_track_audio_verification_option=mock.Mock(return_value=(1, "Demo")),
            _prompt_audio_authenticity_verification_source=mock.Mock(return_value="selected"),
            _selected_track_audio_verification_candidate=mock.Mock(
                return_value=(temp_path, temp_root.name)
            ),
            _submit_background_bundle_task=mock.Mock(),
            _show_background_task_error=mock.Mock(),
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _log_event=mock.Mock(),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            _pick_audio_authenticity_verification_file=mock.Mock(return_value=None),
        )

        with (
            mock.patch("isrc_manager.authenticity.controller.AUTHENTICITY_FEATURE_AVAILABLE", True),
            mock.patch("shutil.rmtree") as rmtree,
        ):
            verify_audio_authenticity(app)
            on_finished = app._submit_background_bundle_task.call_args.kwargs["on_finished"]
            on_finished()
            rmtree.assert_called_once_with(temp_root.name, ignore_errors=True)

        temp_root.cleanup()
