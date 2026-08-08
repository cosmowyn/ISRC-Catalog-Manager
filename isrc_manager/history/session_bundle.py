"""Safe filesystem replay for session-level profile history."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

PROFILE_BUNDLE_SUFFIXES = ("", "-wal", "-shm")
SNAPSHOT_INVENTORY_KEY = "snapshot_inventory"
_SNAPSHOT_INVENTORY_VERSION = 1


class ProfileDeletionRollback:
    """Keeps an exact pre-delete profile bundle available until replay commits."""

    def __init__(
        self,
        *,
        restore: Callable[[], None],
        after_restore: Callable[[], None],
        cleanup: Callable[[], None],
    ) -> None:
        self._restore = restore
        self._after_restore = after_restore
        self._cleanup = cleanup
        self._closed = False

    def rollback(self) -> None:
        if self._closed:
            return
        self._restore()
        self._after_restore()
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._cleanup()
        self._closed = True


class SessionProfileBundleStore:
    """Captures, validates, restores, and removes profile snapshot bundles."""

    def __init__(self, snapshot_dir: str | Path) -> None:
        self.snapshot_dir = Path(snapshot_dir)
        self._captured_inventories: dict[str, dict[str, Any]] = {}

    def capture(self, source: Path, target: Path) -> dict[str, Any]:
        safe_target = self.validate_snapshot_path(target)
        self.assert_live_absent(safe_target, action="capture the profile snapshot")
        safe_target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{safe_target.name}.session-capture-",
            dir=safe_target.parent,
        ) as stage_value:
            stage_base = Path(stage_value) / safe_target.name
            self._copy_profile_bundle(source, stage_base)
            inventory = self.capture_inventory(stage_base, require_main=True)
            self.assert_live_absent(safe_target, action="capture the profile snapshot")
            self._link_staged_bundle(stage_base, safe_target, inventory)
        if self.capture_inventory(safe_target, require_main=True) != inventory:
            raise RuntimeError("The profile snapshot changed while it was being captured.")
        self._captured_inventories[self.cache_key(safe_target)] = inventory
        return inventory

    def inventory_for_record(self, snapshot_path: str | Path) -> dict[str, Any]:
        snapshot = self.validate_snapshot_path(snapshot_path)
        cache_key = self.cache_key(snapshot)
        captured = self._captured_inventories.pop(cache_key, None)
        current = self.capture_inventory(snapshot, require_main=True)
        if captured is not None and current != captured:
            raise RuntimeError(
                "The captured profile snapshot changed before its history entry was recorded."
            )
        return current

    def verified_payload_snapshot(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[Path, dict[str, Any]]:
        raw_path = str(payload.get("snapshot_path") or "").strip()
        if not raw_path:
            raise RuntimeError("This session history entry has no profile snapshot path.")
        snapshot = self.validate_snapshot_path(raw_path)
        inventory = self.parse_inventory(payload.get(SNAPSHOT_INVENTORY_KEY))
        current = self.capture_inventory(snapshot, require_main=True)
        if current != inventory:
            raise RuntimeError(
                "The stored profile snapshot bundle is missing or failed its integrity check."
            )
        return snapshot, inventory

    def validate_snapshot_path(self, snapshot_path: str | Path) -> Path:
        lexical_root = Path(os.path.abspath(self.snapshot_dir))
        candidate = Path(os.path.abspath(Path(snapshot_path)))
        if self.snapshot_dir.is_symlink():
            raise ValueError("Session snapshot storage cannot use symbolic links.")
        if candidate.parent != lexical_root:
            raise ValueError(
                "Session snapshot paths must be direct children of the session snapshot directory."
            )
        if candidate.is_symlink():
            raise ValueError("Session snapshot paths cannot use symbolic links.")
        for suffix in PROFILE_BUNDLE_SUFFIXES[1:]:
            if Path(f"{candidate}{suffix}").is_symlink():
                raise ValueError("Session snapshot paths cannot use symbolic links.")
        return candidate

    @staticmethod
    def cache_key(snapshot_path: str | Path) -> str:
        return os.path.abspath(Path(snapshot_path))

    @classmethod
    def capture_inventory(
        cls,
        bundle_path: str | Path,
        *,
        require_main: bool,
    ) -> dict[str, Any]:
        base = Path(bundle_path)
        files: list[dict[str, Any]] = []
        for suffix in PROFILE_BUNDLE_SUFFIXES:
            path = Path(f"{base}{suffix}")
            if path.is_symlink():
                raise RuntimeError("A profile bundle contains an unsafe symbolic link.")
            if not path.exists():
                continue
            if not path.is_file():
                raise RuntimeError("A profile bundle contains a non-file entry.")
            files.append(cls._capture_inventory_for_suffix(path, suffix))
        if require_main and not any(item["suffix"] == "" for item in files):
            raise FileNotFoundError(base)
        return {"version": _SNAPSHOT_INVENTORY_VERSION, "files": files}

    @staticmethod
    def parse_inventory(raw_inventory: object) -> dict[str, Any]:
        if not isinstance(raw_inventory, Mapping):
            raise RuntimeError(
                "This older session history entry has no recorded snapshot integrity data and "
                "cannot be replayed safely."
            )
        if raw_inventory.get("version") != _SNAPSHOT_INVENTORY_VERSION:
            raise RuntimeError("This session history entry uses unsupported snapshot metadata.")
        raw_files = raw_inventory.get("files")
        if not isinstance(raw_files, list):
            raise RuntimeError("This session history entry has invalid snapshot metadata.")

        parsed_files: list[dict[str, Any]] = []
        seen_suffixes: set[str] = set()
        for item in raw_files:
            if not isinstance(item, Mapping):
                raise RuntimeError("This session history entry has invalid snapshot metadata.")
            suffix = item.get("suffix")
            size = item.get("size")
            digest = item.get("sha256")
            if (
                suffix not in PROFILE_BUNDLE_SUFFIXES
                or suffix in seen_suffixes
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise RuntimeError("This session history entry has invalid snapshot metadata.")
            seen_suffixes.add(suffix)
            parsed_files.append({"suffix": suffix, "size": size, "sha256": digest})
        if "" not in seen_suffixes:
            raise RuntimeError("This session history entry has invalid snapshot metadata.")
        parsed_files.sort(key=lambda item: PROFILE_BUNDLE_SUFFIXES.index(item["suffix"]))
        return {"version": _SNAPSHOT_INVENTORY_VERSION, "files": parsed_files}

    @classmethod
    def finalize_recorded_removal(
        cls,
        deleted_path: Path,
        snapshot_inventory: Mapping[str, Any],
    ) -> None:
        if deleted_path.is_symlink():
            raise RuntimeError(
                "The removed profile path became occupied before history could be recorded."
            )
        if deleted_path.exists():
            raise RuntimeError(
                "The removed profile path became occupied before history could be recorded."
            )
        expected_by_suffix = {item["suffix"]: item for item in snapshot_inventory.get("files", [])}
        companions_to_remove: list[Path] = []
        for suffix in PROFILE_BUNDLE_SUFFIXES[1:]:
            companion = Path(f"{deleted_path}{suffix}")
            if companion.is_symlink():
                raise RuntimeError(
                    "The removed profile left an unsafe symbolic-link companion behind."
                )
            if not companion.exists():
                continue
            if not companion.is_file():
                raise RuntimeError("The removed profile left a non-file companion behind.")
            actual = cls._capture_inventory_for_suffix(companion, suffix)
            if expected_by_suffix.get(suffix) != actual:
                raise RuntimeError(
                    "A profile companion changed before removal history could be recorded."
                )
            companions_to_remove.append(companion)
        for companion in companions_to_remove:
            companion.unlink()

    @classmethod
    def assert_live_matches(
        cls,
        profile_path: Path,
        expected_inventory: Mapping[str, Any],
        *,
        action: str,
        logical_matcher: Callable[[], bool] | None = None,
    ) -> None:
        try:
            actual = cls.capture_inventory(profile_path, require_main=True)
        except (FileNotFoundError, RuntimeError) as exc:
            raise RuntimeError(
                f"Cannot {action}: the profile bundle is missing or unsafe."
            ) from exc
        if cls._durable_inventory(actual) == cls._durable_inventory(expected_inventory):
            return
        if logical_matcher is not None:
            try:
                if logical_matcher():
                    return
            except Exception as exc:
                raise RuntimeError(
                    f"Cannot {action}: the profile's logical state could not be verified safely."
                ) from exc
        raise RuntimeError(
            f"Cannot {action}: the profile bundle changed after this history action."
        )

    @staticmethod
    def assert_live_absent(profile_path: Path, *, action: str) -> None:
        for suffix in PROFILE_BUNDLE_SUFFIXES:
            path = Path(f"{profile_path}{suffix}")
            if path.is_symlink() or path.exists():
                raise RuntimeError(
                    f"Cannot {action}: another profile bundle now occupies the target path."
                )

    def delete_profile_bundle(
        self,
        app: Any,
        profile_path: Path,
        *,
        after_delete: Callable[[], None],
        after_rollback: Callable[[], None],
    ) -> ProfileDeletionRollback:
        rollback_temp = tempfile.TemporaryDirectory(
            prefix=f".{profile_path.name}.session-delete-rollback-",
            dir=profile_path.parent,
        )
        try:
            rollback_base = Path(rollback_temp.name) / profile_path.name
            self._copy_profile_bundle(profile_path, rollback_base)
            rollback_inventory = self.capture_inventory(rollback_base, require_main=True)
            replay_rollback = ProfileDeletionRollback(
                restore=lambda: self._restore_exact_rollback_bundle(
                    profile_path,
                    rollback_base,
                    rollback_inventory,
                ),
                after_restore=after_rollback,
                cleanup=rollback_temp.cleanup,
            )
            try:
                app._session_history_delete_profile(str(profile_path))
                for suffix in PROFILE_BUNDLE_SUFFIXES:
                    path = Path(f"{profile_path}{suffix}")
                    if path.is_symlink():
                        raise RuntimeError(
                            "Refusing to delete a symbolic-link profile bundle entry."
                        )
                    if path.exists():
                        if not path.is_file():
                            raise RuntimeError(
                                "Refusing to delete a non-file profile bundle entry."
                            )
                        path.unlink()
                after_delete()
            except Exception:
                try:
                    replay_rollback.rollback()
                except Exception as rollback_exc:
                    raise RuntimeError(
                        "Profile deletion failed and its filesystem rollback could not be "
                        "completed without risking another file."
                    ) from rollback_exc
                raise
            return replay_rollback
        except Exception:
            rollback_temp.cleanup()
            raise

    def restore_after_failed_removal_record(
        self,
        profile_path: Path,
        snapshot_path: Path,
        expected_inventory: Mapping[str, Any],
    ) -> None:
        """Return a just-deleted profile when its history record cannot be saved."""

        self._rollback_partial_delete(
            profile_path,
            snapshot_path,
            expected_inventory,
        )

    def restore(
        self,
        snapshot_path: str | Path,
        target_path: str | Path,
        expected_inventory: Mapping[str, Any] | None = None,
    ) -> None:
        snapshot = self.validate_snapshot_path(snapshot_path)
        target = Path(target_path)
        inventory = (
            self.parse_inventory(expected_inventory)
            if expected_inventory is not None
            else self.capture_inventory(snapshot, require_main=True)
        )
        if self.capture_inventory(snapshot, require_main=True) != inventory:
            raise RuntimeError(
                "The stored profile snapshot bundle is missing or failed its integrity check."
            )
        self._restore_verified_bundle(snapshot, target, inventory)

    def _restore_verified_bundle(
        self,
        source: Path,
        target: Path,
        inventory: Mapping[str, Any],
    ) -> None:
        if self.capture_inventory(source, require_main=True) != inventory:
            raise RuntimeError("A profile rollback bundle failed its integrity check.")
        self.assert_live_absent(target, action="restore the profile snapshot")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{target.name}.session-restore-",
            dir=target.parent,
        ) as stage_value:
            stage_base = Path(stage_value) / target.name
            for item in inventory["files"]:
                suffix = item["suffix"]
                shutil.copy2(Path(f"{source}{suffix}"), Path(f"{stage_base}{suffix}"))
            if self.capture_inventory(stage_base, require_main=True) != inventory:
                raise RuntimeError("The profile snapshot changed while it was being restored.")
            self.assert_live_absent(target, action="restore the profile snapshot")
            self._link_staged_bundle(stage_base, target, inventory)

    def _restore_exact_rollback_bundle(
        self,
        profile_path: Path,
        rollback_base: Path,
        rollback_inventory: Mapping[str, Any],
    ) -> None:
        actual = self.capture_inventory(profile_path, require_main=False)
        if actual == rollback_inventory:
            return
        expected_by_suffix = {item["suffix"]: item for item in rollback_inventory.get("files", [])}
        if any(
            item["suffix"] != "-shm" and expected_by_suffix.get(item["suffix"]) != item
            for item in actual.get("files", [])
        ):
            raise RuntimeError("The partially deleted profile changed during rollback.")
        for item in reversed(actual.get("files", [])):
            Path(f"{profile_path}{item['suffix']}").unlink()
        self._restore_verified_bundle(rollback_base, profile_path, rollback_inventory)

    @classmethod
    def remove_restored_if_unchanged(
        cls,
        profile_path: Path,
        expected_inventory: Mapping[str, Any],
    ) -> None:
        try:
            actual = cls.capture_inventory(profile_path, require_main=True)
        except FileNotFoundError, RuntimeError:
            return
        if cls._durable_inventory(actual) != cls._durable_inventory(expected_inventory):
            return
        for suffix in reversed(PROFILE_BUNDLE_SUFFIXES):
            path = Path(f"{profile_path}{suffix}")
            if path.exists() and not path.is_symlink() and path.is_file():
                path.unlink()

    @staticmethod
    def _copy_profile_bundle(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink() or not source.is_file():
            raise RuntimeError("A profile snapshot source must be a regular file.")
        try:
            shutil.copy2(source, target)
            for suffix in PROFILE_BUNDLE_SUFFIXES[1:]:
                companion = Path(f"{source}{suffix}")
                if companion.exists():
                    if companion.is_symlink() or not companion.is_file():
                        raise RuntimeError("A profile bundle contains an unsafe companion entry.")
                    shutil.copy2(companion, Path(f"{target}{suffix}"))
        except Exception:
            for suffix in reversed(PROFILE_BUNDLE_SUFFIXES):
                copied = Path(f"{target}{suffix}")
                if copied.exists() and not copied.is_symlink() and copied.is_file():
                    copied.unlink()
            raise

    @staticmethod
    def _link_staged_bundle(
        staged_base: Path,
        target: Path,
        inventory: Mapping[str, Any],
    ) -> None:
        installed_paths: list[Path] = []
        try:
            for item in inventory["files"]:
                suffix = item["suffix"]
                staged_path = Path(f"{staged_base}{suffix}")
                installed_path = Path(f"{target}{suffix}")
                os.link(staged_path, installed_path, follow_symlinks=False)
                installed_paths.append(installed_path)
        except Exception:
            for installed_path in reversed(installed_paths):
                if installed_path.exists() and not installed_path.is_symlink():
                    installed_path.unlink()
            raise

    def _rollback_partial_delete(
        self,
        profile_path: Path,
        snapshot_path: Path,
        expected_inventory: Mapping[str, Any],
    ) -> None:
        actual = self.capture_inventory(profile_path, require_main=False)
        if actual == expected_inventory:
            return
        expected_by_suffix = {item["suffix"]: item for item in expected_inventory.get("files", [])}
        if any(
            item["suffix"] != "-shm" and expected_by_suffix.get(item["suffix"]) != item
            for item in actual.get("files", [])
        ):
            raise RuntimeError("The partially deleted profile bundle changed during rollback.")
        for item in reversed(actual.get("files", [])):
            Path(f"{profile_path}{item['suffix']}").unlink()
        self.restore(snapshot_path, profile_path, expected_inventory)

    @staticmethod
    def _durable_inventory(inventory: Mapping[str, Any]) -> dict[str, Any]:
        # SQLite rebuilds shared-memory indexes while opening an unchanged WAL
        # database; DB and WAL bytes are the durable conflict boundary.
        return {
            "version": inventory.get("version"),
            "files": [item for item in inventory.get("files", []) if item.get("suffix") != "-shm"],
        }

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _capture_inventory_for_suffix(
        cls,
        path: Path,
        suffix: str,
    ) -> dict[str, Any]:
        return {
            "suffix": suffix,
            "size": path.stat().st_size,
            "sha256": cls._sha256_file(path),
        }
