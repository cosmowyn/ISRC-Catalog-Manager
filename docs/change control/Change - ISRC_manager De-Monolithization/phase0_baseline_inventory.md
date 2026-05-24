# Plan 1 Phase 0 Baseline Inventory

Timestamp: 2026-05-24 21:08:14 CEST

This baseline records the live repository state used for the Plan 1 packaging and compatibility gate.
It reflects the current working tree, including the already-applied Plan 1 Phase 1 logging/helper
extraction that was reconciled during Phase 0.

## Package Parity

- `pyproject.toml` package entries: 25
- tracked `isrc_manager/**/__init__.py` package directories: 25
- missing package entries: none
- listed packages without `__init__.py`: none
- Phase 0 package addition: `isrc_manager.tracks`

## Top-Level `ISRC_manager.py` Classes And Functions

- `__getattr__`
- `_install_qt_message_filter`
- `ApplicationSettingsDialog`
- `_ManageArtistsDialog`
- `_ManageAlbumsDialog`
- `LicenseUploadDialog`
- `LicensesBrowserPanel`
- `LicensesBrowserDialog`
- `LicenseeManagerDialog`
- `_CatalogManagerPaneBase`
- `_CatalogArtistsPane`
- `_CatalogAlbumsPane`
- `DiagnosticsCatalogCleanupPanel`
- `_CatalogLicenseesPane`
- `CatalogManagersPanel`
- `CatalogManagersDialog`
- `_AlbumTrackOrderingTable`
- `AlbumTrackOrderingDialog`
- `App`
- `_AlbumTrackSection`
- `AlbumEntryDialog`
- `EditDialog`
- `_ImagePreviewDialog`
- `_HiDpiArtworkLabel`
- `_AudioPreviewPreloadBridge`
- `_AudioPreviewPreloadCancelled`
- `_AudioPreviewPreparedMedia`
- `_AudioPreviewPreloadTask`
- `_AudioPreviewPreloadResult`
- `_AudioPreviewTrackLoadTask`
- `_AudioPreviewTrackLoadResult`
- `_audio_preview_detect_mime_from_bytes`
- `_audio_preview_suffix_for_mime`
- `_audio_preview_fetch_source_for_preload`
- `_audio_preview_write_preload_temp_file`
- `_audio_preview_artwork_payload_for_snapshot`
- `_audio_preview_track_queue_items_for_service`
- `_audio_preview_state_for_preload_task`
- `_build_audio_preview_preload`
- `_build_audio_preview_track_load`
- `_AudioPreviewDialog`
- `StereoPeakMeterWidget`
- `WaveformWidget`
- `SpectrumGraphWidget`
- `load_wav_peaks`
- `load_audio_harmonic_frames`
- `load_audio_peak_meter_frames`
- `load_audio_spectrum_frames`
- `main`

## Current Root `ISRC_manager` Test Imports

- `tests/test_history_budget_hooks.py`
- `tests/test_qss_autocomplete.py`
- `tests/test_shortcut_ordering.py`
- `tests/test_update_ui_integration.py`
- `tests/test_app_bootstrap.py`
- `tests/test_migration_integration.py`
- `tests/test_theme_builder.py`
- `tests/app/_app_shell_support.py`

## Compatibility Inventory Status

`compatibility_inventory.md` exists with the required schema and currently contains the active Phase 1
root compatibility entries for logging and prompt helper aliases.
