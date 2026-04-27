"""Application-wide storage auditing and final cleanup helpers."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

try:
    from PySide6.QtCore import QSettings
except Exception:  # pragma: no cover - optional for non-Qt helper imports
    QSettings = None

from isrc_manager.file_storage import ManagedFileStorage
from isrc_manager.history.cleanup import HistoryStorageCleanupService
from isrc_manager.history.manager import HistoryManager
from isrc_manager.history.session_manager import SessionHistoryManager
from isrc_manager.paths import MANAGED_STORAGE_SUBDIRS, AppStorageLayout
from isrc_manager.services.database_admin import ProfileStoreService
from isrc_manager.update_handoff import (
    UPDATE_BACKUP_HANDOFF_FILENAME,
    UPDATE_BACKUP_STATUS_CREATED,
    UPDATE_BACKUP_STATUS_DESTROYED,
    UPDATE_BACKUP_STATUS_READY_FOR_DELETION,
    mark_update_backup_destroyed,
    read_update_backup_handoff,
)

STATUS_IN_USE = "in_use"
STATUS_DELETED_PROFILE = "deleted_profile_residue"
STATUS_ORPHANED = "orphaned"
STATUS_RECOVERABILITY = "recoverability_artifact"
STATUS_OTHER = "other_app_managed"


@dataclass(slots=True)
class StorageAdminReference:
    profile_path: str
    profile_name: str
    owner_label: str


@dataclass(slots=True)
class StorageAdminItem:
    item_key: str
    status_key: str
    status_label: str
    category_key: str
    category_label: str
    label: str
    path: str
    bytes_on_disk: int
    profile_name: str | None
    profile_path: str | None
    reason: str
    recommended: bool
    warning_required: bool
    warning: str = ""
    references: tuple[StorageAdminReference, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class StorageAdminSummary:
    total_app_bytes: int
    listed_item_bytes: int
    current_profile_bytes: int
    reclaimable_bytes: int
    deleted_profile_bytes: int
    orphaned_bytes: int
    warning_bytes: int
    in_use_bytes: int
    recoverability_bytes: int
    other_bytes: int
    total_items: int
    reclaimable_items: int
    warning_items: int
    current_profile_name: str | None


@dataclass(slots=True)
class StorageAdminAudit:
    summary: StorageAdminSummary
    items: tuple[StorageAdminItem, ...]


@dataclass(slots=True)
class StorageAdminCleanupResult:
    removed_item_keys: tuple[str, ...]
    removed_paths: tuple[str, ...]
    removed_bytes: int
    skipped_item_keys: tuple[str, ...]
    removed_history_entry_ids: tuple[int, ...]
    removed_session_entry_ids: tuple[int, ...]


class ApplicationStorageAdminService:
    """Audits application-wide storage and performs final cleanup without new history."""

    _SESSION_SNAPSHOT_SUFFIXES = ("", "-wal", "-shm", "-journal")
    _MANAGED_REFERENCE_SPECS = (
        {
            "root": "track_media",
            "table": "Tracks",
            "path_column": "audio_file_path",
            "label_sql": "COALESCE(track_title, '')",
            "label_template": "Track #{row_id} audio",
            "detail_template": "Track #{row_id} '{name}' audio",
            "category_key": "track_media",
            "category_label": "Track Media",
        },
        {
            "root": "track_media",
            "table": "Tracks",
            "path_column": "album_art_path",
            "label_sql": "COALESCE(track_title, '')",
            "label_template": "Track #{row_id} album art",
            "detail_template": "Track #{row_id} '{name}' album art",
            "category_key": "track_album_art",
            "category_label": "Track Album Art",
        },
        {
            "root": "track_media",
            "table": "Albums",
            "path_column": "album_art_path",
            "label_sql": "COALESCE(title, '')",
            "label_template": "Album #{row_id} artwork",
            "detail_template": "Album #{row_id} '{name}' artwork",
            "category_key": "album_art",
            "category_label": "Album Artwork",
        },
        {
            "root": "release_media",
            "table": "Releases",
            "path_column": "artwork_path",
            "label_sql": "COALESCE(title, '')",
            "label_template": "Release #{row_id} artwork",
            "detail_template": "Release #{row_id} '{name}' artwork",
            "category_key": "release_artwork",
            "category_label": "Release Artwork",
        },
        {
            "root": "licenses",
            "table": "Licenses",
            "path_column": "file_path",
            "label_sql": "COALESCE(filename, '')",
            "label_template": "License #{row_id}",
            "detail_template": "License #{row_id} '{name}'",
            "category_key": "license_file",
            "category_label": "License File",
        },
        {
            "root": "contract_documents",
            "table": "ContractDocuments",
            "path_column": "file_path",
            "label_sql": "COALESCE(filename, '')",
            "label_template": "Contract document #{row_id}",
            "detail_template": "Contract document #{row_id} '{name}'",
            "category_key": "contract_document",
            "category_label": "Contract Document",
        },
        {
            "root": "asset_registry",
            "table": "AssetVersions",
            "path_column": "stored_path",
            "label_sql": "COALESCE(filename, '')",
            "label_template": "Asset version #{row_id}",
            "detail_template": "Asset version #{row_id} '{name}'",
            "category_key": "asset_file",
            "category_label": "Asset Registry File",
        },
        {
            "root": "custom_field_media",
            "table": "CustomFieldValues",
            "path_column": "managed_file_path",
            "label_sql": "COALESCE(filename, '')",
            "label_template": "Custom field file #{row_id}",
            "detail_template": "Custom field file #{row_id} '{name}'",
            "category_key": "custom_field_file",
            "category_label": "Custom Field File",
        },
        {
            "root": "gs1_templates",
            "table": "GS1TemplateStorage",
            "path_column": "managed_file_path",
            "label_sql": "COALESCE(filename, '')",
            "label_template": "GS1 template #{row_id}",
            "detail_template": "GS1 template #{row_id} '{name}'",
            "category_key": "gs1_template",
            "category_label": "GS1 Template",
        },
        {
            "root": "contract_template_sources",
            "table": "ContractTemplateRevisions",
            "path_column": "managed_file_path",
            "label_sql": "COALESCE(source_filename, '')",
            "label_template": "Contract template source #{row_id}",
            "detail_template": "Contract template source #{row_id} '{name}'",
            "category_key": "contract_template_source",
            "category_label": "Contract Template Source",
        },
        {
            "root": "contract_template_sources",
            "table": "ContractTemplateRevisionAssets",
            "path_column": "managed_file_path",
            "label_sql": "COALESCE(source_filename, '')",
            "label_template": "Contract template source asset #{row_id}",
            "detail_template": "Contract template source asset #{row_id} '{name}'",
            "category_key": "contract_template_source_asset",
            "category_label": "Contract Template Source Asset",
        },
        {
            "root": "contract_template_drafts",
            "table": "ContractTemplateDrafts",
            "path_column": "managed_file_path",
            "label_sql": "COALESCE(filename, '')",
            "label_template": "Contract template draft #{row_id}",
            "detail_template": "Contract template draft #{row_id} '{name}'",
            "category_key": "contract_template_draft",
            "category_label": "Contract Template Draft",
        },
        {
            "root": "contract_template_drafts",
            "table": "ContractTemplateDrafts",
            "path_column": "working_file_path",
            "label_sql": "COALESCE(working_filename, '')",
            "label_template": "Contract template draft working file #{row_id}",
            "detail_template": "Contract template draft working file #{row_id} '{name}'",
            "category_key": "contract_template_draft_working_file",
            "category_label": "Contract Template Draft Working File",
        },
        {
            "root": "contract_template_artifacts",
            "table": "ContractTemplateOutputArtifacts",
            "path_column": "output_path",
            "label_sql": "COALESCE(filename, '')",
            "label_template": "Contract template output #{row_id}",
            "detail_template": "Contract template output #{row_id} '{name}'",
            "category_key": "contract_template_artifact",
            "category_label": "Contract Template Artifact",
        },
    )
    _MANAGED_ROOT_CATEGORIES = {
        "track_media": ("track_media", "Track / Album Media"),
        "release_media": ("release_artwork", "Release Artwork"),
        "licenses": ("license_file", "License File"),
        "contract_documents": ("contract_document", "Contract Document"),
        "asset_registry": ("asset_file", "Asset Registry File"),
        "custom_field_media": ("custom_field_file", "Custom Field File"),
        "gs1_templates": ("gs1_template", "GS1 Template"),
        "contract_template_sources": ("contract_template_source", "Contract Template Source"),
        "contract_template_drafts": ("contract_template_draft", "Contract Template Draft"),
        "contract_template_artifacts": (
            "contract_template_artifact",
            "Contract Template Artifact",
        ),
    }

    _UPDATE_BACKUP_MARKER = ".backup-before-v"
    _UPDATE_BACKUP_NAME_RE = re.compile(
        r"\.backup-before-v(?P<version>.+?)-(?P<stamp>\d{8}-\d{6})(?:-\d+)?$"
    )

    def __init__(
        self,
        layout: AppStorageLayout,
        *,
        update_root: str | Path | None = None,
        installed_update_target_path: str | Path | None = None,
    ):
        self.layout = layout
        self.update_root = (
            Path(update_root).expanduser().resolve()
            if update_root is not None
            else (layout.data_root / "updates").resolve()
        )
        self.installed_update_target_path = (
            Path(installed_update_target_path).expanduser().resolve()
            if installed_update_target_path is not None
            else None
        )
        self.profile_store = ProfileStoreService(layout.database_dir)
        self.managed_stores = {
            name: ManagedFileStorage(data_root=layout.data_root, relative_root=name)
            for name in MANAGED_STORAGE_SUBDIRS
        }

    def inspect(
        self,
        *,
        current_db_path: str | Path | None = None,
        status_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> StorageAdminAudit:
        current_profile = self._normalize_existing_path(current_db_path)
        active_profiles = self._active_profile_paths(current_profile)
        total_steps = max(1, len(active_profiles) + 6)
        active_profile_set = set(active_profiles)
        active_stems = {Path(path).stem for path in active_profiles}
        current_profile_name = Path(current_profile).name if current_profile else None
        references_by_stored_path: dict[str, list[StorageAdminReference]] = defaultdict(list)

        if status_callback is not None:
            status_callback("Discovering active profiles...")
        self._report(progress_callback, 1, total_steps, "Discovered active profiles.")

        for index, profile_path in enumerate(active_profiles, start=1):
            if status_callback is not None:
                status_callback(
                    f"Collecting managed-file references from {Path(profile_path).name}..."
                )
            self._collect_profile_references(profile_path, references_by_stored_path)
            self._report(
                progress_callback,
                1 + index,
                total_steps,
                (
                    "Collected managed-file references from "
                    f"{Path(profile_path).name} ({index}/{len(active_profiles)})."
                ),
            )

        items: list[StorageAdminItem] = []

        if status_callback is not None:
            status_callback("Auditing managed media and document roots...")
        items.extend(
            self._audit_managed_roots(
                references_by_stored_path=references_by_stored_path,
                active_profile_set=active_profile_set,
            )
        )
        self._report(
            progress_callback,
            2 + len(active_profiles),
            total_steps,
            "Audited managed media and document roots.",
        )

        if status_callback is not None:
            status_callback("Auditing history, backup, and session artifacts...")
        items.extend(
            self._audit_history_and_backup_storage(
                active_profiles=active_profiles,
                active_stems=active_stems,
                active_profile_set=active_profile_set,
            )
        )
        self._report(
            progress_callback,
            3 + len(active_profiles),
            total_steps,
            "Audited history, backup, and session artifacts.",
        )

        if status_callback is not None:
            status_callback("Auditing update backups and installer cache...")
        items.extend(self._audit_update_backup_storage())
        self._report(
            progress_callback,
            4 + len(active_profiles),
            total_steps,
            "Audited update backups and installer cache.",
        )

        if status_callback is not None:
            status_callback("Auditing generated exports and log files...")
        items.extend(self._audit_generated_files())
        self._report(
            progress_callback,
            5 + len(active_profiles),
            total_steps,
            "Audited generated exports and log files.",
        )

        if status_callback is not None:
            status_callback("Finalizing application storage summary...")

        items.sort(
            key=lambda item: (
                item.status_label,
                item.category_label,
                item.profile_name or "",
                item.label,
            )
        )

        summary = self._build_summary(
            items=items,
            active_profiles=active_profiles,
            current_profile=current_profile,
            current_profile_name=current_profile_name,
        )
        self._report(
            progress_callback,
            total_steps,
            total_steps,
            "Application-wide storage summary ready.",
        )
        return StorageAdminAudit(summary=summary, items=tuple(items))

    def inspect_progress_total(
        self,
        *,
        current_db_path: str | Path | None = None,
    ) -> int:
        current_profile = self._normalize_existing_path(current_db_path)
        active_profiles = self._active_profile_paths(current_profile)
        return max(1, len(active_profiles) + 6)

    def cleanup_selected(
        self,
        item_keys: list[str] | tuple[str, ...],
        *,
        current_db_path: str | Path | None = None,
        allow_warning_deletes: bool = False,
        status_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> StorageAdminCleanupResult:
        audit = self.inspect(
            current_db_path=current_db_path,
            status_callback=status_callback,
            progress_callback=None,
        )
        item_by_key = {item.item_key: item for item in audit.items}
        selected_items: list[StorageAdminItem] = []
        for raw_key in item_keys:
            item = item_by_key.get(str(raw_key))
            if item is None:
                raise ValueError(f"Cleanup item is no longer available: {raw_key}")
            selected_items.append(item)

        if any(item.warning_required for item in selected_items) and not allow_warning_deletes:
            raise ValueError(
                "One or more selected items are still in use or protected. Confirm the stronger warning before deleting them."
            )

        removed_keys: list[str] = []
        removed_paths: list[str] = []
        removed_history_entry_ids: set[int] = set()
        removed_session_entry_ids: set[int] = set()
        removed_bytes = 0
        skipped_keys: list[str] = []
        history_contexts: dict[
            str, tuple[sqlite3.Connection, HistoryManager, HistoryStorageCleanupService]
        ] = {}
        session_manager = SessionHistoryManager(self.layout.history_dir)

        total_items = max(1, len(selected_items))
        for index, item in enumerate(selected_items, start=1):
            label = item.label or Path(item.path).name
            if status_callback is not None:
                status_callback(f"Cleaning {label} ({index}/{total_items})...")
            self._report(
                progress_callback,
                index - 1,
                total_items,
                f"Preparing cleanup for {label}...",
            )
            try:
                removed = self._cleanup_item(
                    item,
                    session_manager=session_manager,
                    history_contexts=history_contexts,
                    removed_history_entry_ids=removed_history_entry_ids,
                    removed_session_entry_ids=removed_session_entry_ids,
                )
            except FileNotFoundError:
                removed = [str(item.path)]
            removed_keys.append(item.item_key)
            removed_bytes += int(item.bytes_on_disk or 0)
            removed_paths.extend(str(path) for path in removed)
            self._report(
                progress_callback,
                index,
                total_items,
                f"Removed {label}.",
            )

        for conn, _manager, _cleanup_service in history_contexts.values():
            try:
                conn.close()
            except Exception:
                pass

        if status_callback is not None:
            status_callback("Storage cleanup finished.")
        if progress_callback is not None:
            progress_callback(100, 100, "Storage cleanup finished.")

        return StorageAdminCleanupResult(
            removed_item_keys=tuple(removed_keys),
            removed_paths=tuple(dict.fromkeys(removed_paths)),
            removed_bytes=removed_bytes,
            skipped_item_keys=tuple(skipped_keys),
            removed_history_entry_ids=tuple(sorted(removed_history_entry_ids)),
            removed_session_entry_ids=tuple(sorted(removed_session_entry_ids)),
        )

    def _active_profile_paths(self, current_profile: str | None) -> list[str]:
        active_paths = [
            path
            for path in (
                self._normalize_existing_path(path) for path in self.profile_store.list_profiles()
            )
            if path
        ]
        if current_profile and current_profile not in active_paths:
            active_paths.append(current_profile)
        return sorted(dict.fromkeys(active_paths))

    def _collect_profile_references(
        self,
        profile_path: str,
        references_by_stored_path: dict[str, list[StorageAdminReference]],
    ) -> None:
        conn = sqlite3.connect(profile_path)
        try:
            for spec in self._MANAGED_REFERENCE_SPECS:
                table = str(spec["table"])
                path_column = str(spec["path_column"])
                if not self._table_has_columns(conn, table, ("id", path_column)):
                    continue
                label_sql = str(spec["label_sql"])
                query = f"""
                    SELECT id, {path_column}, {label_sql}
                    FROM {table}
                    WHERE COALESCE(trim({path_column}), '') != ''
                    ORDER BY id
                """
                store = self.managed_stores[str(spec["root"])]
                try:
                    rows = conn.execute(query).fetchall()
                except sqlite3.OperationalError:
                    rows = conn.execute(
                        f"""
                        SELECT id, {path_column}, ''
                        FROM {table}
                        WHERE COALESCE(trim({path_column}), '') != ''
                        ORDER BY id
                        """
                    ).fetchall()
                for row_id, stored_path, name in rows:
                    clean_path = self._normalize_stored_path(stored_path)
                    if not clean_path or not store.is_managed(clean_path):
                        continue
                    detail_template = str(spec["detail_template"])
                    display_name = self._display_reference_name(
                        row_id=row_id,
                        name=str(name or "").strip(),
                        detail_template=detail_template,
                    )
                    reference = StorageAdminReference(
                        profile_path=profile_path,
                        profile_name=Path(profile_path).name,
                        owner_label=display_name,
                    )
                    references_by_stored_path[clean_path].append(reference)
        finally:
            conn.close()

    def _audit_managed_roots(
        self,
        *,
        references_by_stored_path: dict[str, list[StorageAdminReference]],
        active_profile_set: set[str],
    ) -> list[StorageAdminItem]:
        items: list[StorageAdminItem] = []
        for root_name, store in self.managed_stores.items():
            root_path = store.root_path
            if root_path is None or not root_path.exists():
                continue
            category_key, category_label = self._MANAGED_ROOT_CATEGORIES.get(
                root_name,
                (root_name, root_name.replace("_", " ").title()),
            )
            for path in sorted(path for path in root_path.rglob("*") if path.is_file()):
                stored_path = self._normalize_stored_path(path.relative_to(self.layout.data_root))
                references = tuple(references_by_stored_path.get(stored_path, ()))
                profile_name = self._profile_name_from_references(references)
                profile_path = self._profile_path_from_references(references)
                if references:
                    reason = self._format_reference_reason(references)
                    items.append(
                        StorageAdminItem(
                            item_key=f"managed:{stored_path}",
                            status_key=STATUS_IN_USE,
                            status_label="In Use by Active Profile",
                            category_key=category_key,
                            category_label=category_label,
                            label=path.name,
                            path=str(path),
                            bytes_on_disk=self._path_size(path),
                            profile_name=profile_name,
                            profile_path=profile_path,
                            reason=reason,
                            recommended=False,
                            warning_required=True,
                            warning=(
                                "Deleting this file permanently removes application-managed media that active profiles still reference.\n\n"
                                f"{reason}"
                            ),
                            references=references,
                            metadata={
                                "cleanup_kind": "direct_path",
                                "stored_path": str(path),
                            },
                        )
                    )
                    continue
                items.append(
                    StorageAdminItem(
                        item_key=f"managed:{stored_path}",
                        status_key=STATUS_ORPHANED,
                        status_label="Orphaned / Unreferenced",
                        category_key=category_key,
                        category_label=category_label,
                        label=path.name,
                        path=str(path),
                        bytes_on_disk=self._path_size(path),
                        profile_name=None,
                        profile_path=None,
                        reason="No active profile references this application-managed file.",
                        recommended=True,
                        warning_required=False,
                        metadata={
                            "cleanup_kind": "direct_path",
                            "stored_path": str(path),
                        },
                    )
                )
        return items

    def _audit_history_and_backup_storage(
        self,
        *,
        active_profiles: list[str],
        active_stems: set[str],
        active_profile_set: set[str],
    ) -> list[StorageAdminItem]:
        items: list[StorageAdminItem] = []
        registered_backup_paths: set[str] = set()

        for profile_path in active_profiles:
            conn = sqlite3.connect(profile_path)
            try:
                history_state = self._collect_history_state(profile_path, conn)
            finally:
                conn.close()
            profile_name = Path(profile_path).name
            items.extend(
                self._history_items_for_profile(
                    profile_path=profile_path,
                    profile_name=profile_name,
                    history_state=history_state,
                )
            )
            registered_backup_paths.update(history_state["registered_backup_paths"])

        items.extend(self._deleted_profile_history_residue_items(active_stems))
        items.extend(
            self._backup_file_items(
                registered_backup_paths=registered_backup_paths,
                active_profile_set=active_profile_set,
            )
        )
        items.extend(self._session_snapshot_items(active_profile_set=active_profile_set))
        return items

    def _audit_update_backup_storage(self) -> list[StorageAdminItem]:
        items: list[StorageAdminItem] = []
        update_root = self.update_root
        handoff_path = update_root / UPDATE_BACKUP_HANDOFF_FILENAME
        handoff_state = read_update_backup_handoff(state_path=handoff_path)
        handoff_backup_path = self._handoff_backup_path(handoff_state)
        handoff_backup_identity = (
            self._path_identity(handoff_backup_path) if handoff_backup_path is not None else ""
        )

        backup_candidates: list[Path] = []
        if handoff_backup_path is not None:
            backup_candidates.append(handoff_backup_path)
        for scan_root in self._update_backup_scan_roots(handoff_state):
            if not scan_root.is_dir():
                continue
            for candidate in sorted(scan_root.iterdir(), key=lambda path: path.name.lower()):
                if self._looks_like_update_backup(candidate):
                    backup_candidates.append(candidate)

        seen_backup_paths: set[str] = set()
        backup_identities: set[str] = set()
        for backup_path in backup_candidates:
            identity = self._path_identity(backup_path)
            if not identity or identity in seen_backup_paths:
                continue
            if not backup_path.exists() and not backup_path.is_symlink():
                continue
            seen_backup_paths.add(identity)
            backup_identities.add(identity)
            items.append(
                self._update_backup_item(
                    backup_path,
                    handoff_state=handoff_state,
                    handoff_path=handoff_path,
                    is_handoff_backup=bool(identity == handoff_backup_identity),
                )
            )

        if update_root.exists():
            for path in sorted(update_root.iterdir(), key=lambda candidate: candidate.name.lower()):
                if path.name == UPDATE_BACKUP_HANDOFF_FILENAME:
                    continue
                if self._path_identity(path) in backup_identities:
                    continue
                if not path.exists() and not path.is_symlink():
                    continue
                category_key = "update_workspace" if path.is_dir() else "update_cache_file"
                category_label = (
                    "Update Installer Workspace" if path.is_dir() else "Update Cache File"
                )
                items.append(
                    StorageAdminItem(
                        item_key=f"update-cache:{self._path_identity(path)}",
                        status_key=STATUS_OTHER,
                        status_label="Update Cache / Installer Workspace",
                        category_key=category_key,
                        category_label=category_label,
                        label=path.name,
                        path=str(path),
                        bytes_on_disk=self._path_size(path),
                        profile_name=self._version_label_from_update_workspace(path),
                        profile_path=None,
                        reason=(
                            "This update workspace can contain downloaded packages, extracted staging files, helper-runtime copies, and install logs from a previous update attempt."
                        ),
                        recommended=True,
                        warning_required=False,
                        metadata={
                            "cleanup_kind": "direct_path",
                            "stored_path": str(path),
                        },
                    )
                )
        return items

    def _update_backup_item(
        self,
        backup_path: Path,
        *,
        handoff_state: dict[str, object] | None,
        handoff_path: Path,
        is_handoff_backup: bool,
    ) -> StorageAdminItem:
        status = str(handoff_state.get("status") or "") if handoff_state else ""
        expected_version = (
            str(handoff_state.get("expected_version") or "").strip()
            if is_handoff_backup and handoff_state
            else ""
        )
        parsed_version, parsed_created_at = self._parse_update_backup_name(backup_path.name)
        version = expected_version or parsed_version
        created_at = (
            str(handoff_state.get("created_at") or "").strip()
            if is_handoff_backup and handoff_state
            else parsed_created_at
        )

        status_key = STATUS_RECOVERABILITY
        status_label = "Older Update Backup"
        reason = (
            "This is an older packaged-app rollback copy left by the automatic updater. "
            "It is not required by catalog data."
        )
        recommended = True
        warning_required = False
        warning = ""

        if is_handoff_backup and status == UPDATE_BACKUP_STATUS_CREATED:
            status_key = STATUS_IN_USE
            status_label = "Current Update Rollback Backup"
            reason = "This backup is the updater's current rollback copy. It is normally removed after the updated app reaches a clean startup and closes."
            recommended = False
            warning_required = True
            warning = "Deleting this backup removes the automatic rollback copy for the most recent packaged-app update."
        elif is_handoff_backup and status == UPDATE_BACKUP_STATUS_READY_FOR_DELETION:
            status_label = "Ready for Update Cleanup"
            reason = "The updated app marked this rollback copy ready for deletion, but cleanup did not remove it."
        elif is_handoff_backup and status == UPDATE_BACKUP_STATUS_DESTROYED:
            status_label = "Stale Update Backup"
            reason = "The updater handoff says this rollback copy was already destroyed, but the file or folder is still present."

        details: list[str] = []
        if version:
            details.append(f"Target update version: v{version.removeprefix('v')}")
        if created_at:
            details.append(f"Created: {created_at}")
        if is_handoff_backup and status:
            details.append(f"Handoff status: {status}")
        if details:
            reason = f"{reason}\n" + "\n".join(details)

        return StorageAdminItem(
            item_key=f"update-backup:{self._path_identity(backup_path)}",
            status_key=status_key,
            status_label=status_label,
            category_key="update_install_backup",
            category_label="Update Install Backup",
            label=backup_path.name,
            path=str(backup_path),
            bytes_on_disk=self._path_size(backup_path),
            profile_name=f"v{version.removeprefix('v')}" if version else "",
            profile_path=None,
            reason=reason,
            recommended=recommended,
            warning_required=warning_required,
            warning=warning,
            metadata={
                "cleanup_kind": "update_backup",
                "stored_path": str(backup_path),
                "handoff_backup": is_handoff_backup,
                "handoff_state_path": str(handoff_path),
            },
        )

    def _update_backup_scan_roots(
        self,
        handoff_state: dict[str, object] | None,
    ) -> list[Path]:
        roots: list[Path] = []
        if self.installed_update_target_path is not None:
            roots.append(self.installed_update_target_path.parent)
        if isinstance(handoff_state, dict):
            for key in ("backup_path", "target_path", "installed_path"):
                raw_path = str(handoff_state.get(key) or "").strip()
                if not raw_path:
                    continue
                try:
                    roots.append(Path(raw_path).expanduser().resolve().parent)
                except Exception:
                    pass
        unique_roots: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            identity = self._path_identity(root)
            if not identity or identity in seen:
                continue
            seen.add(identity)
            unique_roots.append(root)
        return unique_roots

    def _handoff_backup_path(self, handoff_state: dict[str, object] | None) -> Path | None:
        if not isinstance(handoff_state, dict):
            return None
        raw_path = str(handoff_state.get("backup_path") or "").strip()
        if not raw_path:
            return None
        try:
            return Path(raw_path).expanduser()
        except Exception:
            return None

    def _looks_like_update_backup(self, path: Path) -> bool:
        return bool(self._UPDATE_BACKUP_MARKER in path.name)

    def _parse_update_backup_name(self, name: str) -> tuple[str, str]:
        match = self._UPDATE_BACKUP_NAME_RE.search(str(name or ""))
        if match is None:
            return "", ""
        version = str(match.group("version") or "").strip()
        stamp = str(match.group("stamp") or "").strip()
        if len(stamp) == 15:
            created_at = (
                f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]} "
                f"{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}"
            )
        else:
            created_at = stamp
        return version, created_at

    @staticmethod
    def _version_label_from_update_workspace(path: Path) -> str:
        name = str(path.name or "").strip()
        if not name.startswith("v"):
            return ""
        version = name[1:].split("-", 1)[0].strip()
        return f"v{version}" if version else ""

    def _collect_history_state(
        self,
        profile_path: str,
        conn: sqlite3.Connection,
    ) -> dict[str, object]:
        db_stem = Path(profile_path).stem
        history_root = self.layout.history_dir
        snapshot_root = history_root / "snapshots" / db_stem
        archive_root = history_root / "snapshot_archives" / db_stem
        file_state_root = history_root / "file_states" / db_stem

        table_names = self._table_names(conn)
        snapshot_rows = []
        backup_rows = []
        entry_rows = []
        if "HistorySnapshots" in table_names:
            snapshot_rows = conn.execute(
                """
                SELECT id, created_at, kind, label, db_snapshot_path, manifest_json
                FROM HistorySnapshots
                ORDER BY id
                """
            ).fetchall()
        if "HistoryBackups" in table_names:
            backup_rows = conn.execute(
                """
                SELECT id, created_at, kind, label, backup_path, source_db_path, metadata_json
                FROM HistoryBackups
                ORDER BY id
                """
            ).fetchall()
        if "HistoryEntries" in table_names:
            entry_rows = conn.execute(
                """
                SELECT id, parent_id, payload_json, inverse_json, redo_json, snapshot_before_id, snapshot_after_id
                FROM HistoryEntries
                ORDER BY id
                """
            ).fetchall()

        protected_snapshot_ids: set[int] = set()
        live_archive_paths: set[Path] = set()
        live_file_state_paths: set[Path] = set()
        for (
            entry_id,
            parent_id,
            payload_json,
            inverse_json,
            redo_json,
            before_id,
            after_id,
        ) in entry_rows:
            del entry_id, parent_id
            if before_id is not None:
                protected_snapshot_ids.add(int(before_id))
            if after_id is not None:
                protected_snapshot_ids.add(int(after_id))
            for payload in (
                self._load_json(payload_json),
                self._load_json(inverse_json),
                self._load_json(redo_json),
            ):
                protected_snapshot_ids.update(self._collect_int_values(payload, "snapshot_id"))
                live_archive_paths.update(self._paths_under_root(payload, archive_root))
                live_file_state_paths.update(self._paths_under_root(payload, file_state_root))

        registered_snapshot_paths = {
            str(Path(row[4])) for row in snapshot_rows if str(row[4] or "").strip()
        }
        registered_backup_paths = {
            str(Path(row[4])) for row in backup_rows if str(row[4] or "").strip()
        }

        return {
            "snapshot_rows": snapshot_rows,
            "backup_rows": backup_rows,
            "entry_rows": entry_rows,
            "protected_snapshot_ids": protected_snapshot_ids,
            "live_archive_paths": live_archive_paths,
            "live_file_state_paths": live_file_state_paths,
            "snapshot_root": snapshot_root,
            "archive_root": archive_root,
            "file_state_root": file_state_root,
            "registered_snapshot_paths": registered_snapshot_paths,
            "registered_backup_paths": registered_backup_paths,
        }

    def _history_items_for_profile(
        self,
        *,
        profile_path: str,
        profile_name: str,
        history_state: dict[str, object],
    ) -> list[StorageAdminItem]:
        items: list[StorageAdminItem] = []
        protected_snapshot_ids = set(history_state["protected_snapshot_ids"])
        live_archive_paths = set(history_state["live_archive_paths"])
        live_file_state_paths = set(history_state["live_file_state_paths"])
        snapshot_root = Path(history_state["snapshot_root"])
        archive_root = Path(history_state["archive_root"])
        file_state_root = Path(history_state["file_state_root"])
        registered_snapshot_paths = set(history_state["registered_snapshot_paths"])
        snapshot_rows = list(history_state["snapshot_rows"])
        backup_rows = list(history_state["backup_rows"])

        for snapshot_id, created_at, kind, label, snapshot_path, manifest_json in snapshot_rows:
            del created_at, kind
            snapshot_file = Path(str(snapshot_path))
            manifest = self._load_json(manifest_json)
            bytes_on_disk = (
                self._path_size(snapshot_file)
                + self._path_size(self._snapshot_sidecar_path(snapshot_file))
                + self._managed_manifest_size(manifest)
            )
            protected = int(snapshot_id) in protected_snapshot_ids
            items.append(
                StorageAdminItem(
                    item_key=f"history:{profile_path}:snapshot_record:{int(snapshot_id)}",
                    status_key=STATUS_IN_USE if protected else STATUS_RECOVERABILITY,
                    status_label=(
                        "In Use by Active Profile"
                        if protected
                        else "Recoverability / History Artifact"
                    ),
                    category_key="history_snapshot",
                    category_label="History Snapshot",
                    label=str(label or snapshot_file.name),
                    path=str(snapshot_file),
                    bytes_on_disk=bytes_on_disk,
                    profile_name=profile_name,
                    profile_path=profile_path,
                    reason=(
                        "This snapshot is still referenced by retained undo/redo or snapshot history."
                        if protected
                        else "This snapshot is no longer referenced by retained history entries."
                    ),
                    recommended=not protected,
                    warning_required=protected,
                    warning=(
                        "Deleting this snapshot also removes the retained history entries that still depend on it."
                        if protected
                        else ""
                    ),
                    metadata={
                        "cleanup_kind": "history_item",
                        "history_item_type": "snapshot_record",
                        "record_id": int(snapshot_id),
                        "profile_path": profile_path,
                    },
                )
            )

        for (
            backup_id,
            created_at,
            kind,
            label,
            backup_path,
            source_db_path,
            metadata_json,
        ) in backup_rows:
            del created_at, kind, source_db_path, metadata_json
            backup_file = Path(str(backup_path))
            items.append(
                StorageAdminItem(
                    item_key=f"history:{profile_path}:backup_record:{int(backup_id)}",
                    status_key=STATUS_RECOVERABILITY,
                    status_label="Recoverability / History Artifact",
                    category_key="database_backup",
                    category_label="Database Backup",
                    label=str(label or backup_file.name),
                    path=str(backup_file),
                    bytes_on_disk=(
                        self._path_size(backup_file)
                        + self._path_size(self._backup_sidecar_path(backup_file))
                    ),
                    profile_name=profile_name,
                    profile_path=profile_path,
                    reason="Safety backups are retained for recovery but are not required for live catalog data.",
                    recommended=True,
                    warning_required=False,
                    metadata={
                        "cleanup_kind": "history_item",
                        "history_item_type": "backup_record",
                        "record_id": int(backup_id),
                        "profile_path": profile_path,
                    },
                )
            )

        if snapshot_root.exists():
            for path in sorted(
                path
                for path in snapshot_root.glob("*.db")
                if str(path) not in registered_snapshot_paths
            ):
                items.append(
                    StorageAdminItem(
                        item_key=f"history:{profile_path}:orphan_snapshot_file:{path}",
                        status_key=STATUS_ORPHANED,
                        status_label="Orphaned / Unreferenced",
                        category_key="history_snapshot",
                        category_label="History Snapshot",
                        label=path.name,
                        path=str(path),
                        bytes_on_disk=(
                            self._path_size(path)
                            + self._path_size(self._snapshot_sidecar_path(path))
                            + self._path_size(path.with_suffix(".assets"))
                        ),
                        profile_name=profile_name,
                        profile_path=profile_path,
                        reason="Snapshot storage is present on disk but not registered in the active profile history.",
                        recommended=True,
                        warning_required=False,
                        metadata={
                            "cleanup_kind": "history_item",
                            "history_item_type": "orphan_snapshot_file",
                            "profile_path": profile_path,
                            "path": str(path),
                        },
                    )
                )
        for path in self._orphan_snapshot_bundle_roots(snapshot_root, archive_root):
            items.append(
                StorageAdminItem(
                    item_key=f"history:{profile_path}:orphan_snapshot_bundle:{path}",
                    status_key=STATUS_ORPHANED,
                    status_label="Orphaned / Unreferenced",
                    category_key="history_snapshot",
                    category_label="History Snapshot",
                    label=path.name,
                    path=str(path),
                    bytes_on_disk=self._path_size(path),
                    profile_name=profile_name,
                    profile_path=profile_path,
                    reason="Snapshot asset storage is present on disk without a matching snapshot database file.",
                    recommended=True,
                    warning_required=False,
                    metadata={
                        "cleanup_kind": "direct_path",
                        "stored_path": str(path),
                    },
                )
            )
        for path in self._orphan_snapshot_companion_files(snapshot_root, archive_root):
            items.append(
                StorageAdminItem(
                    item_key=f"history:{profile_path}:orphan_snapshot_companion:{path}",
                    status_key=STATUS_ORPHANED,
                    status_label="Orphaned / Unreferenced",
                    category_key="history_snapshot",
                    category_label="History Snapshot",
                    label=path.name,
                    path=str(path),
                    bytes_on_disk=self._path_size(path),
                    profile_name=profile_name,
                    profile_path=profile_path,
                    reason="Snapshot companion storage is present on disk without a matching snapshot database file.",
                    recommended=True,
                    warning_required=False,
                    metadata={
                        "cleanup_kind": "direct_path",
                        "stored_path": str(path),
                    },
                )
            )

        if archive_root.exists():
            for archive_path in sorted(
                path for path in archive_root.glob("*.db") if path.is_file()
            ):
                protected = self._path_is_referenced(archive_path, live_archive_paths)
                items.append(
                    StorageAdminItem(
                        item_key=f"history:{profile_path}:snapshot_archive:{archive_path}",
                        status_key=STATUS_IN_USE if protected else STATUS_RECOVERABILITY,
                        status_label=(
                            "In Use by Active Profile"
                            if protected
                            else "Recoverability / History Artifact"
                        ),
                        category_key="snapshot_archive",
                        category_label="Snapshot Archive",
                        label=archive_path.name,
                        path=str(archive_path),
                        bytes_on_disk=(
                            self._path_size(archive_path)
                            + self._path_size(self._snapshot_sidecar_path(archive_path))
                            + self._path_size(archive_path.with_suffix(".assets"))
                        ),
                        profile_name=profile_name,
                        profile_path=profile_path,
                        reason=(
                            "This archived snapshot bundle is still referenced by retained history entries."
                            if protected
                            else "No retained history entry references this archived snapshot bundle."
                        ),
                        recommended=not protected,
                        warning_required=protected,
                        warning=(
                            "Deleting this archive also removes the retained history entries that still depend on it."
                            if protected
                            else ""
                        ),
                        metadata={
                            "cleanup_kind": "history_item",
                            "history_item_type": "snapshot_archive",
                            "profile_path": profile_path,
                            "path": str(archive_path),
                        },
                    )
                )

        if file_state_root.exists():
            for bundle_path in sorted(path for path in file_state_root.iterdir() if path.is_dir()):
                protected = self._path_is_referenced(bundle_path, live_file_state_paths)
                items.append(
                    StorageAdminItem(
                        item_key=f"history:{profile_path}:file_state_bundle:{bundle_path}",
                        status_key=STATUS_IN_USE if protected else STATUS_RECOVERABILITY,
                        status_label=(
                            "In Use by Active Profile"
                            if protected
                            else "Recoverability / History Artifact"
                        ),
                        category_key="file_state_bundle",
                        category_label="Stored File-State Bundle",
                        label=bundle_path.name,
                        path=str(bundle_path),
                        bytes_on_disk=self._path_size(bundle_path),
                        profile_name=profile_name,
                        profile_path=profile_path,
                        reason=(
                            "This stored file-state bundle is still referenced by retained history payloads."
                            if protected
                            else "No retained history entry references this stored file-state bundle."
                        ),
                        recommended=not protected,
                        warning_required=protected,
                        warning=(
                            "Deleting this stored file-state bundle also removes the retained history entries that still depend on it."
                            if protected
                            else ""
                        ),
                        metadata={
                            "cleanup_kind": "history_item",
                            "history_item_type": "file_state_bundle",
                            "profile_path": profile_path,
                            "path": str(bundle_path),
                        },
                    )
                )

        return items

    def _deleted_profile_history_residue_items(
        self, active_stems: set[str]
    ) -> list[StorageAdminItem]:
        items: list[StorageAdminItem] = []
        for root_name, category_key, category_label in (
            ("snapshots", "deleted_profile_snapshots", "Deleted-Profile Snapshot Storage"),
            ("snapshot_archives", "deleted_profile_archives", "Deleted-Profile Snapshot Archives"),
            ("file_states", "deleted_profile_file_states", "Deleted-Profile File-State Bundles"),
        ):
            root = self.layout.history_dir / root_name
            if not root.exists():
                continue
            for child in sorted(path for path in root.iterdir() if path.is_dir()):
                if child.name in active_stems:
                    continue
                items.append(
                    StorageAdminItem(
                        item_key=f"deleted-profile-tree:{root_name}:{child}",
                        status_key=STATUS_DELETED_PROFILE,
                        status_label="Deleted / Missing Profile Residue",
                        category_key=category_key,
                        category_label=category_label,
                        label=child.name,
                        path=str(child),
                        bytes_on_disk=self._path_size(child),
                        profile_name=child.name,
                        profile_path=None,
                        reason=(
                            f"This history subtree belongs to profile stem '{child.name}', but no active profile database with that stem exists."
                        ),
                        recommended=True,
                        warning_required=False,
                        metadata={
                            "cleanup_kind": "direct_path",
                            "stored_path": str(child),
                        },
                    )
                )
        return items

    def _backup_file_items(
        self,
        *,
        registered_backup_paths: set[str],
        active_profile_set: set[str],
    ) -> list[StorageAdminItem]:
        items: list[StorageAdminItem] = []
        if not self.layout.backups_dir.exists():
            return items
        for path in sorted(self.layout.backups_dir.rglob("*.db")):
            normalized = str(path)
            if normalized in registered_backup_paths:
                continue
            metadata = self._load_json_sidecar(self._backup_sidecar_path(path))
            source_db_path = self._normalize_existing_path(metadata.get("source_db_path"))
            if source_db_path and source_db_path not in active_profile_set:
                status_key = STATUS_DELETED_PROFILE
                status_label = "Deleted / Missing Profile Residue"
                reason = (
                    "This database copy was created for a profile database that no longer exists."
                )
                recommended = True
            else:
                status_key = STATUS_ORPHANED
                status_label = "Orphaned / Unreferenced"
                reason = "This database copy is present on disk but is not registered in any active profile history."
                recommended = True
            items.append(
                StorageAdminItem(
                    item_key=f"backup-file:{path}",
                    status_key=status_key,
                    status_label=status_label,
                    category_key="database_copy",
                    category_label="Database Copy",
                    label=path.name,
                    path=str(path),
                    bytes_on_disk=self._path_size(path)
                    + self._path_size(self._backup_sidecar_path(path)),
                    profile_name=Path(source_db_path).name if source_db_path else None,
                    profile_path=source_db_path,
                    reason=reason,
                    recommended=recommended,
                    warning_required=False,
                    metadata={
                        "cleanup_kind": "direct_path",
                        "stored_path": str(path),
                    },
                )
            )
        for path in self._orphan_backup_companion_files():
            metadata_path = (
                path
                if str(path).endswith(HistoryManager.BACKUP_SIDECAR_SUFFIX)
                else self._backup_sidecar_path(path)
            )
            metadata = self._load_json_sidecar(metadata_path)
            source_db_path = self._normalize_existing_path(metadata.get("source_db_path"))
            status_key = STATUS_ORPHANED
            status_label = "Orphaned / Unreferenced"
            reason = "Backup companion storage is present on disk without a matching database copy."
            if source_db_path and source_db_path not in active_profile_set:
                status_key = STATUS_DELETED_PROFILE
                status_label = "Deleted / Missing Profile Residue"
                reason = (
                    "Backup companion storage belongs to a profile database that no longer exists."
                )
            items.append(
                StorageAdminItem(
                    item_key=f"backup-companion:{path}",
                    status_key=status_key,
                    status_label=status_label,
                    category_key="database_copy",
                    category_label="Database Copy",
                    label=path.name,
                    path=str(path),
                    bytes_on_disk=self._path_size(path),
                    profile_name=Path(source_db_path).name if source_db_path else None,
                    profile_path=source_db_path,
                    reason=reason,
                    recommended=True,
                    warning_required=False,
                    metadata={
                        "cleanup_kind": "direct_path",
                        "stored_path": str(path),
                    },
                )
            )
        return items

    def _session_snapshot_items(self, *, active_profile_set: set[str]) -> list[StorageAdminItem]:
        items: list[StorageAdminItem] = []
        history = SessionHistoryManager(self.layout.history_dir)
        references = history.snapshot_references()
        refs_by_snapshot: dict[str, list[dict[str, object]]] = defaultdict(list)
        for reference in references:
            snapshot_path = (
                self._normalize_existing_path(reference.get("snapshot_path"))
                or str(reference.get("snapshot_path") or "").strip()
            )
            if snapshot_path:
                refs_by_snapshot[snapshot_path].append(reference)

        for path in sorted(history.snapshot_dir.glob("*.db")):
            normalized = str(path)
            refs = refs_by_snapshot.get(normalized, [])
            associated_profile_paths = {
                self._normalize_existing_path(reference.get("profile_path"))
                or str(reference.get("profile_path") or "").strip()
                for reference in refs
                if str(reference.get("profile_path") or "").strip()
            }
            associated_active = any(path in active_profile_set for path in associated_profile_paths)
            associated_missing = any(
                path not in active_profile_set for path in associated_profile_paths
            )
            warning_required = bool(refs)
            if refs and associated_active:
                status_key = STATUS_IN_USE
                status_label = "In Use by Active Profile"
                reason = "Session undo/redo still references this stored profile snapshot for an active profile."
                warning = "Deleting this session snapshot also removes the retained session-history entries that still depend on it."
                recommended = False
            elif refs and associated_missing:
                status_key = STATUS_DELETED_PROFILE
                status_label = "Deleted / Missing Profile Residue"
                reason = "Session history still keeps this recoverability snapshot for a deleted or missing profile."
                warning = "Deleting this session snapshot also removes the retained session-history entries that still depend on it."
                recommended = True
            else:
                status_key = STATUS_ORPHANED
                status_label = "Orphaned / Unreferenced"
                reason = "Session history no longer references this stored profile snapshot."
                warning = ""
                recommended = True
            profile_name = None
            profile_path = None
            if associated_profile_paths:
                first = sorted(associated_profile_paths)[0]
                profile_path = first or None
                profile_name = Path(first).name if first else None
            items.append(
                StorageAdminItem(
                    item_key=f"session-snapshot:{path}",
                    status_key=status_key,
                    status_label=status_label,
                    category_key="session_snapshot",
                    category_label="Session Profile Snapshot",
                    label=path.name,
                    path=str(path),
                    bytes_on_disk=self._session_snapshot_size(path),
                    profile_name=profile_name,
                    profile_path=profile_path,
                    reason=reason,
                    recommended=recommended,
                    warning_required=warning_required,
                    warning=warning,
                    metadata={
                        "cleanup_kind": "session_snapshot",
                        "stored_path": str(path),
                    },
                )
            )
        return items

    def _audit_generated_files(self) -> list[StorageAdminItem]:
        items: list[StorageAdminItem] = []
        for root, category_key, category_label, reason in (
            (
                self.layout.exports_dir,
                "export_file",
                "Export File",
                "Exports are application-generated outputs. They are not automatically linked to live catalog references.",
            ),
            (
                self.layout.logs_dir,
                "log_file",
                "Log File",
                "Log files are retained for diagnostics and support, but they are not required by live catalog data.",
            ),
        ):
            if not root.exists():
                continue
            for path in sorted(path for path in root.rglob("*") if path.is_file()):
                items.append(
                    StorageAdminItem(
                        item_key=f"generated:{path}",
                        status_key=STATUS_OTHER,
                        status_label="Other App-Managed File",
                        category_key=category_key,
                        category_label=category_label,
                        label=path.name,
                        path=str(path),
                        bytes_on_disk=self._path_size(path),
                        profile_name=None,
                        profile_path=None,
                        reason=reason,
                        recommended=False,
                        warning_required=False,
                        metadata={
                            "cleanup_kind": "direct_path",
                            "stored_path": str(path),
                        },
                    )
                )
        return items

    def _build_summary(
        self,
        *,
        items: list[StorageAdminItem],
        active_profiles: list[str],
        current_profile: str | None,
        current_profile_name: str | None,
    ) -> StorageAdminSummary:
        listed_item_bytes = sum(int(item.bytes_on_disk or 0) for item in items)
        total_app_bytes = self._path_size(self.layout.data_root) + sum(
            int(item.bytes_on_disk or 0)
            for item in items
            if not self._path_is_under(Path(item.path), self.layout.data_root)
        )
        current_profile_bytes = 0
        if current_profile:
            current_profile_bytes += self._profile_bundle_size(Path(current_profile))
        for item in items:
            if current_profile and self._item_belongs_to_profile(item, current_profile):
                current_profile_bytes += int(item.bytes_on_disk or 0)
        reclaimable_items = [item for item in items if item.recommended]
        warning_items = [item for item in items if item.warning_required]
        return StorageAdminSummary(
            total_app_bytes=total_app_bytes,
            listed_item_bytes=listed_item_bytes,
            current_profile_bytes=current_profile_bytes,
            reclaimable_bytes=sum(int(item.bytes_on_disk or 0) for item in reclaimable_items),
            deleted_profile_bytes=sum(
                int(item.bytes_on_disk or 0)
                for item in items
                if item.status_key == STATUS_DELETED_PROFILE
            ),
            orphaned_bytes=sum(
                int(item.bytes_on_disk or 0) for item in items if item.status_key == STATUS_ORPHANED
            ),
            warning_bytes=sum(int(item.bytes_on_disk or 0) for item in warning_items),
            in_use_bytes=sum(
                int(item.bytes_on_disk or 0) for item in items if item.status_key == STATUS_IN_USE
            ),
            recoverability_bytes=sum(
                int(item.bytes_on_disk or 0)
                for item in items
                if item.status_key == STATUS_RECOVERABILITY
            ),
            other_bytes=sum(
                int(item.bytes_on_disk or 0) for item in items if item.status_key == STATUS_OTHER
            ),
            total_items=len(items),
            reclaimable_items=len(reclaimable_items),
            warning_items=len(warning_items),
            current_profile_name=current_profile_name,
        )

    def _cleanup_item(
        self,
        item: StorageAdminItem,
        *,
        session_manager: SessionHistoryManager,
        history_contexts: dict[
            str, tuple[sqlite3.Connection, HistoryManager, HistoryStorageCleanupService]
        ],
        removed_history_entry_ids: set[int],
        removed_session_entry_ids: set[int],
    ) -> list[str]:
        cleanup_kind = str(item.metadata.get("cleanup_kind") or "")
        if cleanup_kind == "update_backup":
            target = Path(str(item.metadata.get("stored_path") or item.path))
            self._remove_direct_path(target)
            if bool(item.metadata.get("handoff_backup")):
                state_path = str(item.metadata.get("handoff_state_path") or "").strip()
                if state_path:
                    mark_update_backup_destroyed(
                        state_path=state_path,
                        reason="Update backup deleted from Application Storage Admin.",
                    )
            return [str(target)]

        if cleanup_kind == "direct_path":
            target = Path(str(item.metadata.get("stored_path") or item.path))
            self._remove_direct_path(target)
            return [str(target)]

        if cleanup_kind == "session_snapshot":
            snapshot_path = Path(str(item.metadata.get("stored_path") or item.path))
            entry_ids = session_manager.remove_entries_for_snapshot(snapshot_path)
            removed_session_entry_ids.update(int(entry_id) for entry_id in entry_ids)
            removed: list[str] = []
            for suffix in self._SESSION_SNAPSHOT_SUFFIXES:
                path = Path(str(snapshot_path) + suffix) if suffix else snapshot_path
                if path.exists():
                    path.unlink()
                    removed.append(str(path))
            return removed

        if cleanup_kind == "history_item":
            profile_path = str(item.metadata.get("profile_path") or item.profile_path or "").strip()
            if not profile_path:
                raise ValueError(
                    f"History cleanup item is missing its profile path: {item.item_key}"
                )
            conn, manager, cleanup_service = self._history_context(profile_path, history_contexts)
            history_item_type = str(item.metadata.get("history_item_type") or "")
            if item.warning_required:
                entry_ids = self._quarantine_referencing_history_entries(
                    manager,
                    history_item_type=history_item_type,
                    item=item,
                )
                removed_history_entry_ids.update(entry_ids)
            record_id = item.metadata.get("record_id")
            if history_item_type == "snapshot_record":
                if record_id is None:
                    raise ValueError(
                        f"Snapshot cleanup item is missing its record id: {item.item_key}"
                    )
                manager._remove_snapshot_record(int(record_id))
                manager._ensure_history_invariants()
                return [item.path]
            if history_item_type == "backup_record":
                if record_id is None:
                    raise ValueError(
                        f"Backup cleanup item is missing its record id: {item.item_key}"
                    )
                cleanup_service.cleanup_selected([f"backup_record:{int(record_id)}"])
                return [item.path]
            if history_item_type == "orphan_snapshot_file":
                cleanup_service.cleanup_selected([f"orphan_snapshot_file:{item.path}"])
                return [item.path]
            if history_item_type == "snapshot_archive":
                target_path = Path(item.path)
                cleanup_service._remove_snapshot_bundle(target_path)
                manager._ensure_history_invariants()
                return [str(target_path)]
            if history_item_type == "file_state_bundle":
                target_path = Path(item.path)
                manager._remove_path(target_path)
                manager._ensure_history_invariants()
                return [str(target_path)]
            raise ValueError(f"Unsupported history cleanup item type: {history_item_type}")

        raise ValueError(f"Unsupported cleanup kind: {cleanup_kind}")

    def _history_context(
        self,
        profile_path: str,
        history_contexts: dict[
            str, tuple[sqlite3.Connection, HistoryManager, HistoryStorageCleanupService]
        ],
    ) -> tuple[sqlite3.Connection, HistoryManager, HistoryStorageCleanupService]:
        cached = history_contexts.get(profile_path)
        if cached is not None:
            return cached
        conn = sqlite3.connect(profile_path)
        manager = HistoryManager(
            conn,
            self._history_settings(),
            profile_path,
            self.layout.history_dir,
            self.layout.data_root,
            self.layout.backups_dir,
        )
        cleanup_service = HistoryStorageCleanupService(manager)
        history_contexts[profile_path] = (conn, manager, cleanup_service)
        return conn, manager, cleanup_service

    def _history_settings(self):
        if QSettings is None:
            raise RuntimeError("Qt settings are required for history cleanup.")
        settings = QSettings(str(self.layout.settings_path), QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        return settings

    def _quarantine_referencing_history_entries(
        self,
        manager: HistoryManager,
        *,
        history_item_type: str,
        item: StorageAdminItem,
    ) -> list[int]:
        if history_item_type == "snapshot_record":
            record_id = int(item.metadata.get("record_id") or 0)
            entry_ids = manager._quarantine_artifact_references(snapshot_ids={record_id})
        elif history_item_type == "snapshot_archive":
            target_path = Path(item.path)
            entry_ids = manager._quarantine_artifact_references(
                artifact_roots=(target_path, target_path.with_suffix(".assets")),
            )
        elif history_item_type == "file_state_bundle":
            entry_ids = manager._quarantine_artifact_references(
                artifact_roots=(Path(item.path),),
            )
        else:
            entry_ids = []
        manager._ensure_history_invariants()
        return sorted(set(entry_ids))

    def _table_names(self, conn: sqlite3.Connection) -> set[str]:
        return {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if row and row[0]
        }

    def _table_has_columns(
        self,
        conn: sqlite3.Connection,
        table: str,
        columns: tuple[str, ...],
    ) -> bool:
        tables = self._table_names(conn)
        if table not in tables:
            return False
        available_columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            if row and row[1]
        }
        return all(column in available_columns for column in columns)

    def _display_reference_name(
        self,
        *,
        row_id: int,
        name: str,
        detail_template: str,
    ) -> str:
        clean_name = str(name or "").strip()
        return detail_template.format(row_id=int(row_id), name=clean_name or "Untitled")

    def _format_reference_reason(self, references: tuple[StorageAdminReference, ...]) -> str:
        unique_profiles = sorted(
            {reference.profile_name for reference in references if reference.profile_name}
        )
        summary = (
            f"Referenced by {len(unique_profiles)} active profile(s)."
            if len(unique_profiles) > 1
            else (
                f"Referenced by active profile {unique_profiles[0]}."
                if unique_profiles
                else "Referenced by an active profile."
            )
        )
        owners = [reference.owner_label for reference in references[:5] if reference.owner_label]
        if not owners:
            return summary
        suffix = "\n".join(owners)
        return f"{summary}\n{suffix}"

    def _profile_name_from_references(
        self, references: tuple[StorageAdminReference, ...]
    ) -> str | None:
        unique_names = sorted(
            {reference.profile_name for reference in references if reference.profile_name}
        )
        if not unique_names:
            return None
        if len(unique_names) == 1:
            return unique_names[0]
        return f"{len(unique_names)} active profiles"

    def _profile_path_from_references(
        self, references: tuple[StorageAdminReference, ...]
    ) -> str | None:
        unique_paths = sorted(
            {reference.profile_path for reference in references if reference.profile_path}
        )
        if len(unique_paths) == 1:
            return unique_paths[0]
        return None

    def _item_belongs_to_profile(self, item: StorageAdminItem, profile_path: str) -> bool:
        if str(item.profile_path or "").strip() == str(profile_path):
            return True
        return any(reference.profile_path == str(profile_path) for reference in item.references)

    @staticmethod
    def _path_identity(path: str | Path) -> str:
        try:
            return str(Path(path).expanduser().resolve())
        except Exception:
            return str(path)

    @staticmethod
    def _path_is_under(path: Path, root: Path) -> bool:
        try:
            candidate = path.expanduser().resolve()
            root_path = root.expanduser().resolve()
            candidate.relative_to(root_path)
            return True
        except Exception:
            return False

    @staticmethod
    def _normalize_existing_path(path: object | None) -> str | None:
        clean = str(path or "").strip()
        if not clean:
            return None
        return str(Path(clean).resolve())

    @staticmethod
    def _normalize_stored_path(path: object | None) -> str:
        clean = str(path or "").strip()
        if not clean:
            return ""
        return str(Path(clean))

    @staticmethod
    def _load_json(value: object | None) -> dict | list | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            raw = json.loads(text)
        except Exception:
            return None
        if isinstance(raw, (dict, list)):
            return raw
        return None

    @staticmethod
    def _load_json_sidecar(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _collect_int_values(payload: object | None, key: str) -> set[int]:
        values: set[int] = set()
        if isinstance(payload, dict):
            for payload_key, payload_value in payload.items():
                if payload_key == key:
                    try:
                        values.add(int(payload_value))
                    except Exception:
                        pass
                values.update(
                    ApplicationStorageAdminService._collect_int_values(payload_value, key)
                )
            return values
        if isinstance(payload, list):
            for item in payload:
                values.update(ApplicationStorageAdminService._collect_int_values(item, key))
        return values

    @staticmethod
    def _paths_under_root(payload: object | None, root: Path) -> set[Path]:
        if payload is None:
            return set()
        results: set[Path] = set()
        root_resolved = root.resolve()

        def _walk(value: object) -> None:
            if isinstance(value, dict):
                for nested in value.values():
                    _walk(nested)
                return
            if isinstance(value, list):
                for nested in value:
                    _walk(nested)
                return
            if not isinstance(value, str):
                return
            clean = value.strip()
            if not clean:
                return
            try:
                candidate = Path(clean)
                candidate_resolved = candidate.resolve()
            except Exception:
                return
            try:
                candidate_resolved.relative_to(root_resolved)
            except Exception:
                return
            results.add(candidate_resolved)

        _walk(payload)
        return results

    @staticmethod
    def _path_is_referenced(path: Path, live_paths: set[Path]) -> bool:
        try:
            target = path.resolve()
        except Exception:
            target = path
        bundle_root = target if target.is_dir() else target.with_suffix(".assets")
        for live_path in live_paths:
            try:
                candidate = live_path.resolve()
            except Exception:
                candidate = live_path
            if candidate == target:
                return True
            if bundle_root.exists():
                try:
                    candidate.relative_to(bundle_root.resolve())
                    return True
                except Exception:
                    pass
            if target.is_dir():
                try:
                    candidate.relative_to(target)
                    return True
                except Exception:
                    pass
        return False

    @staticmethod
    def _snapshot_sidecar_path(snapshot_path: Path) -> Path:
        return snapshot_path.with_suffix(
            snapshot_path.suffix + HistoryManager.SNAPSHOT_SIDECAR_SUFFIX
        )

    @staticmethod
    def _backup_sidecar_path(backup_path: Path) -> Path:
        return backup_path.with_suffix(backup_path.suffix + HistoryManager.BACKUP_SIDECAR_SUFFIX)

    @classmethod
    def _orphan_snapshot_bundle_roots(cls, *roots: Path) -> list[Path]:
        bundle_roots: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(
                candidate for candidate in root.glob("*.assets") if candidate.is_dir()
            ):
                if path.with_suffix(".db").exists():
                    continue
                bundle_roots.append(path)
        return bundle_roots

    @classmethod
    def _orphan_snapshot_companion_files(cls, *roots: Path) -> list[Path]:
        files: list[Path] = []
        for root in roots:
            files.extend(cls._orphan_database_companion_files_under_root(root))
            files.extend(
                cls._orphan_sidecar_files_under_root(
                    root,
                    suffix=HistoryManager.SNAPSHOT_SIDECAR_SUFFIX,
                )
            )
        return sorted(files)

    def _orphan_backup_companion_files(self) -> list[Path]:
        return self._orphan_database_companion_files_under_root(self.layout.backups_dir)

    @staticmethod
    def _orphan_database_companion_files_under_root(root: Path) -> list[Path]:
        if not root.exists():
            return []
        files: list[Path] = []
        for suffix in HistoryManager.DATABASE_ARTIFACT_COMPANION_SUFFIXES:
            for path in root.rglob(f"*{suffix}"):
                if not path.is_file():
                    continue
                base_path = Path(str(path)[: -len(suffix)])
                if base_path.exists():
                    continue
                files.append(path)
        for path in root.rglob(f"*{HistoryManager.BACKUP_SIDECAR_SUFFIX}"):
            if not path.is_file():
                continue
            base_path = Path(str(path)[: -len(HistoryManager.BACKUP_SIDECAR_SUFFIX)])
            if base_path.exists():
                continue
            files.append(path)
        return sorted(dict.fromkeys(files))

    @staticmethod
    def _orphan_sidecar_files_under_root(root: Path, *, suffix: str) -> list[Path]:
        if not root.exists():
            return []
        files: list[Path] = []
        for path in root.rglob(f"*{suffix}"):
            if not path.is_file():
                continue
            base_path = Path(str(path)[: -len(suffix)])
            if base_path.exists():
                continue
            files.append(path)
        return sorted(files)

    @staticmethod
    def _managed_manifest_size(manifest: object | None) -> int:
        if not isinstance(manifest, dict):
            return 0
        total = 0
        managed_dirs = manifest.get("managed_directories") or {}
        if isinstance(managed_dirs, dict):
            for state in managed_dirs.values():
                if not isinstance(state, dict):
                    continue
                snapshot_path = str(state.get("snapshot_path") or "").strip()
                if snapshot_path:
                    total += ApplicationStorageAdminService._path_size(Path(snapshot_path))
        return total

    @staticmethod
    def _path_size(path: Path) -> int:
        if not path.exists() and not path.is_symlink():
            return 0
        if path.is_symlink():
            try:
                return int(path.stat().st_size)
            except Exception:
                return 0
        if path.is_file():
            try:
                return int(path.stat().st_size)
            except Exception:
                return 0
        total = 0
        try:
            for child in path.rglob("*"):
                if child.is_file():
                    try:
                        total += int(child.stat().st_size)
                    except Exception:
                        pass
        except Exception:
            pass
        return total

    @classmethod
    def _session_snapshot_size(cls, snapshot_path: Path) -> int:
        total = 0
        for suffix in cls._SESSION_SNAPSHOT_SUFFIXES:
            candidate = Path(str(snapshot_path) + suffix) if suffix else snapshot_path
            total += cls._path_size(candidate)
        return total

    @staticmethod
    def _profile_bundle_size(profile_path: Path) -> int:
        total = ApplicationStorageAdminService._path_size(profile_path)
        total += ApplicationStorageAdminService._path_size(Path(str(profile_path) + ".wal"))
        total += ApplicationStorageAdminService._path_size(Path(str(profile_path) + ".shm"))
        return total

    @staticmethod
    def _remove_direct_path(path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        if path.is_dir() and not path.is_symlink():
            for child in sorted(path.iterdir(), key=lambda candidate: str(candidate), reverse=True):
                ApplicationStorageAdminService._remove_direct_path(child)
            path.rmdir()
            return
        path.unlink()

    @staticmethod
    def _report(
        progress_callback: Callable[[int, int, str], None] | None,
        value: int,
        maximum: int,
        message: str,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(int(value), int(maximum), str(message or ""))
