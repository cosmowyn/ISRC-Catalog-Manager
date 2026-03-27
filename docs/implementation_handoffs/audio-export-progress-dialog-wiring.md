# Audio Export Progress Dialog Wiring

## 1. Previous audio export execution / progress path

- Managed derivative export, forensic watermark export, external conversion, catalog audio copies, authentic masters, and provenance copies already used the shared background-task manager.
- Those workflows were running in worker threads, but some service layers still emitted terminal "finished" messages before the app-level lifecycle had truly finished.
- Plain stored-audio export paths from the table and file export helpers were still synchronous for audio:
  - single track `audio_file` export
  - bulk focused-column `audio_file` export
  - single custom `blob_audio` export
- Those direct audio exports did not show the managed loading dialog and did not participate in the shared task/progress lifecycle.

## 2. Why it was not properly wired into the loading dialog system

- The app had one managed export family and one silent direct-export branch for stored audio files.
- Some managed services still emitted final "finished" progress messages inside the worker payload, even though app-level result recording and completion handling still followed afterward.
- That made the progress contract less truthful than the rest of the task manager design, where terminal completion is supposed to be owned by the managed task lifecycle.

## 3. Worker-thread / task integration changes made

- Kept the existing `BackgroundTaskManager`, `BackgroundTaskContext`, and `_submit_background_(bundle_)task(...)` infrastructure.
- Routed direct stored-audio exports through `_submit_background_bundle_task(...)` instead of synchronous UI-thread writes.
- Added managed worker-driven export handling for:
  - single track `audio_file` export
  - single custom `blob_audio` export
  - bulk focused-column audio export for `audio_file`
  - bulk focused-column audio export for `blob_audio`
- Kept non-audio file export behavior unchanged.
- Preserved history capture by running file writes through `run_file_history_action(...)` inside the worker.

## 4. Real export stages now reported

- Managed derivatives now report real stages without an early final "finished" message:
  - resolve source audio
  - convert derivative
  - apply direct watermark when applicable
  - write catalog metadata
  - hash finalized derivative
  - register derivative
  - stage finalized derivative
  - finalize managed derivative delivery
- External conversion now reports:
  - convert external audio
  - finalize converted output
- Catalog audio copies report:
  - prepare exported audio copy inputs
  - resolve export source
  - copy audio
  - write catalog metadata or finalize copy
- Authentic masters report:
  - prepare export plan
  - prepare authenticity manifest
  - embed direct watermark
  - write catalog metadata
  - sign authenticity sidecar
- Provenance copies report:
  - prepare provenance plan
  - resolve provenance source
  - copy provenance audio
  - write catalog metadata
  - sign provenance sidecar
- Forensic exports report:
  - resolve source
  - convert
  - prepare metadata/token state
  - apply forensic watermark
  - hash final output
  - register derivative
  - register forensic export
  - finalize filename
  - finalize delivery or package ZIP
- Direct stored-audio exports now report worker-owned stages such as:
  - load source audio
  - write exported audio
  - write catalog metadata when applicable
  - record export history or finalize exported audio

## 5. How truthful completion is enforced

- Service layers no longer emit premature terminal "finished" progress for managed derivatives, external conversion, authentic masters, or provenance exports.
- Managed export dialogs reserve terminal completion for the app-managed task lifecycle.
- Direct stored-audio exports now only emit `100%` through the managed task wrapper after the worker has completed file write, metadata write, and history capture.
- Success dialogs now remain post-cleanup UI, not hidden long-running work after nominal completion.
- The last worker-owned service progress update remains below terminal completion where the app still owns final task lifecycle steps.

## 6. Files changed

- `ISRC_manager.py`
- `isrc_manager/authenticity/service.py`
- `isrc_manager/media/derivatives.py`
- `isrc_manager/tags/service.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/test_audio_conversion_pipeline.py`
- `tests/test_authenticity_verification_service.py`
- `tests/test_forensic_watermark_service.py`
- `tests/test_tag_service.py`

## 7. Tests added / updated

- App-shell regression coverage now checks that:
  - catalog audio copy export uses managed preview/export task callbacks
  - direct single-file audio export uses the background bundle task path
  - bulk focused-column audio export uses the background bundle task path
- Service progress tests now verify real staged progress and non-terminal last worker progress for:
  - tagged catalog audio copies
  - managed derivatives
  - external conversion
  - authentic masters
  - provenance copies
  - forensic exports
- Validation run:
  - `python3 -m unittest tests.app.test_app_shell_editor_surfaces tests.test_tag_service tests.test_audio_conversion_pipeline tests.test_authenticity_verification_service tests.test_forensic_watermark_service`
  - `python3 -m black --check ISRC_manager.py isrc_manager/authenticity/service.py isrc_manager/media/derivatives.py isrc_manager/tags/service.py tests/app/_app_shell_support.py tests/app/test_app_shell_editor_surfaces.py tests/test_audio_conversion_pipeline.py tests/test_authenticity_verification_service.py tests/test_forensic_watermark_service.py tests/test_tag_service.py`

## 8. Remaining limitations / next bottlenecks

- Managed derivative, forensic, and authenticity workflows still reserve `97..100` for app-level result recording and audit finalization; that is intentional and now truthful, but it means the service layer itself does not own the terminal completion step.
- Audio conversion duration is still fundamentally bounded by codec/transcode cost; this pass improves truthfulness and responsiveness, not raw encode speed.
- If future export variants introduce new packaging or signing stages, their progress models should be extended in the same service-level staged pattern instead of reintroducing generic "finished" callbacks.

## 9. Current product statement

Audio export now runs through a truthful managed loading/progress lifecycle: worker-thread execution is used for the dedicated export workflows and the direct stored-audio export paths, progress messages map to real work being performed, and terminal completion is only shown after the actual export lifecycle has finished.
