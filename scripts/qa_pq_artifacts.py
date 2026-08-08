"""Prepare and finalize provenance-safe incremental UI QA/PQ artifact bundles."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scripts import qa_pq_fingerprints as _fingerprints
    from scripts import qa_pq_provenance as _provenance
    from scripts import qa_pq_runtime as _runtime
elif __package__:
    from . import qa_pq_fingerprints as _fingerprints
    from . import qa_pq_provenance as _provenance
    from . import qa_pq_runtime as _runtime
else:
    import qa_pq_fingerprints as _fingerprints  # type: ignore[import-not-found,no-redef]
    import qa_pq_provenance as _provenance  # type: ignore[import-not-found,no-redef]
    import qa_pq_runtime as _runtime  # type: ignore[import-not-found,no-redef]

FingerprintDefinitionError = _fingerprints.FingerprintDefinitionError
_fingerprint_all_targets: Callable[[Path], tuple[list[str], list[str]]] = _fingerprints.all_targets
_compute_input_fingerprints: Callable[[Path], dict[str, dict[str, str]]] = (
    _fingerprints.compute_input_fingerprints
)
_sha256_file = _fingerprints.sha256_file
_stable_hash = _fingerprints.stable_hash

SCHEMA_VERSION = 2
PROVENANCE_NAME = "provenance.json"
VISUAL_MANIFESTS = (
    "visual/visual_manifest.json",
    "visual/business_workflow_manifest.json",
    "visual/generated_output_manifest.json",
)
REQUIRED_BUNDLE_FILES = (
    "deviations.csv",
    "evidence.json",
    "summary.md",
    "traceability_matrix.csv",
    "ui_inventory.json",
)
COMPONENT_EVIDENCE_IDS: dict[str, tuple[str, ...]] = {
    "core-inventory": ("UI-PQ-INV-001", "UI-PQ-SMOKE-001", "UI-PQ-MENU-001"),
    "visual-help": ("UI-PQ-SET-001", "UI-PQ-HELP-001"),
    "catalog": ("UI-PQ-CAT-001",),
    "diagnostics-history-storage": ("UI-PQ-HIST-001", "UI-PQ-DIAG-001"),
    "relationships-releases-parties": ("UI-PQ-REL-001",),
    "contracts-rights": ("UI-PQ-CON-001",),
    "accounting": ("UI-PQ-ACC-001",),
    "soundcloud": ("UI-PQ-SC-001",),
    "imports-exports-reports": ("UI-PQ-IMP-001",),
    "assets": ("UI-PQ-ASSET-001",),
    "authenticity-forensics": ("UI-PQ-AUTH-001",),
    "media-audio": ("UI-PQ-MEDIA-001",),
}
EVIDENCE_ORDER = tuple(
    evidence_id
    for component in (
        "core-inventory",
        "visual-help",
        "catalog",
        "diagnostics-history-storage",
        "relationships-releases-parties",
        "contracts-rights",
        "accounting",
        "soundcloud",
        "imports-exports-reports",
        "assets",
        "authenticity-forensics",
        "media-audio",
    )
    for evidence_id in COMPONENT_EVIDENCE_IDS[component]
)
_BUSINESS_PREFIX_OWNERS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("ui_pq_add_track_", "ui_pq_edit_track_"), "catalog"),
    (
        (
            "ui_pq_party_",
            "ui_pq_work_",
            "ui_pq_release_",
            "ui_pq_promo_",
        ),
        "relationships-releases-parties",
    ),
    (("ui_pq_contract_", "ui_pq_rights_"), "contracts-rights"),
    (("accounting_",), "accounting"),
    (("soundcloud_",), "soundcloud"),
    (("ui_pq_asset_", "ui_pq_deliverable_"), "assets"),
    (("ui_pq_authenticity_", "ui_pq_forensic_"), "authenticity-forensics"),
    (
        (
            "ui_pq_bulk_audio_",
            "ui_pq_media_",
            "ui_pq_derivative_",
        ),
        "media-audio",
    ),
)
_BUSINESS_COMPONENTS = frozenset(component for _prefixes, component in _BUSINESS_PREFIX_OWNERS)


class ArtifactCompatibilityError(RuntimeError):
    """Raised when a bundle cannot be reused or safely combined."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactCompatibilityError(f"invalid JSON file {path}: {exc}") from exc


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compute_input_fingerprints(repo_root: Path) -> dict[str, dict[str, str]]:
    """Hash every canonical component and shared provenance-input group."""
    try:
        return _compute_input_fingerprints(repo_root)
    except FingerprintDefinitionError as exc:
        raise ArtifactCompatibilityError(str(exc)) from exc


