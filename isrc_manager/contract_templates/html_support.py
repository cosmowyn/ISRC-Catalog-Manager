"""Helpers for native HTML template scanning, bundle storage, and ZIP import."""

from __future__ import annotations

import html as html_module
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable
from zipfile import ZipFile

from isrc_manager.file_storage import ManagedFileStorage

from .models import (
    ContractTemplateScanEntry,
    ContractTemplateScanOccurrence,
    ContractTemplateScanResult,
)
from .parser import extract_placeholders

HTML_SOURCE_FORMAT = "html"
HTML_BUNDLE_METADATA_KEY = "html_bundle"
HTML_DIAGNOSTICS_KEY = "diagnostics"
HTML_TEMPLATE_SUFFIXES = frozenset({".html", ".htm"})


def decode_html_bytes(source_bytes: bytes) -> str:
    return bytes(source_bytes or b"").decode("utf-8-sig", errors="replace")


def replace_html_placeholders(html_text: str, replacements: dict[str, str]) -> str:
    rendered = str(html_text or "")
    for token in sorted(replacements, key=len, reverse=True):
        rendered = rendered.replace(
            token,
            html_module.escape(str(replacements[token] or ""), quote=True),
        )
    return rendered


def _ingestion_error(message: str) -> RuntimeError:
    from .ingestion import ContractTemplateIngestionError

    return ContractTemplateIngestionError(message)


class HTMLTemplateBundleError(RuntimeError):
    """Raised when an HTML bundle cannot be inspected or materialized safely."""


@dataclass(frozen=True, slots=True)
class HTMLBundleFile:
    relative_path: str
    data: bytes


@dataclass(frozen=True, slots=True)
class HTMLTemplateBundle:
    primary_relative_path: str
    files: tuple[HTMLBundleFile, ...]
    import_kind: str = "html_file"
    package_filename: str | None = None

    @property
    def primary_filename(self) -> str:
        return Path(self.primary_relative_path).name

    def primary_bytes(self) -> bytes:
        for item in self.files:
            if item.relative_path == self.primary_relative_path:
                return item.data
        raise _ingestion_error(
            f"Primary HTML file {self.primary_relative_path!r} was not found in the bundle."
        )


class HTMLTemplateScanner:
    """Scans HTML source text directly for canonical placeholder tokens."""

    adapter_name = "html_source_direct"

    def scan_bytes(
        self,
        source_bytes: bytes,
        *,
        source_filename: str | None = None,
    ) -> ContractTemplateScanResult:
        text = source_bytes.decode("utf-8", errors="replace")
        source_part = str(source_filename or "document.html").strip() or "document.html"
        placeholder_map: dict[str, dict[str, object]] = {}
        for occurrence in extract_placeholders(text):
            token = occurrence.token
            bucket = placeholder_map.setdefault(
                token.canonical_symbol,
                {
                    "binding_kind": token.binding_kind,
                    "namespace": token.namespace,
                    "key": token.key,
                    "occurrences": [],
                },
            )
            bucket["occurrences"].append(
                ContractTemplateScanOccurrence(
                    source_part=source_part,
                    container_kind="html",
                    container_index=1,
                    start_index=occurrence.start_index,
                    end_index=occurrence.end_index,
                    raw_text=occurrence.raw_text,
                )
            )
        placeholders = tuple(
            ContractTemplateScanEntry(
                canonical_symbol=canonical_symbol,
                binding_kind=str(entry["binding_kind"]),
                namespace=entry["namespace"],
                key=str(entry["key"]),
                occurrence_count=len(entry["occurrences"]),
                occurrences=tuple(entry["occurrences"]),
            )
            for canonical_symbol, entry in sorted(placeholder_map.items())
        )
        return ContractTemplateScanResult(
            source_format=HTML_SOURCE_FORMAT,
            scan_format=HTML_SOURCE_FORMAT,
            scan_status="scan_ready",
            scan_adapter=self.adapter_name,
            placeholders=placeholders,
            diagnostics=(),
        )


