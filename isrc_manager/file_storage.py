"""Shared helpers for dual database/blob and managed-file attachment storage."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from collections.abc import Iterable
from pathlib import Path

STORAGE_MODE_DATABASE = "database"
STORAGE_MODE_MANAGED_FILE = "managed_file"
VALID_STORAGE_MODES = {STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE}

_FILENAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_EXPORT_BASENAME_SANITIZE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_EXPORT_BASENAME_WHITESPACE_RE = re.compile(r"\s+")


def normalize_storage_mode(value: str | None, *, default: str | None = None) -> str | None:
    clean = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not clean:
        return default
    if clean in {"database", "db", "blob"}:
        return STORAGE_MODE_DATABASE
    if clean in {
        "managed_file",
        "managed_path",
        "managed_local_file",
        "managed_file_path",
        "file",
        "path",
    }:
        return STORAGE_MODE_MANAGED_FILE
    raise ValueError(f"Unsupported storage mode: {value}")


def has_blob_value(blob_value: object | None) -> bool:
    return blob_value is not None


def infer_storage_mode(
    *,
    explicit_mode: str | None = None,
    stored_path: str | None = None,
    blob_value: object | None = None,
    default: str | None = None,
) -> str | None:
    normalized = normalize_storage_mode(explicit_mode, default=None)
    if normalized is not None:
        return normalized
    if str(stored_path or "").strip():
        return STORAGE_MODE_MANAGED_FILE
    if has_blob_value(blob_value):
        return STORAGE_MODE_DATABASE
    return default


def sanitize_filename(filename: str | None, *, default_stem: str = "file") -> str:
    clean_name = Path(str(filename or "").strip()).name
    if not clean_name or clean_name in {".", ".."}:
        clean_name = default_stem
    stem = _FILENAME_SANITIZE_RE.sub("_", Path(clean_name).stem).strip("._-") or default_stem
    suffix = _FILENAME_SANITIZE_RE.sub("", Path(clean_name).suffix)
    return f"{stem}{suffix}" if suffix else stem


def sanitize_export_basename(value: str | None, *, default_stem: str = "file") -> str:
    """Sanitize a user-facing export basename without altering leading letters."""

    clean = str(value or "").strip()
    if not clean:
        clean = default_stem
    clean = _EXPORT_BASENAME_SANITIZE_RE.sub("_", clean)
    clean = _EXPORT_BASENAME_WHITESPACE_RE.sub(" ", clean).strip().rstrip(".")
    return clean or default_stem


def export_package_name(value: str | None, *, default_stem: str = "Release") -> str:
    return sanitize_export_basename(value, default_stem=default_stem)


def common_export_package_name(
    values: Iterable[str | None],
    *,
    default_stem: str = "Release",
    mixed_stem: str = "Selected Releases",
) -> str:
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        if not clean:
            continue
        folded = clean.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        unique_values.append(clean)
    if len(unique_values) == 1:
        return export_package_name(unique_values[0], default_stem=default_stem)
    if unique_values:
        return export_package_name(mixed_stem, default_stem=default_stem)
    return export_package_name(default_stem, default_stem=default_stem)


def deduplicate_export_path(target_path: str | Path) -> Path:
    target = Path(target_path)
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    index = 2
    while True:
        candidate = target.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def coalesce_filename(
    filename: str | None,
    *,
    stored_path: str | None = None,
    default_stem: str = "file",
    default_suffix: str = "",
) -> str:
    clean = str(filename or "").strip()
    if clean:
        return sanitize_filename(clean, default_stem=default_stem)
    path_name = Path(str(stored_path or "").strip()).name
    if path_name:
        return sanitize_filename(path_name, default_stem=default_stem)
    fallback = sanitize_filename(default_stem, default_stem=default_stem)
    if default_suffix and not fallback.endswith(default_suffix):
        return f"{fallback}{default_suffix}"
    return fallback


def resolve_file_export_target(
    target_path: str | Path,
    *,
    default_name: str,
    default_suffix: str = "",
) -> Path:
    """Resolve a save-dialog selection into a concrete file target."""

    clean_target = str(target_path or "").strip()
    if not clean_target:
        raise ValueError("Export target path is required.")

    target = Path(clean_target).expanduser()
    normalized_suffix = str(default_suffix or "").strip()
    if normalized_suffix and not normalized_suffix.startswith("."):
        normalized_suffix = f".{normalized_suffix}"
    default_filename = coalesce_filename(
        default_name,
        default_stem="export",
        default_suffix=normalized_suffix,
    )

    if target.exists() and target.is_dir():
        target = target / default_filename
    elif normalized_suffix and not target.suffix:
        target = target.with_suffix(normalized_suffix)

    if target.name in {"", ".", ".."}:
        raise ValueError("Export target must resolve to a file path.")
    return target


def resolve_directory_export_target(target_path: str | Path, *, default_name: str) -> Path:
    """Resolve a directory-picker selection into a concrete export folder."""

    clean_target = str(target_path or "").strip()
    if not clean_target:
        raise ValueError("Export target directory is required.")

    target = Path(clean_target).expanduser()
    safe_name = sanitize_export_basename(default_name, default_stem="export")
    if target.exists() and target.is_dir():
        target = target / safe_name
    if target.name in {"", ".", ".."}:
        raise ValueError("Export target must resolve to a directory path.")
    return target


def guess_mime_type(filename: str | None, fallback: str | None = None) -> str:
    clean_name = str(filename or "").strip()
    if clean_name:
        mime = mimetypes.guess_type(clean_name)[0] or ""
        if mime:
            return mime
    return str(fallback or "").strip()


def bytes_from_blob(blob_value: object | None) -> bytes:
    if blob_value is None:
        return b""
    if isinstance(blob_value, bytes):
        return blob_value
    if isinstance(blob_value, bytearray):
        return bytes(blob_value)
    if isinstance(blob_value, memoryview):
        return blob_value.tobytes()
    return bytes(blob_value)


def sha256_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ManagedFileStorage:
    """Writes managed files using stable, collision-safe names."""

    def __init__(self, *, data_root: str | Path | None, relative_root: str | Path):
        self.data_root = Path(data_root) if data_root is not None else None
        self.relative_root = Path(relative_root)

    @property
    def root_path(self) -> Path | None:
        if self.data_root is None:
            return None
        return self.data_root / self.relative_root

    def resolve(self, stored_path: str | None) -> Path | None:
        clean_path = str(stored_path or "").strip()
        if not clean_path:
            return None
        path = Path(clean_path)
        if path.is_absolute():
            return path
        if self.data_root is None:
            return None
        return self.data_root / path

    def is_managed(self, stored_path: str | None) -> bool:
        clean_path = str(stored_path or "").strip()
        if not clean_path or self.data_root is None:
            return False
        if Path(clean_path).is_absolute():
            return False
        root_path = self.root_path
        if root_path is None:
            return False
        try:
            (self.data_root / clean_path).resolve().relative_to(root_path.resolve())
            return True
        except Exception:
            return False

    def write_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        subdir: str | Path | None = None,
    ) -> str:
        if self.data_root is None:
            raise ValueError("Managed file storage is not configured")
        safe_name = coalesce_filename(filename, default_stem="file")
        digest = sha256_digest(data)[:12]
        destination_dir = self.root_path
        if destination_dir is None:
            raise ValueError("Managed file storage is not configured")
        if subdir:
            destination_dir = destination_dir / Path(subdir)
        destination_dir.mkdir(parents=True, exist_ok=True)

        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix
        destination = destination_dir / f"{digest}_{safe_name}"
        suffix_index = 2
        while destination.exists():
            try:
                if destination.read_bytes() == data:
                    return str(destination.relative_to(self.data_root))
            except Exception:
                pass
            destination = destination_dir / f"{digest}_{stem}_{suffix_index}{suffix}"
            suffix_index += 1

        destination.write_bytes(data)
        return str(destination.relative_to(self.data_root))
