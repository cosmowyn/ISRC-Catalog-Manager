import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isrc_manager.forensics.controller import (
    _root_attr,
    export_forensic_watermarked_audio,
    inspect_forensic_watermark,
)
from isrc_manager.forensics.models import ForensicInspectionReport


class ForensicsControllerTests(unittest.TestCase):
    def test_root_attr_falls_back_when_main_window_missing(self):
        self.assertIs(_root_attr("MissingName", mock.sentinel.fallback), mock.sentinel.fallback)

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
            statusBar=mock.Mock(return_value=mock.Mock(showMessage=mock.Mock())),
            _current_profile_name=mock.Mock(return_value="Profile"),
        )
        file_dialog = mock.Mock(getExistingDirectory=mock.Mock(return_value="/tmp/out"))

        with (
            mock.patch("isrc_manager.forensics.controller.ForensicExportDialog", None),
            mock.patch("isrc_manager.forensics.controller._file_dialog", return_value=file_dialog),
            mock.patch("isrc_manager.forensics.controller._message_box", return_value=mock.Mock()),
        ):
            export_forensic_watermarked_audio(app)

        app._prompt_audio_conversion_format.assert_called_once_with(
            title="Export Forensic Watermarked Audio",
            prompt=(
                "Choose the lossy forensic delivery output format. "
                "These exports are recipient-specific leak-tracing copies, not signed authenticity masters."
            ),
            capability_group="managed_forensic",
        )

        app._submit_background_bundle_task.assert_called_once_with(
            title="Export Forensic Watermarked Audio",
            description=(
                "Converting selected catalog audio into lossy delivery copies, writing tags, embedding recipient-specific forensic watermarks, hashing final files, and registering forensic export lineage..."
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
