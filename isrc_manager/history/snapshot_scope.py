"""Action-pair scoping and integrity checks for external snapshot state."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .snapshot_replay import SnapshotConnectionError, SnapshotTableDelta


@dataclass(frozen=True, slots=True)
class SnapshotReplayScope:
    """State changed by one before/after snapshot action."""

    table_deltas: tuple[SnapshotTableDelta, ...]
    setting_keys: frozenset[str]
    managed_files: tuple[tuple[str, tuple[str, ...]], ...]
    before_db_snapshot_path: str
    after_db_snapshot_path: str
    before_settings_state: Mapping[str, object]
    after_settings_state: Mapping[str, object]
    before_manifest: Mapping[str, object]
    after_manifest: Mapping[str, object]


def changed_setting_keys(
    before: Mapping[str, object], after: Mapping[str, object]
) -> frozenset[str]:
    """Return settings keys whose serialized values differ between snapshots."""

    return frozenset(
        key
        for key in set(before) | set(after)
        if not _strict_state_equal(
            before.get(key, _MISSING),
            after.get(key, _MISSING),
        )
    )


def validate_setting_values_match(
    current: Mapping[str, object],
    expected: Mapping[str, object],
    setting_keys: Iterable[str],
) -> None:
    """Fail when an action-owned setting no longer matches its expected state."""

    for key in setting_keys:
        if not _strict_state_equal(
            current.get(key, _MISSING),
            expected.get(key, _MISSING),
        ):
            raise SnapshotConnectionError(
                "Cannot replay history because an action-owned setting changed after "
                f"the action was recorded: {key}"
            )


def capture_managed_file_inventory(root: Path) -> dict[str, dict[str, object]]:
    """Capture a stable size and SHA-256 inventory for one managed directory."""

    return {
        relative_path: {"size_bytes": signature[0], "sha256": signature[1]}
        for relative_path, signature in _managed_tree_signatures(root).items()
    }


def changed_managed_files(
    before_manifest: Mapping[str, object],
    after_manifest: Mapping[str, object],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return per-directory file paths changed by an action snapshot pair."""

    before_directories = _managed_directories(before_manifest)
    after_directories = _managed_directories(after_manifest)
    changes: list[tuple[str, tuple[str, ...]]] = []
    for directory_name in sorted(set(before_directories) | set(after_directories)):
        before_state = before_directories.get(directory_name, {})
        after_state = after_directories.get(directory_name, {})
        before_files = _recorded_file_signatures(before_state)
        after_files = _recorded_file_signatures(after_state)
        if before_files is None or after_files is None:
            before_actual = _managed_file_signatures(before_state)
            after_actual = _managed_file_signatures(after_state)
            if (
                bool(before_state.get("exists")) != bool(after_state.get("exists"))
                or before_actual != after_actual
            ):
                raise SnapshotConnectionError(
                    "Cannot safely replay legacy managed-file history without a recorded "
                    f"file inventory: {directory_name}"
                )
            continue
        changed_paths = tuple(
            sorted(
                relative_path
                for relative_path in set(before_files) | set(after_files)
                if before_files.get(relative_path) != after_files.get(relative_path)
            )
        )
        before_exists = bool(before_state.get("exists"))
        after_exists = bool(after_state.get("exists"))
        if changed_paths or before_exists != after_exists:
            changes.append((directory_name, changed_paths))
    return tuple(changes)


def validate_managed_snapshot_artifacts(
    manifest: Mapping[str, object],
    managed_files: Iterable[tuple[str, Iterable[str]]],
) -> None:
    """Verify target snapshot files against their capture-time inventory."""

    directories = _managed_directories(manifest)
    for directory_name, relative_paths in managed_files:
        state = directories.get(directory_name, {})
        inventory = _require_recorded_file_signatures(state, directory_name)
        source_root = _managed_snapshot_root(state)
        if state.get("exists"):
            if source_root is None:
                raise SnapshotConnectionError(
                    f"Managed history snapshot root is missing: {directory_name}"
                )
            _validate_root(source_root)
        scoped_paths = tuple(_safe_relative_path(path) for path in relative_paths)
        for clean_relative_path in scoped_paths:
            _validate_inventory_path_signature(
                source_root,
                clean_relative_path,
                inventory,
                alias_paths=scoped_paths,
                context="managed history artifact",
            )


