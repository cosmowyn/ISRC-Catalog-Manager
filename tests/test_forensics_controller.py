import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isrc_manager.forensics.controller import (
    _file_dialog,
    _message_box,
    _root_attr,
    _soundcloud_account_public_profile,
    _soundcloud_forensic_share_label,
    export_forensic_watermarked_audio,
    export_soundcloud_forensic_watermarked_audio,
    inspect_forensic_watermark,
)
from isrc_manager.forensics.models import ForensicExportResult, ForensicInspectionReport


class ForensicsControllerTests(unittest.TestCase):
    def test_root_attr_falls_back_when_main_window_missing(self):
        self.assertIs(_root_attr("MissingName", mock.sentinel.fallback), mock.sentinel.fallback)

    def test_dialog_helpers_use_main_window_overrides(self):
        with mock.patch.dict(
            "sys.modules",
            {
                "isrc_manager.main_window": SimpleNamespace(
                    QMessageBox=mock.sentinel.message_box,
                    QFileDialog=mock.sentinel.file_dialog,
                )
            },
        ):
            self.assertIs(_message_box(), mock.sentinel.message_box)
            self.assertIs(_file_dialog(), mock.sentinel.file_dialog)

    def test_soundcloud_account_public_profile_handles_missing_or_unavailable_accounts(self):
        self.assertEqual(_soundcloud_account_public_profile(SimpleNamespace(conn=None)), {})

        with mock.patch(
            "isrc_manager.integrations.soundcloud.persistence.SoundCloudSQLiteRepository",
            side_effect=RuntimeError("repository unavailable"),
        ):
            self.assertEqual(_soundcloud_account_public_profile(SimpleNamespace(conn=object())), {})

        repository = mock.Mock(active_account=mock.Mock(return_value=None))
        with mock.patch(
            "isrc_manager.integrations.soundcloud.persistence.SoundCloudSQLiteRepository",
            return_value=repository,
        ):
            self.assertEqual(_soundcloud_account_public_profile(SimpleNamespace(conn=object())), {})

    def test_soundcloud_account_public_profile_returns_public_trace_fields_only(self):
        account = SimpleNamespace(
            soundcloud_user_id=" 55 ",
            username=" Artist ",
            permalink_url=" https://soundcloud.com/artist ",
            avatar_url=" ",
            oauth_token="secret",
        )
        repository = mock.Mock(active_account=mock.Mock(return_value=account))

        with mock.patch(
            "isrc_manager.integrations.soundcloud.persistence.SoundCloudSQLiteRepository",
            return_value=repository,
        ):
            profile = _soundcloud_account_public_profile(SimpleNamespace(conn=object()))

        self.assertEqual(
            profile,
            {
                "user_id": "55",
                "username": "Artist",
                "profile_url": "https://soundcloud.com/artist",
            },
        )
        self.assertNotIn("oauth_token", profile)

    def test_export_forensic_watermarked_audio_warns_when_track_service_missing(self):
        app = SimpleNamespace(track_service=None)
        with mock.patch("isrc_manager.forensics.controller._message_box") as message_box:
            box = mock.Mock()
            message_box.return_value = box
            export_forensic_watermarked_audio(app)
            box.warning.assert_called_once_with(
                app,
                "Export Forensic Watermarked Audio",
                "Open a profile first.",
            )

    def test_export_forensic_watermarked_audio_warns_when_services_missing(self):
        app = SimpleNamespace(
            track_service=mock.Mock(),
            forensic_export_service=None,
            audio_conversion_service=mock.Mock(),
        )
        with mock.patch("isrc_manager.forensics.controller._message_box") as message_box:
            box = mock.Mock()
            message_box.return_value = box
            export_forensic_watermarked_audio(app)
            box.warning.assert_called_once()

    def test_export_forensic_watermarked_audio_warns_when_conversion_unavailable(self):
        app = SimpleNamespace(
            track_service=mock.Mock(),
            forensic_export_service=mock.Mock(),
            audio_conversion_service=mock.Mock(),
            _audio_conversion_unavailable_message=mock.Mock(return_value="ffmpeg unavailable"),
        )
        with mock.patch("isrc_manager.forensics.controller._message_box") as message_box:
            box = mock.Mock()
            message_box.return_value = box
            export_forensic_watermarked_audio(app)
            box.warning.assert_called_once_with(
                app,
                "Export Forensic Watermarked Audio",
                "ffmpeg unavailable",
            )

    def test_export_forensic_watermarked_audio_warns_when_no_tracks_selected(self):
        app = SimpleNamespace(
            track_service=mock.Mock(),
            forensic_export_service=mock.Mock(),
            audio_conversion_service=mock.Mock(
                capabilities=mock.Mock(
                    return_value=SimpleNamespace(managed_forensic_targets=[("mp3", "MP3")])
                )
            ),
            _audio_conversion_unavailable_message=mock.Mock(return_value=None),
            _selected_track_ids_with_audio=mock.Mock(return_value=[]),
        )
        with mock.patch("isrc_manager.forensics.controller._message_box") as message_box:
            box = mock.Mock()
            message_box.return_value = box
            export_forensic_watermarked_audio(app)
            box.information.assert_called_once_with(
                app,
                "Export Forensic Watermarked Audio",
                "Select one or more tracks with attached primary audio first.",
            )

    def test_export_forensic_watermarked_audio_warns_when_no_formats_available(self):
        app = SimpleNamespace(
            track_service=mock.Mock(),
            forensic_export_service=mock.Mock(),
            audio_conversion_service=mock.Mock(
                capabilities=mock.Mock(return_value=SimpleNamespace(managed_forensic_targets=[]))
            ),
            _audio_conversion_unavailable_message=mock.Mock(return_value=None),
            _selected_track_ids_with_audio=mock.Mock(return_value=[1]),
        )
        with mock.patch("isrc_manager.forensics.controller._message_box") as message_box:
            box = mock.Mock()
            message_box.return_value = box
            export_forensic_watermarked_audio(app)
            box.warning.assert_called_once_with(
                app,
                "Export Forensic Watermarked Audio",
                "No forensic watermark export targets are available in this runtime.",
            )

    def test_export_forensic_watermarked_audio_aborts_without_format_or_output_folder(self):
        base_app = dict(
            track_service=mock.Mock(),
            forensic_export_service=mock.Mock(),
            audio_conversion_service=mock.Mock(
                capabilities=mock.Mock(
                    return_value=SimpleNamespace(
                        managed_forensic_targets=[
                            SimpleNamespace(id="wav", label="WAV", lossy=False),
                        ]
                    )
                )
            ),
            exports_dir=Path("/tmp"),
            _audio_conversion_unavailable_message=mock.Mock(return_value=None),
            _selected_track_ids_with_audio=mock.Mock(return_value=[1]),
            _submit_background_bundle_task=mock.Mock(),
        )
        no_format_app = SimpleNamespace(
            **base_app,
            _prompt_audio_conversion_format=mock.Mock(return_value=""),
        )
        with mock.patch("isrc_manager.forensics.controller.ForensicExportDialog", None):
            export_forensic_watermarked_audio(no_format_app)
        no_format_app._submit_background_bundle_task.assert_not_called()

        no_folder_app = SimpleNamespace(
            **base_app,
            _prompt_audio_conversion_format=mock.Mock(return_value="wav"),
        )
        file_dialog = mock.Mock(getExistingDirectory=mock.Mock(return_value=""))
        with (
            mock.patch("isrc_manager.forensics.controller.ForensicExportDialog", None),
            mock.patch("isrc_manager.forensics.controller._file_dialog", return_value=file_dialog),
        ):
            export_forensic_watermarked_audio(no_folder_app)
        no_folder_app._submit_background_bundle_task.assert_not_called()

    def test_export_forensic_watermarked_audio_prompt_path_submits_background_task(self):
        app = SimpleNamespace(
            track_service=mock.Mock(),
            forensic_export_service=mock.Mock(),
            audio_conversion_service=mock.Mock(
                capabilities=mock.Mock(
                    return_value=SimpleNamespace(
                        managed_forensic_targets=[
                            SimpleNamespace(id="mp3", label="mp3", lossy=True),
                        ]
                    )
                )
            ),
            exports_dir=Path("/tmp"),
            _audio_conversion_unavailable_message=mock.Mock(return_value=None),
            _selected_track_ids_with_audio=mock.Mock(return_value=[1]),
            _prompt_audio_conversion_format=mock.Mock(return_value="mp3"),
            _submit_background_bundle_task=mock.Mock(),
            _scaled_progress_callback=mock.Mock(side_effect=lambda callback, **kwargs: callback),
            _show_background_task_error=mock.Mock(),
            _log_event=mock.Mock(),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            _advance_task_ui_progress=mock.Mock(),
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _current_profile_name=mock.Mock(return_value="Profile"),
        )
        file_dialog = mock.Mock(getExistingDirectory=mock.Mock(return_value="/tmp/out"))
        info_box = mock.Mock()

        with (
            mock.patch("isrc_manager.forensics.controller.ForensicExportDialog", None),
            mock.patch("isrc_manager.forensics.controller._file_dialog", return_value=file_dialog),
            mock.patch("isrc_manager.forensics.controller._message_box", return_value=info_box),
        ):
            export_forensic_watermarked_audio(app)
            task_kwargs = app._submit_background_bundle_task.call_args.kwargs
            export_service = mock.Mock()
            ctx = SimpleNamespace(
                report_progress=mock.Mock(),
                is_cancelled=mock.Mock(return_value=False),
            )
            task_kwargs["task_fn"](SimpleNamespace(forensic_export_service=export_service), ctx)
            request = export_service.export.call_args.args[0]
            self.assertEqual(request.track_ids, [1])
            self.assertEqual(request.output_dir, "/tmp/out")
            self.assertEqual(request.output_format, "mp3")
            self.assertIsNone(request.recipient_label)
            self.assertIsNone(request.share_label)
            self.assertEqual(request.profile_name, "Profile")

            result = ForensicExportResult(
                requested=1,
                exported=1,
                skipped=0,
                warnings=["low headroom"],
                written_paths=["/tmp/out/track.mp3"],
                derivative_ids=["derivative-1"],
                forensic_export_ids=["forensic-1"],
                batch_public_id="batch-1",
            )
            ui_progress = object()
            task_kwargs["on_success_before_cleanup"](result, ui_progress)
            task_kwargs["on_success_after_cleanup"](result)

        app._prompt_audio_conversion_format.assert_called_once_with(
            title="Export Forensic Watermarked Audio",
            prompt=(
                "Choose the forensic delivery output format. "
                "These exports are recipient-specific leak-tracing copies, not signed authenticity masters."
            ),
            capability_group="managed_forensic",
        )

        app._submit_background_bundle_task.assert_called_once_with(
            title="Export Forensic Watermarked Audio",
            description=(
                "Converting selected catalog audio into delivery copies, writing tags, embedding recipient-specific forensic watermarks, hashing final files, and registering forensic export lineage..."
            ),
            task_fn=mock.ANY,
            kind="write",
            unique_key="forensics.export_audio",
            cancellable=True,
            worker_completion_progress=(96, "Finalizing forensic watermark export results..."),
            on_cancelled=mock.ANY,
            on_error=mock.ANY,
            on_success_before_cleanup=mock.ANY,
            on_success_after_cleanup=mock.ANY,
        )
        app._advance_task_ui_progress.assert_any_call(
            ui_progress,
            value=97,
            message="Recording forensic watermark export results...",
        )
        app._advance_task_ui_progress.assert_any_call(
            ui_progress,
            value=100,
            message="Forensic watermark export complete.",
        )
        app._log_event.assert_called_once()
        app._audit.assert_called_once()
        app._audit_commit.assert_called_once_with()
        info_box.information.assert_called_once()
        self.assertIn(
            "Exported 1 forensic watermarked copy.",
            info_box.information.call_args.args[2],
        )
        self.assertIn("Warnings:\n- low headroom", info_box.information.call_args.args[2])

    def test_export_forensic_watermarked_audio_cancels_when_dialog_rejected(self):
        app = SimpleNamespace(
            track_service=mock.Mock(),
            forensic_export_service=mock.Mock(),
            audio_conversion_service=mock.Mock(
                capabilities=mock.Mock(
                    return_value=SimpleNamespace(
                        managed_forensic_targets=[
                            SimpleNamespace(id="mp3", label="mp3", lossy=True),
                        ]
                    )
                )
            ),
            exports_dir=Path("/tmp"),
            _audio_conversion_unavailable_message=mock.Mock(return_value=None),
            _selected_track_ids_with_audio=mock.Mock(return_value=[1]),
            _prompt_audio_conversion_format=mock.Mock(return_value="mp3"),
            _submit_background_bundle_task=mock.Mock(),
            _scaled_progress_callback=mock.Mock(side_effect=lambda callback, **kwargs: callback),
            _show_background_task_error=mock.Mock(),
            _log_event=mock.Mock(),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _current_profile_name=mock.Mock(return_value="Profile"),
        )
        # QDialog constants are 1 for Accept and 0 for Reject in most Qt configurations.
        dialog_instance = mock.Mock(exec=mock.Mock(return_value=0))
        dialog_factory = mock.Mock(return_value=dialog_instance)

        with mock.patch(
            "isrc_manager.forensics.controller._root_attr",
            side_effect=lambda name, fallback: (
                dialog_factory if name == "ForensicExportDialog" else fallback
            ),
        ):
            export_forensic_watermarked_audio(app)

        app._submit_background_bundle_task.assert_not_called()
        dialog_factory.assert_called_once_with(
            format_labels=[("mp3", "mp3 (lossy forensic delivery copy)")], parent=app
        )
        dialog_instance.exec.assert_called_once_with()

    def test_export_forensic_watermarked_audio_dialog_accepts_recipient_metadata(self):
        app = SimpleNamespace(
            track_service=mock.Mock(),
            forensic_export_service=mock.Mock(),
            audio_conversion_service=mock.Mock(
                capabilities=mock.Mock(
                    return_value=SimpleNamespace(
                        managed_forensic_targets=[
                            SimpleNamespace(id="flac", label="FLAC", lossy=False),
                        ]
                    )
                )
            ),
            exports_dir=Path("/tmp"),
            _audio_conversion_unavailable_message=mock.Mock(return_value=None),
            _selected_track_ids_with_audio=mock.Mock(return_value=[2]),
            _submit_background_bundle_task=mock.Mock(),
            _scaled_progress_callback=mock.Mock(side_effect=lambda callback, **kwargs: callback),
            _show_background_task_error=mock.Mock(),
            _log_event=mock.Mock(),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _current_profile_name=mock.Mock(return_value="Profile"),
        )
        dialog_instance = mock.Mock(
            exec=mock.Mock(return_value=1),
            selected_format_id=mock.Mock(return_value="flac"),
            recipient_label=mock.Mock(return_value="Reviewer"),
            share_label=mock.Mock(return_value="Private review"),
        )
        dialog_factory = mock.Mock(return_value=dialog_instance)
        file_dialog = mock.Mock(getExistingDirectory=mock.Mock(return_value="/tmp/review"))

        with (
            mock.patch("isrc_manager.forensics.controller.QDialog", SimpleNamespace(Accepted=1)),
            mock.patch(
                "isrc_manager.forensics.controller._root_attr",
                side_effect=lambda name, fallback: (
                    dialog_factory if name == "ForensicExportDialog" else fallback
                ),
            ),
            mock.patch("isrc_manager.forensics.controller._file_dialog", return_value=file_dialog),
        ):
            export_forensic_watermarked_audio(app)
            task_fn = app._submit_background_bundle_task.call_args.kwargs["task_fn"]
            export_service = mock.Mock()
            task_fn(
                SimpleNamespace(forensic_export_service=export_service),
                SimpleNamespace(report_progress=mock.Mock(), is_cancelled=mock.Mock()),
            )

        request = export_service.export.call_args.args[0]
        self.assertEqual(request.output_format, "flac")
        self.assertEqual(request.recipient_label, "Reviewer")
        self.assertEqual(request.share_label, "Private review")

    def test_soundcloud_share_label_uses_public_profile_without_secret_fields(self):
        label = _soundcloud_forensic_share_label(
            public_profile={
                "username": "Cosmowyn Records",
                "user_id": "42",
                "profile_url": "https://soundcloud.com/cosmowyn",
                "avatar_url": "https://i1.sndcdn.com/avatar.jpg",
                "scope": "non-secret-but-not-public-profile-trace",
                "token_store_key": "secret-ish",
            },
            upload_label="Forgiveness public upload",
        )

        self.assertIn("SoundCloud upload", label)
        self.assertIn("label=Forgiveness public upload", label)
        self.assertIn("username=Cosmowyn Records", label)
        self.assertIn("user_id=42", label)
        self.assertIn("profile_url=https://soundcloud.com/cosmowyn", label)
        self.assertIn("avatar_url=https://i1.sndcdn.com/avatar.jpg", label)
        self.assertNotIn("scope", label)
        self.assertNotIn("token_store_key", label)

    def test_soundcloud_share_label_notes_unavailable_public_profile(self):
        self.assertEqual(
            _soundcloud_forensic_share_label(public_profile={}),
            "SoundCloud upload; public_profile=unavailable",
        )

    def test_export_soundcloud_forensic_audio_warns_for_unavailable_inputs(self):
        cases = [
            (
                SimpleNamespace(track_service=None),
                "Open a profile first.",
            ),
            (
                SimpleNamespace(
                    track_service=mock.Mock(),
                    forensic_export_service=None,
                    audio_conversion_service=mock.Mock(),
                ),
                "SoundCloud forensic export requires an open profile, a local authenticity key, and managed conversion support.",
            ),
            (
                SimpleNamespace(
                    track_service=mock.Mock(),
                    forensic_export_service=mock.Mock(),
                    audio_conversion_service=mock.Mock(),
                    _audio_conversion_unavailable_message=mock.Mock(return_value="converter down"),
                ),
                "converter down",
            ),
            (
                SimpleNamespace(
                    track_service=mock.Mock(),
                    forensic_export_service=mock.Mock(),
                    audio_conversion_service=mock.Mock(
                        capabilities=mock.Mock(
                            return_value=SimpleNamespace(managed_forensic_targets=[])
                        )
                    ),
                    _audio_conversion_unavailable_message=mock.Mock(return_value=None),
                    _selected_track_ids_with_audio=mock.Mock(return_value=[4]),
                ),
                "No forensic watermark export targets are available in this runtime.",
            ),
        ]
        for app, message in cases:
            with self.subTest(message=message):
                with mock.patch("isrc_manager.forensics.controller._message_box") as message_box:
                    box = mock.Mock()
                    message_box.return_value = box
                    export_soundcloud_forensic_watermarked_audio(app)
                    box.warning.assert_called_once_with(
                        app,
                        "Export SoundCloud Forensic Upload Audio",
                        message,
                    )

    def test_export_soundcloud_forensic_audio_informs_when_no_tracks_selected(self):
        app = SimpleNamespace(
            track_service=mock.Mock(),
            forensic_export_service=mock.Mock(),
            audio_conversion_service=mock.Mock(),
            _audio_conversion_unavailable_message=mock.Mock(return_value=None),
            _selected_track_ids_with_audio=mock.Mock(return_value=[]),
        )
        with mock.patch("isrc_manager.forensics.controller._message_box") as message_box:
            box = mock.Mock()
            message_box.return_value = box
            export_soundcloud_forensic_watermarked_audio(app)
            box.information.assert_called_once_with(
                app,
                "Export SoundCloud Forensic Upload Audio",
                "Select one or more tracks with attached primary audio first.",
            )

    def test_export_soundcloud_forensic_audio_aborts_without_format_or_output_folder(self):
        base_app = dict(
            track_service=mock.Mock(),
            forensic_export_service=mock.Mock(),
            audio_conversion_service=mock.Mock(
                capabilities=mock.Mock(
                    return_value=SimpleNamespace(
                        managed_forensic_targets=[
                            SimpleNamespace(id="wav", label="WAV", lossy=False),
                        ]
                    )
                )
            ),
            exports_dir=Path("/tmp"),
            conn=None,
            _audio_conversion_unavailable_message=mock.Mock(return_value=None),
            _selected_track_ids_with_audio=mock.Mock(return_value=[1]),
            _submit_background_bundle_task=mock.Mock(),
        )
        no_format_app = SimpleNamespace(
            **base_app,
            _prompt_audio_conversion_format=mock.Mock(return_value=""),
        )
        with mock.patch("isrc_manager.forensics.controller.ForensicExportDialog", None):
            export_soundcloud_forensic_watermarked_audio(no_format_app)
        no_format_app._submit_background_bundle_task.assert_not_called()

        no_folder_app = SimpleNamespace(
            **base_app,
            _prompt_audio_conversion_format=mock.Mock(return_value="wav"),
        )
        file_dialog = mock.Mock(getExistingDirectory=mock.Mock(return_value=""))
        with (
            mock.patch("isrc_manager.forensics.controller.ForensicExportDialog", None),
            mock.patch("isrc_manager.forensics.controller._file_dialog", return_value=file_dialog),
        ):
            export_soundcloud_forensic_watermarked_audio(no_folder_app)
        no_folder_app._submit_background_bundle_task.assert_not_called()

    def test_export_soundcloud_forensic_audio_builds_fixed_recipient_request(self):
        export_service = mock.Mock()
        app = SimpleNamespace(
            track_service=mock.Mock(),
            forensic_export_service=export_service,
            audio_conversion_service=mock.Mock(
                capabilities=mock.Mock(
                    return_value=SimpleNamespace(
                        managed_forensic_targets=[
                            SimpleNamespace(id="wav", label="WAV", lossy=False),
                        ]
                    )
                )
            ),
            exports_dir=Path("/tmp"),
            _audio_conversion_unavailable_message=mock.Mock(return_value=None),
            _selected_track_ids_with_audio=mock.Mock(return_value=[7]),
            _prompt_audio_conversion_format=mock.Mock(return_value="wav"),
            _submit_background_bundle_task=mock.Mock(),
            _scaled_progress_callback=mock.Mock(side_effect=lambda callback, **kwargs: callback),
            _show_background_task_error=mock.Mock(),
            _log_event=mock.Mock(),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            _advance_task_ui_progress=mock.Mock(),
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _current_profile_name=mock.Mock(return_value="Profile"),
        )
        file_dialog = mock.Mock(getExistingDirectory=mock.Mock(return_value="/tmp/sc-out"))
        info_box = mock.Mock()

        with (
            mock.patch("isrc_manager.forensics.controller.ForensicExportDialog", None),
            mock.patch("isrc_manager.forensics.controller._file_dialog", return_value=file_dialog),
            mock.patch("isrc_manager.forensics.controller._message_box", return_value=info_box),
            mock.patch(
                "isrc_manager.forensics.controller._soundcloud_account_public_profile",
                return_value={
                    "username": "Artist",
                    "user_id": "55",
                    "profile_url": "https://soundcloud.com/artist",
                },
            ),
        ):
            export_soundcloud_forensic_watermarked_audio(app)

        app._submit_background_bundle_task.assert_called_once()
        task_fn = app._submit_background_bundle_task.call_args.kwargs["task_fn"]
        ctx = SimpleNamespace(
            report_progress=mock.Mock(),
            is_cancelled=mock.Mock(return_value=False),
        )
        task_fn(SimpleNamespace(forensic_export_service=export_service), ctx)
        request = export_service.export.call_args.args[0]
        self.assertEqual(request.track_ids, [7])
        self.assertEqual(request.output_dir, "/tmp/sc-out")
        self.assertEqual(request.output_format, "wav")
        self.assertEqual(request.recipient_label, "SoundCloud")
        self.assertTrue(request.embed_trace_metadata)
        self.assertIn("username=Artist", request.share_label)
        self.assertIn("profile_url=https://soundcloud.com/artist", request.share_label)
        result = ForensicExportResult(
            requested=2,
            exported=2,
            skipped=0,
            warnings=[],
            written_paths=["/tmp/sc-out/one.wav", "/tmp/sc-out/two.wav"],
            derivative_ids=["d1", "d2"],
            forensic_export_ids=["f1", "f2"],
            batch_public_id="batch-sc",
            zip_path="/tmp/sc.zip",
        )
        ui_progress = object()
        task_kwargs = app._submit_background_bundle_task.call_args.kwargs
        task_kwargs["on_success_before_cleanup"](result, ui_progress)
        with mock.patch(
            "isrc_manager.forensics.controller._message_box",
            return_value=info_box,
        ):
            task_kwargs["on_success_after_cleanup"](result)

        app._advance_task_ui_progress.assert_any_call(
            ui_progress,
            value=97,
            message="Recording SoundCloud forensic export results...",
        )
        app._advance_task_ui_progress.assert_any_call(
            ui_progress,
            value=100,
            message="SoundCloud forensic export complete.",
        )
        app._log_event.assert_called_once()
        app._audit.assert_called_once()
        app._audit_commit.assert_called_once_with()
        info_box.information.assert_called_once()
        self.assertIn(
            "Exported 2 SoundCloud forensic upload copies.",
            info_box.information.call_args.args[2],
        )
        self.assertIn("Public SoundCloud trace:", info_box.information.call_args.args[2])

    def test_export_soundcloud_forensic_audio_dialog_accepts_upload_label(self):
        export_service = mock.Mock()
        app = SimpleNamespace(
            track_service=mock.Mock(),
            forensic_export_service=export_service,
            audio_conversion_service=mock.Mock(
                capabilities=mock.Mock(
                    return_value=SimpleNamespace(
                        managed_forensic_targets=[
                            SimpleNamespace(id="wav", label="WAV", lossy=False),
                        ]
                    )
                )
            ),
            exports_dir=Path("/tmp"),
            conn=None,
            _audio_conversion_unavailable_message=mock.Mock(return_value=None),
            _selected_track_ids_with_audio=mock.Mock(return_value=[7]),
            _submit_background_bundle_task=mock.Mock(),
            _scaled_progress_callback=mock.Mock(side_effect=lambda callback, **kwargs: callback),
            _show_background_task_error=mock.Mock(),
            _log_event=mock.Mock(),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _current_profile_name=mock.Mock(return_value="Profile"),
        )
        dialog_instance = mock.Mock(
            exec=mock.Mock(return_value=1),
            selected_format_id=mock.Mock(return_value="wav"),
            share_label=mock.Mock(return_value="Premiere"),
        )
        dialog_factory = mock.Mock(return_value=dialog_instance)
        file_dialog = mock.Mock(getExistingDirectory=mock.Mock(return_value="/tmp/sc-out"))

        with (
            mock.patch("isrc_manager.forensics.controller.QDialog", SimpleNamespace(Accepted=1)),
            mock.patch(
                "isrc_manager.forensics.controller._root_attr",
                side_effect=lambda name, fallback: (
                    dialog_factory if name == "ForensicExportDialog" else fallback
                ),
            ),
            mock.patch("isrc_manager.forensics.controller._file_dialog", return_value=file_dialog),
        ):
            export_soundcloud_forensic_watermarked_audio(app)
            task_fn = app._submit_background_bundle_task.call_args.kwargs["task_fn"]
            task_fn(
                SimpleNamespace(forensic_export_service=export_service),
                SimpleNamespace(report_progress=mock.Mock(), is_cancelled=mock.Mock()),
            )

        dialog_factory.assert_called_once_with(
            format_labels=[("wav", "WAV (lossless forensic copy)")],
            fixed_recipient_label="SoundCloud",
            share_label_caption="SoundCloud Label",
            share_label_placeholder="Optional upload, campaign, or release label",
            parent=app,
        )
        request = export_service.export.call_args.args[0]
        self.assertEqual(request.recipient_label, "SoundCloud")
        self.assertIn("label=Premiere", request.share_label)

    def test_inspect_forensic_watermark_warns_when_service_missing(self):
        app = SimpleNamespace(forensic_export_service=None)
        with mock.patch("isrc_manager.forensics.controller._message_box") as message_box:
            box = mock.Mock()
            message_box.return_value = box
            inspect_forensic_watermark(app)
            box.warning.assert_called_once_with(
                app,
                "Inspect Forensic Watermark",
                "Open a profile with forensic export services available first.",
            )

    def test_inspect_forensic_watermark_aborts_when_file_not_selected(self):
        app = SimpleNamespace(forensic_export_service=mock.Mock())
        with mock.patch(
            "isrc_manager.forensics.controller._file_dialog",
            return_value=mock.Mock(getOpenFileName=mock.Mock(return_value=("", ""))),
        ):
            inspect_forensic_watermark(app)

    def test_inspect_forensic_watermark_success_invokes_dialog_when_available(self):
        app = SimpleNamespace(
            forensic_export_service=mock.Mock(),
            _log_event=mock.Mock(),
            _submit_background_bundle_task=mock.Mock(),
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _show_background_task_error=mock.Mock(),
        )
        file_dialog = mock.Mock(getOpenFileName=mock.Mock(return_value=("/tmp/audio.wav", "")))
        inspection_dialog_instance = mock.Mock(exec=mock.Mock())
        inspection_dialog_factory = mock.Mock(return_value=inspection_dialog_instance)

        with (
            mock.patch("isrc_manager.forensics.controller._file_dialog", return_value=file_dialog),
            mock.patch(
                "isrc_manager.forensics.controller._root_attr",
                side_effect=lambda name, fallback: (
                    inspection_dialog_factory if name == "ForensicInspectionDialog" else fallback
                ),
            ),
        ):
            inspect_forensic_watermark(app)
            on_success = app._submit_background_bundle_task.call_args.kwargs["on_success"]
            task_fn = app._submit_background_bundle_task.call_args.kwargs["task_fn"]
            export_service = mock.Mock()
            ctx = SimpleNamespace(
                report_progress=mock.Mock(),
                is_cancelled=mock.Mock(return_value=False),
            )
            task_fn(SimpleNamespace(forensic_export_service=export_service), ctx)
            export_service.inspect_file.assert_called_once()
            progress_callback = export_service.inspect_file.call_args.kwargs["progress_callback"]
            progress_callback(1, 2, "half")
            ctx.report_progress.assert_called_once_with(value=1, maximum=2, message="half")
            on_success(
                ForensicInspectionReport(
                    status="found", message="ok", inspected_path="/tmp/audio.wav"
                )
            )

        app._submit_background_bundle_task.assert_called_once_with(
            title="Inspect Forensic Watermark",
            description=(
                "Inspecting the selected audio file, attempting forensic token extraction, and resolving any matches against the export ledger..."
            ),
            task_fn=mock.ANY,
            kind="read",
            unique_key="forensics.inspect_audio",
            cancellable=True,
            on_error=mock.ANY,
            on_cancelled=mock.ANY,
            on_success=mock.ANY,
        )
        inspection_dialog_factory.assert_called_once_with(
            report=ForensicInspectionReport(
                status="found", message="ok", inspected_path="/tmp/audio.wav"
            ),
            parent=app,
        )
        inspection_dialog_instance.exec.assert_called_once_with()

    def test_inspect_forensic_watermark_falls_back_to_message_box_when_dialog_absent(self):
        app = SimpleNamespace(
            forensic_export_service=mock.Mock(),
            _log_event=mock.Mock(),
            _submit_background_bundle_task=mock.Mock(),
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _show_background_task_error=mock.Mock(),
        )
        file_dialog = mock.Mock(getOpenFileName=mock.Mock(return_value=("/tmp/audio.wav", "")))
        info_box = mock.Mock()

        with (
            mock.patch("isrc_manager.forensics.controller.ForensicInspectionDialog", None),
            mock.patch("isrc_manager.forensics.controller._file_dialog", return_value=file_dialog),
            mock.patch("isrc_manager.forensics.controller._message_box", return_value=info_box),
        ):
            inspect_forensic_watermark(app)
            on_success = app._submit_background_bundle_task.call_args.kwargs["on_success"]
            report = ForensicInspectionReport(
                status="found", message="ok", inspected_path="/tmp/audio.wav"
            )
            on_success(report)

        app._submit_background_bundle_task.assert_called_once()
        info_box.information.assert_called_once_with(
            app,
            "Inspect Forensic Watermark",
            "ok\n\nStatus: found\nPath: /tmp/audio.wav",
        )