def _all_targets(repo_root: Path) -> tuple[list[str], list[str]]:
    try:
        return _fingerprint_all_targets(repo_root)
    except FingerprintDefinitionError as exc:
        raise ArtifactCompatibilityError(str(exc)) from exc


def _locate_bundle_root(path: Path) -> Path:
    direct = path / PROVENANCE_NAME
    if direct.is_file():
        return path
    candidates = sorted(path.rglob(PROVENANCE_NAME)) if path.is_dir() else []
    if len(candidates) != 1:
        raise ArtifactCompatibilityError(
            f"expected one {PROVENANCE_NAME} below {path}, found {len(candidates)}"
        )
    return candidates[0].parent


def _required_plan_values(plan: Mapping[str, Any]) -> tuple[str, str, str, str]:
    try:
        return _provenance.required_plan_values(plan)
    except _provenance.ProvenanceValidationError as exc:
        raise ArtifactCompatibilityError(str(exc)) from exc


def _validate_baseline(
    baseline_root: Path,
    plan: Mapping[str, Any],
    fingerprints: Mapping[str, Any],
    *,
    baseline_source_commit: str,
) -> dict[str, Any]:
    validate_bundle_files(baseline_root)
    provenance = _read_json(baseline_root / PROVENANCE_NAME)
    try:
        return _provenance.validate_baseline_provenance(
            provenance,
            plan,
            fingerprints,
            attested_source_commit=baseline_source_commit,
            schema_version=SCHEMA_VERSION,
        )
    except _provenance.ProvenanceValidationError as exc:
        raise ArtifactCompatibilityError(str(exc)) from exc


def _safe_replace_output(
    output: Path,
    repo_root: Path,
    *,
    replace_output: bool,
    preserve_visual_baselines: bool = False,
) -> None:
    output_resolved = output.resolve()
    repo_resolved = repo_root.resolve()
    if output_resolved in {Path("/").resolve(), repo_resolved}:
        raise ArtifactCompatibilityError(f"refusing to replace broad output path: {output}")
    if output.is_symlink():
        raise ArtifactCompatibilityError(f"refusing to replace symlinked output path: {output}")
    if output.exists() and any(output.iterdir()):
        if not replace_output:
            raise ArtifactCompatibilityError(
                f"output is not empty: {output}; pass --replace-output explicitly"
            )
        baseline_source = output / "visual" / "baselines"
        with tempfile.TemporaryDirectory(prefix="qa-pq-baselines-") as temporary:
            preserved = Path(temporary) / "baselines"
            if preserve_visual_baselines and baseline_source.is_dir():
                if baseline_source.is_symlink() or any(
                    path.is_symlink() for path in baseline_source.rglob("*")
                ):
                    raise ArtifactCompatibilityError(
                        f"refusing to preserve symlinked visual baselines: {baseline_source}"
                    )
                shutil.copytree(baseline_source, preserved)
            shutil.rmtree(output)
            output.mkdir(parents=True, exist_ok=True)
            if preserved.is_dir():
                shutil.copytree(preserved, output / "visual" / "baselines")
        return
    output.mkdir(parents=True, exist_ok=True)