def validate_complete_managed_snapshot(
    manifest: Mapping[str, object],
    *,
    allowed_directory_names: Iterable[str] | None = None,
    snapshot_assets_root: Path | None = None,
) -> None:
    """Verify a full managed snapshot before a non-scoped restore or clone."""

    if (allowed_directory_names is None) != (snapshot_assets_root is None):
        raise SnapshotConnectionError(
            "Managed history validation requires both its allowlist and assets root."
        )
    if allowed_directory_names is not None and snapshot_assets_root is not None:
        validate_managed_manifest_layout(
            manifest,
            allowed_directory_names=allowed_directory_names,
            snapshot_assets_root=snapshot_assets_root,
        )

    for directory_name, state in _managed_directories(manifest).items():
        root = _managed_snapshot_root(state)
        if state.get("exists"):
            if root is None or not root.exists():
                raise FileNotFoundError(root or directory_name)
            _validate_root(root)
        recorded = _recorded_file_signatures(state)
        actual = _managed_file_signatures(state)
        if recorded is None:
            if actual:
                raise SnapshotConnectionError(
                    "Cannot safely restore legacy managed-file history without a recorded "
                    f"file inventory: {directory_name}"
                )
            continue
        if actual != recorded:
            raise SnapshotConnectionError(
                f"Managed history snapshot failed its integrity check: {directory_name}"
            )


def validate_managed_manifest_layout(
    manifest: Mapping[str, object],
    *,
    allowed_directory_names: Iterable[str],
    snapshot_assets_root: Path,
) -> None:
    """Require fixed directory names and capture-owned snapshot source paths."""

    raw_directories = manifest.get("managed_directories", {})
    if not isinstance(raw_directories, Mapping):
        raise SnapshotConnectionError("Managed history manifest is malformed.")
    allowed_names = frozenset(str(name) for name in allowed_directory_names)
    assets_root = snapshot_assets_root.absolute()
    if assets_root.is_symlink():
        raise SnapshotConnectionError(
            f"Managed history assets root is a symbolic link: {assets_root}"
        )
    if assets_root.exists() and not assets_root.is_dir():
        raise SnapshotConnectionError(
            f"Managed history assets root is not a directory: {assets_root}"
        )
    for raw_name, raw_state in raw_directories.items():
        directory_name = str(raw_name)
        if directory_name not in allowed_names:
            raise SnapshotConnectionError(
                f"Managed history manifest contains an unsupported directory: {directory_name}"
            )
        if not isinstance(raw_state, Mapping):
            raise SnapshotConnectionError("Managed history directory metadata is malformed.")
        expected_path = (assets_root / directory_name).absolute()
        raw_snapshot_path = str(raw_state.get("snapshot_path") or "").strip()
        if not raw_state.get("exists"):
            if raw_snapshot_path:
                raise SnapshotConnectionError(
                    f"Missing managed history directory has a snapshot path: {directory_name}"
                )
            continue
        if not raw_snapshot_path:
            raise SnapshotConnectionError(
                f"Managed history snapshot root is missing: {directory_name}"
            )
        snapshot_path = Path(raw_snapshot_path).absolute()
        if snapshot_path != expected_path:
            raise SnapshotConnectionError(
                f"Managed history snapshot path is outside its recorded assets root: {directory_name}"
            )
        _validate_root_path_chain(snapshot_path, stop=assets_root)
        _validate_root(snapshot_path)


def validate_history_artifact_path(
    path: str | Path,
    *,
    lexical_root: str | Path,
    require_file: bool,
    direct_child: bool = False,
) -> Path:
    """Validate a lexical history path without following symbolic-link escapes."""

    candidate = Path(path).absolute()
    root = Path(lexical_root).absolute()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SnapshotConnectionError(
            "History artifact path is outside its application-owned directory."
        ) from exc
    if direct_child and candidate.parent != root:
        raise SnapshotConnectionError(
            "History artifact path is not a direct child of its application-owned directory."
        )
    _validate_root_path_chain(candidate, stop=root)
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise SnapshotConnectionError(f"History artifact root is not a regular directory: {root}")
    if require_file and (candidate.is_symlink() or not candidate.is_file()):
        raise SnapshotConnectionError(
            f"History artifact is missing or not a regular file: {candidate}"
        )
    return candidate