def is_html_source_format(value: str | None) -> bool:
    return str(value or "").strip().lower() == HTML_SOURCE_FORMAT


def build_html_bundle_from_source_bytes(
    source_bytes: bytes,
    *,
    source_filename: str,
) -> HTMLTemplateBundle:
    relative_path = normalize_bundle_relative_path(source_filename)
    if relative_path is None:
        raise _ingestion_error("HTML template source requires a filename.")
    return HTMLTemplateBundle(
        primary_relative_path=relative_path,
        files=(HTMLBundleFile(relative_path=relative_path, data=bytes(source_bytes)),),
        import_kind="html_file",
    )


def build_html_bundle_from_zip_path(package_path: str | Path) -> HTMLTemplateBundle:
    package = Path(str(package_path or "").strip())
    if not package.exists():
        raise FileNotFoundError(package)
    with ZipFile(package) as archive:
        return build_html_bundle_from_zip_archive(
            archive,
            package_filename=package.name,
        )


def build_html_bundle_from_zip_bytes(
    package_bytes: bytes,
    *,
    package_filename: str | None = None,
) -> HTMLTemplateBundle:
    from io import BytesIO

    with ZipFile(BytesIO(package_bytes)) as archive:
        return build_html_bundle_from_zip_archive(
            archive,
            package_filename=package_filename,
        )


def build_html_bundle_from_zip_archive(
    archive: ZipFile,
    *,
    package_filename: str | None = None,
) -> HTMLTemplateBundle:
    files: list[HTMLBundleFile] = []
    html_candidates: list[str] = []
    for name in archive.namelist():
        normalized = normalize_bundle_relative_path(name)
        if normalized is None:
            continue
        data = archive.read(name)
        files.append(HTMLBundleFile(relative_path=normalized, data=data))
        if Path(normalized).suffix.lower() in HTML_TEMPLATE_SUFFIXES:
            html_candidates.append(normalized)
    if not html_candidates:
        raise _ingestion_error("The ZIP package does not contain an HTML template file.")
    primary_relative_path = _choose_primary_html_path(html_candidates)
    return HTMLTemplateBundle(
        primary_relative_path=primary_relative_path,
        files=tuple(files),
        import_kind="zip_package",
        package_filename=str(package_filename or "").strip() or None,
    )


def normalize_bundle_relative_path(raw_path: str | Path) -> str | None:
    text = str(raw_path or "").replace("\\", "/").strip()
    if not text or text.endswith("/"):
        return None
    if text.startswith("__MACOSX/"):
        return None
    candidate = PurePosixPath(text)
    if candidate.is_absolute():
        raise _ingestion_error("HTML template package entries must use relative paths.")
    normalized_parts: list[str] = []
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise _ingestion_error("HTML template package entries must not escape the bundle root.")
        if part.startswith("._"):
            return None
        normalized_parts.append(part)
    if not normalized_parts:
        return None
    return "/".join(normalized_parts)


