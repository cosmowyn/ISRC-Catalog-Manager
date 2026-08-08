"""Validate and hash provenance for reusable QA/PQ artifact components."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scripts import qa_pq_fingerprints as _fingerprints
    from scripts import qa_pq_runtime as _runtime
elif __package__:
    from . import qa_pq_fingerprints as _fingerprints
    from . import qa_pq_runtime as _runtime
else:
    import qa_pq_fingerprints as _fingerprints  # type: ignore[import-not-found,no-redef]
    import qa_pq_runtime as _runtime  # type: ignore[import-not-found,no-redef]

_stable_hash: Callable[[object], str] = _fingerprints.stable_hash

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


class ProvenanceValidationError(RuntimeError):
    """Raised when stored provenance cannot safely support incremental reuse."""


def required_plan_values(plan: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """Return required plan provenance values in their canonical order."""
    provenance = plan.get("provenance")
    if not isinstance(provenance, dict):
        raise ProvenanceValidationError("impact plan has no provenance object")
    values = (
        provenance.get("source_commit"),
        provenance.get("test_version"),
        provenance.get("renderer_version"),
        provenance.get("mapping_hash"),
    )
    if not all(isinstance(value, str) and value for value in values):
        raise ProvenanceValidationError("impact plan provenance is incomplete")
    return values  # type: ignore[return-value]


def component_relevant_hash(component: str, fingerprints: Mapping[str, Any]) -> str:
    """Hash all inputs that can affect one component's reusable evidence."""
    components = fingerprints.get("components")
    shared = fingerprints.get("shared")
    runtime = fingerprints.get("runtime")
    if not isinstance(components, dict) or not isinstance(shared, dict):
        raise ProvenanceValidationError("provenance fingerprints are incomplete")
    try:
        runtime_document = _runtime.validate_runtime_fingerprint(runtime)
        component_hash = components[component]
    except (KeyError, _runtime.RuntimeFingerprintError) as exc:
        raise ProvenanceValidationError(
            f"cannot hash relevant inputs for component {component}"
        ) from exc
    if not isinstance(component_hash, str):
        raise ProvenanceValidationError(f"component fingerprint is invalid: {component}")
    return _stable_hash(
        {
            "component": component_hash,
            "runtime": runtime_document["fingerprint"],
            "shared": shared,
        }
    )


def validate_baseline_provenance(
    provenance: object,
    plan: Mapping[str, Any],
    current_fingerprints: Mapping[str, Any],
    *,
    attested_source_commit: str,
    schema_version: int,
) -> dict[str, Any]:
    """Validate external identity, runtime compatibility, and reusable component hashes."""
    if not _COMMIT_RE.fullmatch(attested_source_commit):
        raise ProvenanceValidationError("baseline source-commit attestation is missing or invalid")
    if not isinstance(provenance, dict) or provenance.get("schema_version") != schema_version:
        raise ProvenanceValidationError("baseline provenance schema is missing or incompatible")
    bundle = provenance.get("bundle")
    components = provenance.get("components")
    baseline_fingerprints = provenance.get("fingerprints")
    if not all(isinstance(value, dict) for value in (bundle, components, baseline_fingerprints)):
        raise ProvenanceValidationError("baseline provenance is incomplete")
    assert isinstance(bundle, dict)
    assert isinstance(components, dict)
    assert isinstance(baseline_fingerprints, dict)

    if bundle.get("source_commit") != attested_source_commit:
        raise ProvenanceValidationError(
            "baseline source commit does not match the external artifact attestation"
        )
    _source_commit, test_version, renderer_version, mapping_hash = required_plan_values(plan)
    expected = {
        "mapping_hash": mapping_hash,
        "renderer_version": renderer_version,
        "test_version": test_version,
    }
    mismatches = [key for key, value in expected.items() if bundle.get(key) != value]
    if mismatches:
        raise ProvenanceValidationError(
            "baseline global provenance mismatch: " + ", ".join(sorted(mismatches))
        )

    if set(baseline_fingerprints) != {"components", "runtime", "shared"}:
        raise ProvenanceValidationError("baseline fingerprint groups are incomplete")
    baseline_component_hashes = baseline_fingerprints.get("components")
    baseline_shared = baseline_fingerprints.get("shared")
    current_components = current_fingerprints.get("components")
    current_shared = current_fingerprints.get("shared")
    if not all(
        isinstance(value, dict)
        for value in (
            baseline_component_hashes,
            baseline_shared,
            current_components,
            current_shared,
        )
    ):
        raise ProvenanceValidationError("baseline repository fingerprints are incomplete")
    assert isinstance(baseline_component_hashes, dict)
    assert isinstance(current_components, dict)

    try:
        baseline_runtime = _runtime.validate_runtime_fingerprint(
            baseline_fingerprints.get("runtime")
        )
        current_runtime = _runtime.validate_runtime_fingerprint(current_fingerprints.get("runtime"))
    except _runtime.RuntimeFingerprintError as exc:
        raise ProvenanceValidationError(str(exc)) from exc
    if baseline_runtime != current_runtime:
        raise ProvenanceValidationError("baseline runtime-renderer fingerprint mismatch")
    if bundle.get("relevant_inputs_hash") != _stable_hash(baseline_fingerprints):
        raise ProvenanceValidationError("baseline bundle relevant-input hash is inconsistent")
    if baseline_shared != current_shared:
        raise ProvenanceValidationError("baseline shared-input fingerprint mismatch")
    if set(baseline_component_hashes) != set(current_components):
        raise ProvenanceValidationError("baseline component fingerprint set is incompatible")

    selected = {str(name) for name in plan.get("selected_components", [])}
    for name, current_hash in current_components.items():
        component = components.get(name)
        if not isinstance(component, dict):
            raise ProvenanceValidationError(f"baseline has no provenance for component {name}")
        if name in selected:
            continue
        if baseline_component_hashes.get(name) != current_hash:
            raise ProvenanceValidationError(
                f"baseline input fingerprint changed outside the planned components: {name}"
            )
        if component.get("relevant_inputs_hash") != component_relevant_hash(
            name, baseline_fingerprints
        ):
            raise ProvenanceValidationError(
                f"baseline reused-component relevant-input hash is inconsistent: {name}"
            )
        if (
            component.get("renderer_version") != renderer_version
            or component.get("test_version") != test_version
        ):
            raise ProvenanceValidationError(
                f"baseline reused-component tool provenance is incompatible: {name}"
            )
    return provenance