def _read_csv_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"fieldnames": [], "rows": []}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return {"fieldnames": list(reader.fieldnames or []), "rows": list(reader)}


def _baseline_state(root: Path, provenance: Mapping[str, Any]) -> dict[str, Any]:
    manifests: dict[str, Any] = {}
    for relative in VISUAL_MANIFESTS:
        path = root / relative
        manifests[relative] = _read_json(path) if path.is_file() else None
    evidence = _read_json(root / "evidence.json")
    if not isinstance(evidence, list):
        raise ArtifactCompatibilityError("baseline evidence.json must be a list")
    return {
        "provenance": dict(provenance),
        "evidence": evidence,
        "deviations": _read_csv_payload(root / "deviations.csv"),
        "manifests": manifests,
    }


def _write_github_outputs(path: Path, outputs: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for key, value in outputs.items():
            if isinstance(value, bool):
                serialized = str(value).lower()
            elif isinstance(value, (list, dict)):
                serialized = json.dumps(value, separators=(",", ":"), sort_keys=True)
            else:
                serialized = str(value)
            stream.write(f"{key}={serialized}\n")


def prepare_bundle(
    *,
    plan_path: Path,
    repo_root: Path,
    output: Path,
    state_path: Path,
    runtime_fingerprint_path: Path,
    baseline: Path | None = None,
    baseline_source_commit: str | None = None,
    replace_output: bool = False,
) -> dict[str, object]:
    """Validate/copy a reusable baseline or select a safe full-run fallback."""
    plan = _read_json(plan_path)
    if not isinstance(plan, dict):
        raise ArtifactCompatibilityError("impact plan must be a JSON object")
    _required_plan_values(plan)
    all_components, all_targets = _all_targets(repo_root)
    try:
        runtime_fingerprint = _runtime.load_runtime_fingerprint(runtime_fingerprint_path)
    except _runtime.RuntimeFingerprintError as exc:
        raise ArtifactCompatibilityError(str(exc)) from exc
    fingerprints: dict[str, Any] = {
        **compute_input_fingerprints(repo_root),
        "runtime": runtime_fingerprint,
    }
    planned_mode = str(plan.get("mode") or "full")
    selected = [str(name) for name in plan.get("selected_components", [])]
    targets = [str(target) for target in plan.get("test_targets", [])]
    baseline_payload: dict[str, Any] | None = None
    fallback_reason = ""

    if planned_mode != "full" and baseline is not None and not baseline_source_commit:
        fallback_reason = "baseline source-commit attestation is required"
    elif planned_mode != "full" and baseline is not None and baseline.exists():
        try:
            baseline_root = _locate_bundle_root(baseline)
            provenance = _validate_baseline(
                baseline_root,
                plan,
                fingerprints,
                baseline_source_commit=str(baseline_source_commit),
            )
            baseline_payload = _baseline_state(baseline_root, provenance)
        except ArtifactCompatibilityError as exc:
            fallback_reason = str(exc)
        else:
            _safe_replace_output(output, repo_root, replace_output=replace_output)
            shutil.copytree(baseline_root, output, dirs_exist_ok=True)
    elif planned_mode != "full":
        fallback_reason = "no prior canonical QA/PQ bundle was available"

    if planned_mode == "full" or baseline_payload is None:
        effective_mode = "full"
        selected = all_components
        targets = all_targets
        _safe_replace_output(
            output,
            repo_root,
            replace_output=replace_output,
            preserve_visual_baselines=True,
        )
    else:
        effective_mode = planned_mode

    run_tests = effective_mode != "none"
    state = {
        "schema_version": SCHEMA_VERSION,
        "plan": plan,
        "planned_mode": planned_mode,
        "effective_mode": effective_mode,
        "selected_components": selected,
        "test_targets": targets,
        "fingerprints": fingerprints,
        "baseline": baseline_payload,
        "fallback_reason": fallback_reason,
        "prepared_at": _utc_now(),
    }
    _write_json(state_path, state)
    return {
        "baseline_compatible": baseline_payload is not None,
        "effective_mode": effective_mode,
        "fallback_reason": fallback_reason,
        "runtime_fingerprint": runtime_fingerprint["fingerprint"],
        "has_visual_help": "visual-help" in selected,
        "run_tests": run_tests,
        "selected_components": selected,
        "test_targets": targets,
    }


def _selected_evidence_ids(components: Iterable[str]) -> set[str]:
    selected_ids: set[str] = set()
    for component in components:
        try:
            selected_ids.update(COMPONENT_EVIDENCE_IDS[component])
        except KeyError as exc:
            raise ArtifactCompatibilityError(f"unknown selected component: {component}") from exc
    return selected_ids


def _merge_evidence(
    baseline: Sequence[Mapping[str, Any]],
    fresh: Sequence[Mapping[str, Any]],
    selected_components: Sequence[str],
) -> list[dict[str, Any]]:
    selected_ids = _selected_evidence_ids(selected_components)
    fresh_ids = {str(event.get("test_id") or "") for event in fresh}
    missing = sorted(selected_ids - fresh_ids)
    if missing:
        raise ArtifactCompatibilityError(
            "selected qualification evidence is missing: " + ", ".join(missing)
        )
    merged = [
        dict(event) for event in baseline if str(event.get("test_id") or "") not in selected_ids
    ]
    merged.extend(dict(event) for event in fresh)
    order = {test_id: index for index, test_id in enumerate(EVIDENCE_ORDER)}
    merged.sort(key=lambda event: (order.get(str(event.get("test_id")), len(order)), str(event)))
    return merged


def _write_csv_payload(path: Path, payload: Mapping[str, Any]) -> None:
    rows = payload.get("rows", [])
    fieldnames = [str(name) for name in payload.get("fieldnames", [])]
    if not fieldnames:
        fieldnames = sorted({str(key) for row in rows for key in row})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        if not fieldnames:
            return
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _merge_deviations(
    baseline: Mapping[str, Any],
    fresh: Mapping[str, Any],
    selected_components: Sequence[str],
) -> dict[str, Any]:
    selected_ids = _selected_evidence_ids(selected_components)
    baseline_rows = baseline.get("rows", [])
    fresh_rows = fresh.get("rows", [])
    rows = [row for row in baseline_rows if str(row.get("test_id") or "") not in selected_ids]
    rows.extend(fresh_rows)
    fieldnames = list(baseline.get("fieldnames", []))
    for field in fresh.get("fieldnames", []):
        if field not in fieldnames:
            fieldnames.append(field)
    return {"fieldnames": fieldnames, "rows": rows}


def _business_owner(name: str) -> str | None:
    for prefixes, component in _BUSINESS_PREFIX_OWNERS:
        if name.startswith(prefixes):
            return component
    return None


def _merge_named_records(
    baseline: Sequence[Mapping[str, Any]],
    fresh: Sequence[Mapping[str, Any]],
    selected_components: set[str],
) -> list[dict[str, Any]]:
    for record in fresh:
        name = str(record.get("name") or "")
        owner = _business_owner(name)
        if owner is None or owner not in selected_components:
            raise ArtifactCompatibilityError(
                f"fresh business manifest entry {name!r} has no selected component owner"
            )
    merged = {
        str(record.get("name") or ""): dict(record)
        for record in baseline
        if _business_owner(str(record.get("name") or "")) not in selected_components
    }
    merged.update({str(record.get("name") or ""): dict(record) for record in fresh})
    return [merged[name] for name in sorted(merged)]


def _merge_manifests(
    output: Path,
    baseline: Mapping[str, Any],
    selected_components: Sequence[str],
) -> None:
    selected = set(selected_components)
    for relative in VISUAL_MANIFESTS:
        baseline_manifest = baseline.get(relative)
        path = output / relative
        fresh_manifest = _read_json(path) if path.is_file() else None
        if relative == "visual/visual_manifest.json":
            if "visual-help" not in selected and baseline_manifest is not None:
                _write_json(path, baseline_manifest)
            continue
        if relative == "visual/generated_output_manifest.json":
            if "imports-exports-reports" not in selected and baseline_manifest is not None:
                _write_json(path, baseline_manifest)
            continue
        if not selected.intersection(_BUSINESS_COMPONENTS):
            if baseline_manifest is not None:
                _write_json(path, baseline_manifest)
            continue
        if baseline_manifest is None or fresh_manifest is None:
            raise ArtifactCompatibilityError("business workflow manifest is missing during reuse")
        if not isinstance(baseline_manifest, dict) or not isinstance(fresh_manifest, dict):
            raise ArtifactCompatibilityError("business workflow manifest must be an object")
        merged = {
            key: _merge_named_records(
                baseline_manifest.get(key, []),
                fresh_manifest.get(key, []),
                selected,
            )
            for key in ("captures", "comparisons")
        }
        _write_json(path, merged)


def _resolve_artifact_path(output: Path, value: object) -> Path:
    normalized = str(value or "").replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ArtifactCompatibilityError(f"unsafe artifact path in manifest: {value!r}")
    parts = list(path.parts)
    if "ui_pq" in parts:
        parts = parts[parts.index("ui_pq") + 1 :]
    resolved = output.joinpath(*parts).resolve()
    if not resolved.is_relative_to(output.resolve()):
        raise ArtifactCompatibilityError(f"artifact path escapes bundle: {value!r}")
    return resolved


def _validate_manifest(output: Path, relative: str) -> None:
    path = output / relative
    if not path.is_file():
        raise ArtifactCompatibilityError(f"required visual manifest is missing: {relative}")
    manifest = _read_json(path)
    if not isinstance(manifest, dict):
        raise ArtifactCompatibilityError(f"visual manifest must be an object: {relative}")
    captures = manifest.get("captures", [])
    comparisons = manifest.get("comparisons", [])
    if not isinstance(captures, list) or not isinstance(comparisons, list):
        raise ArtifactCompatibilityError(f"visual manifest collections are invalid: {relative}")
    for record in captures:
        if not isinstance(record, dict):
            raise ArtifactCompatibilityError(f"invalid capture in {relative}")
        artifact_path = _resolve_artifact_path(output, record.get("path"))
        if not artifact_path.is_file() or _sha256_file(artifact_path) != record.get("sha256"):
            raise ArtifactCompatibilityError(f"capture hash mismatch: {record.get('name')}")
    for record in comparisons:
        if not isinstance(record, dict) or record.get("passed") is not True:
            raise ArtifactCompatibilityError(f"failed or invalid comparison in {relative}")
        for path_key, hash_key in (
            ("actual_path", "actual_sha256"),
            ("baseline_path", "baseline_sha256"),
        ):
            artifact_path = _resolve_artifact_path(output, record.get(path_key))
            if not artifact_path.is_file() or _sha256_file(artifact_path) != record.get(hash_key):
                raise ArtifactCompatibilityError(
                    f"comparison hash mismatch: {record.get('name')} ({path_key})"
                )


def validate_bundle_files(output: Path) -> None:
    """Reject incomplete, failed, or internally inconsistent canonical bundles."""
    missing = [relative for relative in REQUIRED_BUNDLE_FILES if not (output / relative).is_file()]
    if missing:
        raise ArtifactCompatibilityError("bundle is missing: " + ", ".join(missing))
    evidence = _read_json(output / "evidence.json")
    if not isinstance(evidence, list) or not evidence:
        raise ArtifactCompatibilityError("bundle evidence is missing or empty")
    failed = [
        str(event.get("test_id") or "<unknown>")
        for event in evidence
        if not isinstance(event, dict) or event.get("status") != "passed"
    ]
    if failed:
        raise ArtifactCompatibilityError(
            "bundle contains non-passing evidence: " + ", ".join(failed)
        )
    for relative in VISUAL_MANIFESTS:
        _validate_manifest(output, relative)


def _component_relevant_hash(component: str, fingerprints: Mapping[str, Any]) -> str:
    try:
        return _provenance.component_relevant_hash(component, fingerprints)
    except _provenance.ProvenanceValidationError as exc:
        raise ArtifactCompatibilityError(str(exc)) from exc


def _write_summary(
    output: Path,
    evidence: Sequence[Mapping[str, Any]],
    *,
    effective_mode: str,
    selected_components: Sequence[str],
    reused_components: Sequence[str],
    generated_at: str,
) -> None:
    lines = [
        "# UI PQ Execution Summary",
        "",
        "This is an internal engineering UI qualification artifact. It is not a regulatory ",
        "certification or external compliance claim.",
        "",
        f"- Bundle generated: {generated_at}",
        f"- Effective mode: {effective_mode}",
        f"- Components executed: {', '.join(selected_components) or 'none'}",
        f"- Components reused with compatible provenance: {', '.join(reused_components) or 'none'}",
        f"- Passing evidence events: {len(evidence)}",
        "",
        "## Canonical Evidence Events",
        "",
    ]
    for event in evidence:
        lines.append(
            f"- `{event.get('test_id', '<unknown>')}` {event.get('status', 'unknown')}: "
            f"{event.get('message', '')}"
        )
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def finalize_bundle(*, state_path: Path, output: Path) -> dict[str, object]:
    """Merge selected structured outputs and record complete per-component provenance."""
    state = _read_json(state_path)
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        raise ArtifactCompatibilityError("prepare state is missing or incompatible")
    plan = state.get("plan")
    fingerprints = state.get("fingerprints")
    baseline = state.get("baseline")
    if not isinstance(plan, dict) or not isinstance(fingerprints, dict):
        raise ArtifactCompatibilityError("prepare state is incomplete")
    source_commit, test_version, renderer_version, mapping_hash = _required_plan_values(plan)
    effective_mode = str(state.get("effective_mode") or "full")
    selected = [str(name) for name in state.get("selected_components", [])]
    all_components = sorted(fingerprints.get("components", {}))
    reused = sorted(set(all_components) - set(selected))

    if baseline is not None and effective_mode == "incremental":
        if not isinstance(baseline, dict):
            raise ArtifactCompatibilityError("baseline merge state is invalid")
        fresh_evidence = _read_json(output / "evidence.json")
        if not isinstance(fresh_evidence, list):
            raise ArtifactCompatibilityError("fresh evidence must be a list")
        evidence = _merge_evidence(baseline["evidence"], fresh_evidence, selected)
        _write_json(output / "evidence.json", evidence)
        deviations = _merge_deviations(
            baseline["deviations"],
            _read_csv_payload(output / "deviations.csv"),
            selected,
        )
        _write_csv_payload(output / "deviations.csv", deviations)
        _merge_manifests(output, baseline["manifests"], selected)
    else:
        evidence = _read_json(output / "evidence.json")
        if not isinstance(evidence, list):
            raise ArtifactCompatibilityError("evidence must be a list")

    selected_ids = _selected_evidence_ids(selected)
    evidence_ids = {str(event.get("test_id") or "") for event in evidence}
    missing = sorted(selected_ids - evidence_ids)
    if missing:
        raise ArtifactCompatibilityError("final evidence is missing: " + ", ".join(missing))

    generated_at = _utc_now()
    _write_summary(
        output,
        evidence,
        effective_mode=effective_mode,
        selected_components=selected,
        reused_components=reused,
        generated_at=generated_at,
    )
    validate_bundle_files(output)

    baseline_components: Mapping[str, Any] = {}
    if isinstance(baseline, dict):
        baseline_provenance = baseline.get("provenance", {})
        if isinstance(baseline_provenance, dict):
            value = baseline_provenance.get("components", {})
            if isinstance(value, dict):
                baseline_components = value
    component_provenance: dict[str, dict[str, Any]] = {}
    for component in all_components:
        if component in selected:
            component_provenance[component] = {
                "generated_at": generated_at,
                "relevant_inputs_hash": _component_relevant_hash(component, fingerprints),
                "renderer_version": renderer_version,
                "source_commit": source_commit,
                "status": "generated",
                "test_version": test_version,
            }
            continue
        prior = baseline_components.get(component)
        if not isinstance(prior, dict):
            raise ArtifactCompatibilityError(
                f"cannot reuse component without prior provenance: {component}"
            )
        component_provenance[component] = {
            **prior,
            "last_reused_at": generated_at,
            "reused_for_commit": source_commit,
            "status": "reused",
        }

    bundle_relevant_hash = _stable_hash(fingerprints)
    provenance = {
        "schema_version": SCHEMA_VERSION,
        "bundle": {
            "effective_mode": effective_mode,
            "generated_at": generated_at,
            "mapping_hash": mapping_hash,
            "plan_hash": plan.get("plan_hash"),
            "relevant_inputs_hash": bundle_relevant_hash,
            "renderer_version": renderer_version,
            "reused_components": reused,
            "selected_components": selected,
            "source_commit": source_commit,
            "test_version": test_version,
        },
        "components": component_provenance,
        "fingerprints": fingerprints,
    }
    _write_json(output / PROVENANCE_NAME, provenance)
    return {
        "effective_mode": effective_mode,
        "evidence_events": len(evidence),
        "generated_components": selected,
        "relevant_inputs_hash": bundle_relevant_hash,
        "reused_components": reused,
    }


def _append_summary(path: Path | None, title: str, result: Mapping[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"## {title}\n\n")
        for key, value in result.items():
            if isinstance(value, list):
                display = ", ".join(str(item) for item in value) or "none"
            else:
                display = str(value) or "none"
            stream.write(f"- {key.replace('_', ' ').title()}: {display}\n")
        stream.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="validate/reuse a prior bundle or force full")
    prepare.add_argument("--plan", type=Path, required=True)
    prepare.add_argument("--repo-root", type=Path, default=Path.cwd())
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--state", type=Path, required=True)
    prepare.add_argument(
        "--runtime-fingerprint",
        type=Path,
        required=True,
        help="pre-install runtime identity captured by scripts/qa_pq_runtime.py",
    )
    prepare.add_argument("--baseline", type=Path)
    prepare.add_argument(
        "--baseline-source-commit",
        help="externally attested workflow_run.head_sha for the downloaded baseline artifact",
    )
    prepare.add_argument("--replace-output", action="store_true")
    prepare.add_argument("--github-output", type=Path)
    prepare.add_argument("--summary", type=Path)

    finalize = subparsers.add_parser("finalize", help="merge and validate a canonical bundle")
    finalize.add_argument("--state", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    finalize.add_argument("--summary", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "prepare":
        result = prepare_bundle(
            plan_path=args.plan,
            repo_root=args.repo_root,
            output=args.output,
            state_path=args.state,
            runtime_fingerprint_path=args.runtime_fingerprint,
            baseline=args.baseline,
            baseline_source_commit=args.baseline_source_commit,
            replace_output=args.replace_output,
        )
        if args.github_output:
            _write_github_outputs(args.github_output, result)
        _append_summary(args.summary, "QA/PQ impact and reuse decision", result)
    else:
        result = finalize_bundle(state_path=args.state, output=args.output)
        _append_summary(args.summary, "QA/PQ canonical artifact", result)
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
