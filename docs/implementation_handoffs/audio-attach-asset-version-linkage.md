# Audio Attach -> Asset Version Linkage

## Audit Of The Existing Gap

- The repository already had a real asset/version model in `isrc_manager/assets/service.py` and `isrc_manager/assets/models.py`.
- The repository already had a shared track-audio attachment seam in `isrc_manager/services/tracks.py`.
- That seam was reused by:
  - Add Track with audio
  - track updates with audio replacements
  - manual audio attach
  - drag-and-drop audio attach
  - package/import flows that create audio-backed tracks through `TrackService`
- Before this pass, successful Track audio attachment did **not** automatically create or update `AssetVersions`.
- Resulting gap:
  - a Track could have a real attached audio file
  - while the Asset / Asset Version system still had no corresponding primary master record

## Final Wiring

- `TrackService` now synchronizes the asset layer after successful real audio attachment and after audio storage-mode conversion.
- The synchronization is centralized, not duplicated in UI entrypoints.
- The bridge lives on the existing attachment seam, so all current audio attach paths inherit it automatically.

## Final Behavior

### First Real Audio Attachment

- If a Track receives its first real audio file and no master asset chain exists yet:
  - create a primary asset version automatically
  - default the asset type to `main_master`
  - mark it primary
  - mark it approved for use
  - persist the same storage mode as the attached track media

### Replacing Attached Audio With A Different File

- If the Track already has a primary master asset and the attached audio file identity changes:
  - create a new asset version
  - link it with `derived_from_asset_id`
  - promote the new version to primary
  - demote the previous primary version

### Reattaching The Same File / Storage-Mode Changes

- If the attached file identity is unchanged and only the stored representation changes:
  - update the current primary asset in place
  - do not create a redundant new version row

## Covered Entry Points

- Add Track with audio
- manual audio attach
- reviewed bulk audio attach
- drag-and-drop audio attach
- imports that create or attach real track audio through `TrackService`
- audio storage-mode conversion when file identity remains the same

## Safety Rules Preserved

- No asset records are created before track audio attach succeeds.
- No asset records are created for tracks without real audio media.
- No second manual asset workflow was introduced.
- Work / Track / Asset concepts remain separate.

## Tests Added Or Updated

- `tests/test_track_service.py`
  - asset creation on first real audio attach
  - asset versioning on file replacement
  - in-place asset update on storage-mode conversion
- `tests/test_governed_track_creation_service.py`
  - governed Add Track with audio creates a primary asset version
- `tests/exchange/_support.py`
  - imported audio-backed tracks are reflected in the asset layer
- `tests/app/_app_shell_support.py`
  - reviewed app-shell audio attach produces a primary asset version
- `tests/app/test_app_shell_editor_surfaces.py`
  - wrapper coverage for the app-shell asset reflection path

## Caveats

- This pass enforces the attachment-side invariant.
- It does not introduce automatic asset pruning when track audio is later cleared unless an existing path already handles that separately.

## Final Invariant

If a Track has an attached real audio file, the Asset / Asset Version system must reflect it automatically.