def write_html_bundle(
    store: ManagedFileStorage,
    bundle: HTMLTemplateBundle,
    *,
    bundle_subdir: str | Path,
) -> tuple[str, str]:
    root_path = store.root_path
    if root_path is None:
        raise ValueError("Managed file storage is not configured")
    bundle_root = root_path / Path(bundle_subdir)
    bundle_root.mkdir(parents=True, exist_ok=True)
    for item in bundle.files:
        destination = bundle_root / Path(item.relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(item.data)
    primary_path = bundle_root / Path(bundle.primary_relative_path)
    if not primary_path.exists():
        raise _ingestion_error(
            f"Primary HTML file {bundle.primary_relative_path!r} could not be written."
        )
    return (
        str(primary_path.relative_to(store.data_root)),
        str(bundle_root.relative_to(store.data_root)),
    )


def collect_html_bundle_from_directory(
    bundle_root: str | Path,
    *,
    primary_relative_path: str,
) -> HTMLTemplateBundle:
    root = Path(bundle_root)
    if not root.exists():
        raise FileNotFoundError(root)
    files: list[HTMLBundleFile] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        files.append(
            HTMLBundleFile(
                relative_path=path.relative_to(root).as_posix(),
                data=path.read_bytes(),
            )
        )
    if not files:
        raise _ingestion_error("The HTML bundle directory is empty.")
    return HTMLTemplateBundle(
        primary_relative_path=normalize_bundle_relative_path(primary_relative_path)
        or Path(primary_relative_path).name,
        files=tuple(files),
        import_kind="managed_bundle",
    )


def extract_html_package_archive(
    package_path: str | Path,
    destination_root: str | Path,
) -> tuple[Path, ...]:
    bundle = build_html_bundle_from_zip_path(package_path)
    root = Path(destination_root)
    root.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    for item in bundle.files:
        target = root / Path(item.relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.data)
        extracted.append(target)
    return tuple(extracted)


def choose_html_package_entrypoint(paths: Iterable[Path]) -> Path:
    candidates = [
        Path(item) for item in paths if Path(item).suffix.lower() in HTML_TEMPLATE_SUFFIXES
    ]
    if not candidates:
        raise _ingestion_error("The HTML template package does not contain an HTML entrypoint.")
    if len(candidates) == 1:
        return candidates[0]
    index_candidates = [
        item for item in candidates if item.name.lower() in {"index.html", "index.htm"}
    ]
    if len(index_candidates) == 1:
        return index_candidates[0]
    detail = ", ".join(sorted(str(item) for item in candidates))
    raise _ingestion_error(
        "The ZIP package contains multiple HTML files and the primary template is ambiguous: "
        f"{detail}"
    )


def clone_html_package_tree(
    *, source_package_root: str | Path, destination_root: str | Path
) -> None:
    source_root = Path(source_package_root)
    destination = Path(destination_root)
    if not source_root.exists():
        raise FileNotFoundError(source_root)
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source_root.rglob("*")):
        relative = item.relative_to(source_root)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def copy_html_template_with_local_assets(
    *,
    source_html_path: str | Path,
    destination_root: str | Path,
    source_root: str | Path | None = None,
) -> Path:
    source_html = Path(source_html_path)
    if not source_html.exists():
        raise FileNotFoundError(source_html)
    destination = Path(destination_root)
    destination.mkdir(parents=True, exist_ok=True)
    resolved_root = Path(source_root).resolve() if source_root is not None else None
    try:
        relative = (
            source_html.resolve().relative_to(resolved_root)
            if resolved_root is not None
            else Path(source_html.name)
        )
    except Exception:
        relative = Path(source_html.name)
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_html, target)
    return target


def build_scan_diagnostics_payload(
    diagnostics: Iterable[object] | None,
    *,
    html_bundle: dict[str, object] | None = None,
) -> object | None:
    diagnostic_items = list(diagnostics or [])
    if html_bundle:
        return {
            HTML_DIAGNOSTICS_KEY: diagnostic_items,
            HTML_BUNDLE_METADATA_KEY: dict(html_bundle),
        }
    return diagnostic_items or None


def scan_diagnostic_entries(payload: object | None) -> tuple[object, ...]:
    if isinstance(payload, dict):
        return tuple(payload.get(HTML_DIAGNOSTICS_KEY) or ())
    if isinstance(payload, (list, tuple)):
        return tuple(payload)
    return ()


def html_bundle_metadata(payload: object | None) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    bundle = payload.get(HTML_BUNDLE_METADATA_KEY)
    if not isinstance(bundle, dict):
        return None
    return dict(bundle)


def _choose_primary_html_path(candidates: list[str]) -> str:
    if len(candidates) == 1:
        return candidates[0]
    preferred = [
        item for item in candidates if Path(item).name.lower() in {"index.html", "index.htm"}
    ]
    if len(preferred) == 1:
        return preferred[0]
    detail = ", ".join(sorted(candidates))
    raise _ingestion_error(
        "The ZIP package contains multiple HTML files and the primary template is ambiguous: "
        f"{detail}"
    )