def validate_managed_files_match(
    managed_root: Path,
    expected_manifest: Mapping[str, object],
    managed_files: Iterable[tuple[str, Iterable[str]]],
) -> None:
    """Fail when an action-owned live path no longer matches the expected snapshot."""

    directories = _managed_directories(expected_manifest)
    for directory_name, relative_paths in managed_files:
        clean_directory_name = _safe_relative_path(directory_name)
        live_directory = _contained_path(managed_root, clean_directory_name)
        state = directories.get(directory_name, {})
        inventory = _require_recorded_file_signatures(state, directory_name)
        if live_directory.is_symlink():
            raise SnapshotConnectionError(
                f"Managed history path contains a symbolic link: {live_directory}"
            )
        if live_directory.exists() and not live_directory.is_dir():
            raise SnapshotConnectionError(
                f"Managed history directory is not a regular directory: {live_directory}"
            )
        if state.get("exists") and not live_directory.is_dir():
            raise SnapshotConnectionError(
                "Cannot replay history because an action-owned managed directory changed "
                f"after the action was recorded: {directory_name}"
            )
        scoped_paths = tuple(_safe_relative_path(path) for path in relative_paths)
        for clean_relative_path in scoped_paths:
            try:
                _validate_inventory_path_signature(
                    live_directory,
                    clean_relative_path,
                    inventory,
                    alias_paths=scoped_paths,
                    context="live managed file",
                )
            except SnapshotConnectionError as exc:
                raise SnapshotConnectionError(
                    "Cannot replay history because an action-owned managed file changed "
                    f"after the action was recorded: "
                    f"{directory_name}/{clean_relative_path.as_posix()}"
                ) from exc


def restore_managed_files(
    managed_root: Path,
    target_manifest: Mapping[str, object],
    managed_files: Iterable[tuple[str, Iterable[str]]],
) -> None:
    """Restore only files changed by one action, preserving later unrelated files."""

    managed_file_scope = tuple(
        (str(directory_name), tuple(str(path) for path in relative_paths))
        for directory_name, relative_paths in managed_files
    )
    validate_managed_snapshot_artifacts(target_manifest, managed_file_scope)
    validate_managed_root(managed_root)
    managed_root.mkdir(parents=True, exist_ok=True)
    validate_managed_root(managed_root)
    target_directories = _managed_directories(target_manifest)
    for directory_name, relative_paths in managed_file_scope:
        clean_directory_name = _safe_relative_path(directory_name)
        live_directory = _contained_path(managed_root, clean_directory_name)
        state = target_directories.get(directory_name, {})
        inventory = _require_recorded_file_signatures(state, directory_name)
        source_root = _managed_snapshot_root(state)
        if state.get("exists"):
            if live_directory.exists() and not live_directory.is_dir():
                raise SnapshotConnectionError(
                    f"Cannot restore managed history directory over a file: {live_directory}"
                )
            live_directory.mkdir(parents=True, exist_ok=True)
        restore_items = []
        for relative_path in relative_paths:
            clean_relative_path = _safe_relative_path(relative_path)
            live_path = _contained_path(live_directory, clean_relative_path)
            signature = inventory.get(clean_relative_path.as_posix())
            source_path = (
                _contained_path(source_root, clean_relative_path)
                if source_root is not None
                else None
            )
            restore_items.append((live_path, source_path, signature))

        # Remove target-absent spellings before copies. On a case-insensitive
        # filesystem, both spellings of a case-only rename address one file.
        for live_path, _source_path, signature in restore_items:
            if signature is not None:
                continue
            if live_path.is_file() or live_path.is_symlink():
                live_path.unlink()
                _prune_empty_parents(live_path.parent, stop=live_directory)

        for live_path, source_path, signature in restore_items:
            if signature is None:
                continue
            assert source_path is not None
            if live_path.is_dir():
                raise SnapshotConnectionError(
                    f"Cannot restore managed history file over a directory: {live_path}"
                )
            live_path.parent.mkdir(parents=True, exist_ok=True)
            if live_path.exists() or live_path.is_symlink():
                live_path.unlink()
            shutil.copy2(source_path, live_path)
        if not state.get("exists"):
            try:
                live_directory.rmdir()
            except OSError:
                pass


def validate_managed_tree(root: Path) -> None:
    """Reject symbolic links before managed history trees are copied or hashed."""

    _validate_root(root)
    for path in root.rglob("*"):
        if path.is_symlink():
            raise SnapshotConnectionError(f"Managed history tree contains a symbolic link: {path}")


def validate_managed_root(root: Path) -> None:
    """Reject a configured managed root that redirects through a symbolic link."""

    if root.is_symlink():
        raise SnapshotConnectionError(f"Managed history root is a symbolic link: {root}")
    if root.exists() and not root.is_dir():
        raise SnapshotConnectionError(f"Managed history root is not a regular directory: {root}")


def file_content_signature(path: Path) -> tuple[int, str]:
    """Return a regular file's size and SHA-256 digest."""

    if path.is_symlink() or not path.is_file():
        raise SnapshotConnectionError(f"History artifact is not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return path.stat().st_size, digest.hexdigest()


def validate_file_state_artifacts(state: Mapping[str, object]) -> None:
    """Verify explicit file-effect artifacts before any live file is changed."""

    artifacts = _file_state_artifacts_by_suffix(state)
    if bool(state.get("exists")) != bool(artifacts):
        raise SnapshotConnectionError("History file state metadata is inconsistent.")
    raw_files = state.get("files", [])
    if not isinstance(raw_files, list):
        raise SnapshotConnectionError("History file artifact metadata is malformed.")
    for file_info in raw_files:
        if not isinstance(file_info, Mapping):
            raise SnapshotConnectionError("History file artifact metadata is malformed.")
        suffix = str(file_info.get("suffix", ""))
        artifact = artifacts[suffix]
        actual_size, actual_digest = file_content_signature(artifact)
        recorded_size = file_info.get("size_bytes")
        recorded_digest = file_info.get("sha256")
        try:
            size_matches = recorded_size is None or int(recorded_size) == actual_size
        except TypeError, ValueError:
            size_matches = False
        digest_matches = recorded_digest is None or str(recorded_digest).lower() == actual_digest
        if not size_matches or not digest_matches:
            raise SnapshotConnectionError(
                f"History file artifact failed its integrity check: {artifact}"
            )


def validate_live_file_state(
    target_path: str | Path,
    expected_state: Mapping[str, object],
) -> None:
    """Fail when an explicit action-owned file no longer matches recorded state."""

    validate_file_state_artifacts(expected_state)
    expected_files = _file_state_artifacts_by_suffix(expected_state)
    raw_suffixes = expected_state.get("companion_suffixes", [])
    if not isinstance(raw_suffixes, list):
        raise SnapshotConnectionError("History file companion metadata is malformed.")
    suffixes = {str(suffix) for suffix in raw_suffixes} | set(expected_files)
    suffixes.add("")
    target = Path(target_path)
    for suffix in sorted(suffixes):
        live_path = Path(f"{target}{suffix}") if suffix else target
        expected_artifact = expected_files.get(suffix)
        if expected_artifact is None:
            if live_path.exists() or live_path.is_symlink():
                raise SnapshotConnectionError(
                    "Cannot replay history because an action-owned file changed after "
                    f"the action was recorded: {live_path}"
                )
            continue
        if live_path.is_symlink() or not live_path.is_file():
            raise SnapshotConnectionError(
                "Cannot replay history because an action-owned file changed after "
                f"the action was recorded: {live_path}"
            )
        if file_content_signature(live_path) != file_content_signature(expected_artifact):
            raise SnapshotConnectionError(
                "Cannot replay history because an action-owned file changed after "
                f"the action was recorded: {live_path}"
            )


def validate_snapshot_file_effects(
    payload: Mapping[str, object] | None,
    *,
    direction: str,
) -> None:
    """Preflight every explicit file effect for one snapshot replay direction."""

    if not payload:
        return
    raw_effects = payload.get("file_effects", [])
    if not isinstance(raw_effects, list):
        raise SnapshotConnectionError("History file effects metadata is malformed.")
    for effect in raw_effects:
        if not isinstance(effect, Mapping):
            raise SnapshotConnectionError("History file effect metadata is malformed.")
        target_path = str(effect.get("target_path") or "").strip()
        if not target_path:
            continue
        desired_state = (
            effect.get("before_state") if direction == "undo" else effect.get("after_state")
        )
        if desired_state is None:
            continue
        expected_state = (
            effect.get("after_state") if direction == "undo" else effect.get("before_state")
        )
        if not isinstance(expected_state, Mapping):
            raise SnapshotConnectionError(
                "Cannot safely replay a file effect without its expected current state."
            )
        if not isinstance(desired_state, Mapping):
            raise SnapshotConnectionError("History file effect state is malformed.")
        validate_file_state_artifacts(desired_state)
        validate_live_file_state(target_path, expected_state)


_MISSING = object()


def _strict_state_equal(left: object, right: object) -> bool:
    """Compare serialized setting state without bool/int/float coercion."""

    if left is _MISSING or right is _MISSING:
        return left is right
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            return False
        return all(_strict_state_equal(left[key], right[key]) for key in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            _strict_state_equal(left_value, right_value)
            for left_value, right_value in zip(left, right, strict=True)
        )
    return bool(left == right)


def _managed_directories(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    value = manifest.get("managed_directories", {})
    if not isinstance(value, Mapping):
        return {}
    return {str(name): state for name, state in value.items() if isinstance(state, Mapping)}


def _managed_snapshot_root(state: Mapping[str, object]) -> Path | None:
    if not state.get("exists"):
        return None
    value = str(state.get("snapshot_path") or "").strip()
    return Path(value) if value else None


def _managed_file_signatures(state: Mapping[str, object]) -> dict[str, tuple[int, str]]:
    root = _managed_snapshot_root(state)
    if root is None or not root.exists():
        return {}
    return _managed_tree_signatures(root)


def _managed_tree_signatures(root: Path) -> dict[str, tuple[int, str]]:
    validate_managed_tree(root)
    return {
        path.relative_to(root).as_posix(): file_content_signature(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _recorded_file_signatures(
    state: Mapping[str, object],
) -> dict[str, tuple[int, str]] | None:
    if "file_inventory" not in state:
        return None
    raw_inventory = state.get("file_inventory")
    if not isinstance(raw_inventory, Mapping):
        raise SnapshotConnectionError("Managed history file inventory is malformed.")
    inventory: dict[str, tuple[int, str]] = {}
    for raw_path, raw_signature in raw_inventory.items():
        clean_path = _safe_relative_path(str(raw_path)).as_posix()
        if not isinstance(raw_signature, Mapping):
            raise SnapshotConnectionError("Managed history file inventory is malformed.")
        try:
            size_bytes = int(raw_signature["size_bytes"])
            digest = str(raw_signature["sha256"]).lower()
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotConnectionError("Managed history file inventory is malformed.") from exc
        if (
            size_bytes < 0
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise SnapshotConnectionError("Managed history file inventory is malformed.")
        inventory[clean_path] = (size_bytes, digest)
    if not state.get("exists") and inventory:
        raise SnapshotConnectionError(
            "Managed history inventory contains files for a missing directory."
        )
    return inventory


def _require_recorded_file_signatures(
    state: Mapping[str, object], directory_name: str
) -> dict[str, tuple[int, str]]:
    inventory = _recorded_file_signatures(state)
    if inventory is None:
        raise SnapshotConnectionError(
            "Cannot safely replay legacy managed-file history without a recorded "
            f"file inventory: {directory_name}"
        )
    return inventory


def _validate_path_signature(
    path: Path | None,
    expected: tuple[int, str] | None,
    *,
    context: str,
) -> None:
    if expected is None:
        if path is not None and (path.exists() or path.is_symlink()):
            raise SnapshotConnectionError(f"Unexpected {context}: {path}")
        return
    if path is None:
        raise SnapshotConnectionError(f"Missing {context}.")
    actual = file_content_signature(path)
    if actual != expected:
        raise SnapshotConnectionError(f"{context.capitalize()} failed its integrity check: {path}")


def _validate_inventory_path_signature(
    root: Path | None,
    relative_path: Path,
    inventory: Mapping[str, tuple[int, str]],
    *,
    alias_paths: Iterable[Path],
    context: str,
) -> None:
    path = _contained_path(root, relative_path) if root is not None else None
    expected = inventory.get(relative_path.as_posix())
    if (
        expected is not None
        and root is not None
        and path is not None
        and path.exists()
        and not _path_has_exact_spelling(root, relative_path)
    ):
        raise SnapshotConnectionError(f"Unexpected {context} path spelling: {path}")
    if (
        expected is None
        and path is not None
        and root is not None
        and _aliases_recorded_path_spelling(
            path,
            root,
            relative_path,
            inventory,
            alias_paths,
        )
    ):
        return
    _validate_path_signature(path, expected, context=context)


def _aliases_recorded_path_spelling(
    path: Path,
    root: Path,
    relative_path: Path,
    inventory: Mapping[str, tuple[int, str]],
    alias_paths: Iterable[Path],
) -> bool:
    """Recognize one on-disk entry addressed through alternate path casing."""

    if not path.exists() or _path_has_exact_spelling(root, relative_path):
        return False
    scoped_path_names = {path.as_posix() for path in alias_paths}
    for recorded_path in inventory:
        if recorded_path not in scoped_path_names:
            continue
        recorded_relative = _safe_relative_path(recorded_path)
        if not _path_has_exact_spelling(root, recorded_relative):
            continue
        candidate = _contained_path(root, recorded_relative)
        try:
            if path.samefile(candidate):
                return True
        except OSError:
            continue
    return False


def _path_has_exact_spelling(root: Path, relative_path: Path) -> bool:
    current = root
    for part in relative_path.parts:
        if not current.is_dir():
            return False
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError:
            return False
        if part not in entries:
            return False
        current = entries[part]
    return True


def _file_state_artifacts_by_suffix(state: Mapping[str, object]) -> dict[str, Path]:
    raw_files = state.get("files", [])
    if not isinstance(raw_files, list):
        raise SnapshotConnectionError("History file artifact metadata is malformed.")
    artifacts: dict[str, Path] = {}
    for file_info in raw_files:
        if not isinstance(file_info, Mapping):
            raise SnapshotConnectionError("History file artifact metadata is malformed.")
        raw_artifact_path = str(file_info.get("artifact_path") or "").strip()
        if not raw_artifact_path:
            raise SnapshotConnectionError(
                "History file restore could not proceed because a stored artifact path is missing."
            )
        suffix = str(file_info.get("suffix", ""))
        if suffix in artifacts:
            raise SnapshotConnectionError("History file state contains a duplicate companion.")
        artifact = Path(raw_artifact_path)
        if artifact.is_symlink() or not artifact.is_file():
            raise SnapshotConnectionError(
                f"History file restore artifact is missing or unsafe: {artifact}"
            )
        artifacts[suffix] = artifact
    return artifacts


def _safe_relative_path(value: str) -> Path:
    path = Path(str(value))
    if not str(value).strip() or path.is_absolute() or ".." in path.parts:
        raise SnapshotConnectionError(f"Unsafe managed history path: {value!r}")
    return path


def _validate_root(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise SnapshotConnectionError(f"Managed history root is not a regular directory: {root}")


def _validate_root_path_chain(path: Path, *, stop: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise SnapshotConnectionError(
                f"Managed history path contains a symbolic link: {current}"
            )
        if current == stop:
            return
        if stop not in current.parents:
            raise SnapshotConnectionError(
                f"Managed history path escapes its configured root: {path}"
            )
        current = current.parent


def _contained_path(root: Path, relative_path: Path) -> Path:
    validate_managed_root(root)
    root_resolved = root.resolve(strict=False)
    current = root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            raise SnapshotConnectionError(
                f"Managed history path contains a symbolic link: {current}"
            )
    try:
        current.resolve(strict=False).relative_to(root_resolved)
    except ValueError as exc:
        raise SnapshotConnectionError(
            f"Managed history path escapes its configured root: {current}"
        ) from exc
    return current


def _prune_empty_parents(path: Path, *, stop: Path) -> None:
    current = path
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
