from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts import qa_pq_artifacts as artifacts
from scripts import qa_pq_runtime as runtime

COMPONENTS = ("assets", "catalog", "core-inventory")
BASELINE_COMMIT = "a" * 40
CURRENT_COMMIT = "b" * 40
RUNTIME_INPUTS = {
    "dependencies": {
        "numpy": "2.5.1",
        "pillow": "12.3.0",
        "pyside6": "6.11.1",
        "pyside6-addons": "6.11.1",
        "pyside6-essentials": "6.11.1",
        "pytest": "9.1.1",
        "pytest-cov": "7.1.0",
        "shiboken6": "6.11.1",
    },
    "python": {
        "abi": "cpython-314-test",
        "cache_tag": "cpython-314",
        "implementation": "cpython",
        "requires_python": ">=3.14.4",
        "version": "3.14.4",
    },
    "qt": {
        "auto_screen_scale_factor": "",
        "font_dpi": "",
        "qpa_platform": "offscreen",
        "scale_factor": "",
        "screen_scale_factors": "",
    },
    "runner": {
        "arch": "X64",
        "environment": "github-hosted",
        "image_os": "ubuntu24",
        "image_version": "20260801.1",
        "os": "Linux",
    },
    "system_packages": {name: "1.0" for name in runtime.QT_SYSTEM_PACKAGES},
}
RUNTIME_FINGERPRINT = {
    "schema_version": runtime.RUNTIME_SCHEMA_VERSION,
    "fingerprint": artifacts._stable_hash(RUNTIME_INPUTS),
    "inputs": RUNTIME_INPUTS,
}
REPOSITORY_FINGERPRINTS = {
    "components": {
        "assets": "sha256:assets",
        "catalog": "sha256:catalog",
        "core-inventory": "sha256:core",
    },
    "shared": {"qa-harness": "sha256:shared"},
}
FINGERPRINTS = {**REPOSITORY_FINGERPRINTS, "runtime": RUNTIME_FINGERPRINT}


def _plan(*, mode: str = "incremental", selected: tuple[str, ...] = ("assets",)):
    return {
        "mode": mode,
        "plan_hash": "sha256:plan",
        "selected_components": list(selected),
        "test_targets": ["tests/ui_qa/test_ui_pq_assets_deliverables_workflow.py"],
        "provenance": {
            "mapping_hash": "sha256:mapping",
            "renderer_version": "renderer-v1",
            "source_commit": CURRENT_COMMIT,
            "test_version": "test-v1",
        },
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_deviations(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = ["test_id", "status", "message"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _record(root: Path, name: str) -> tuple[dict[str, object], dict[str, object]]:
    actual = root / "visual" / "screenshots" / f"{name}.png"
    baseline = root / "visual" / "baselines" / f"{name}.png"
    actual.parent.mkdir(parents=True, exist_ok=True)
    baseline.parent.mkdir(parents=True, exist_ok=True)
    payload = f"image:{name}".encode()
    actual.write_bytes(payload)
    baseline.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    capture = {
        "name": name,
        "path": f"artifacts/ui_pq/visual/screenshots/{name}.png",
        "sha256": digest,
    }
    comparison = {
        "name": name,
        "passed": True,
        "actual_path": f"artifacts/ui_pq/visual/screenshots/{name}.png",
        "actual_sha256": digest,
        "baseline_path": f"artifacts/ui_pq/visual/baselines/{name}.png",
        "baseline_sha256": digest,
    }
    return capture, comparison


def _event(test_id: str, message: str = "passed") -> dict[str, object]:
    return {
        "data": {},
        "message": message,
        "status": "passed",
        "test_id": test_id,
        "timestamp": "2026-08-08T00:00:00Z",
    }


def _component_provenance(name: str) -> dict[str, object]:
    return {
        "generated_at": "2026-08-01T00:00:00Z",
        "relevant_inputs_hash": artifacts._component_relevant_hash(name, FINGERPRINTS),
        "renderer_version": "renderer-v1",
        "source_commit": BASELINE_COMMIT,
        "status": "generated",
        "test_version": "test-v1",
    }


def _make_bundle(root: Path) -> None:
    root.mkdir(parents=True)
    _write_json(
        root / "evidence.json",
        [
            _event("UI-PQ-INV-001"),
            _event("UI-PQ-SMOKE-001"),
            _event("UI-PQ-MENU-001"),
            _event("UI-PQ-CAT-001"),
            _event("UI-PQ-ASSET-001", "old asset evidence"),
        ],
    )
    _write_deviations(
        root / "deviations.csv",
        [
            {"test_id": "UI-PQ-CAT-001", "status": "closed", "message": "catalog"},
            {"test_id": "UI-PQ-ASSET-001", "status": "closed", "message": "old"},
        ],
    )
    (root / "summary.md").write_text("old summary\n", encoding="utf-8")
    (root / "traceability_matrix.csv").write_text(
        "test_id,coverage_status\nUI-PQ-INV-001,covered\n", encoding="utf-8"
    )
    _write_json(root / "ui_inventory.json", [{"inventory_id": "main"}])

    catalog_capture, catalog_comparison = _record(root, "ui_pq_add_track_dialog_populated")
    asset_capture, asset_comparison = _record(root, "ui_pq_asset_old")
    empty_manifest = {"captures": [], "comparisons": []}
    _write_json(root / "visual" / "visual_manifest.json", empty_manifest)
    _write_json(root / "visual" / "generated_output_manifest.json", empty_manifest)
    _write_json(
        root / "visual" / "business_workflow_manifest.json",
        {
            "captures": [catalog_capture, asset_capture],
            "comparisons": [catalog_comparison, asset_comparison],
        },
    )
    _write_json(
        root / "provenance.json",
        {
            "schema_version": artifacts.SCHEMA_VERSION,
            "bundle": {
                "generated_at": "2026-08-01T00:00:00Z",
                "mapping_hash": "sha256:mapping",
                "relevant_inputs_hash": artifacts._stable_hash(FINGERPRINTS),
                "renderer_version": "renderer-v1",
                "source_commit": BASELINE_COMMIT,
                "test_version": "test-v1",
            },
            "components": {name: _component_provenance(name) for name in COMPONENTS},
            "fingerprints": FINGERPRINTS,
        },
    )


def _runtime_path(root: Path, value: object = RUNTIME_FINGERPRINT) -> Path:
    path = root / "runtime-fingerprint.json"
    _write_json(path, value)
    return path


@pytest.fixture
def stub_impact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        artifacts,
        "compute_input_fingerprints",
        lambda _repo_root: json.loads(json.dumps(REPOSITORY_FINGERPRINTS)),
    )
    monkeypatch.setattr(
        artifacts,
        "_all_targets",
        lambda _repo_root: (
            list(COMPONENTS),
            [
                "tests/ui_qa/test_ui_pq_assets_deliverables_workflow.py",
                "tests/ui_qa/test_ui_pq_catalog_workflow.py",
                "tests/ui_qa/test_ui_pq_inventory.py",
            ],
        ),
    )


def test_prepare_reuses_only_a_compatible_baseline(tmp_path: Path, stub_impact: None) -> None:
    baseline = tmp_path / "baseline"
    output = tmp_path / "output"
    state = tmp_path / "state.json"
    plan_path = tmp_path / "plan.json"
    _make_bundle(baseline)
    _write_json(plan_path, _plan())
    output.mkdir()
    (output / "stale.txt").write_text("stale", encoding="utf-8")

    result = artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=output,
        state_path=state,
        runtime_fingerprint_path=_runtime_path(tmp_path),
        baseline=baseline,
        baseline_source_commit=BASELINE_COMMIT,
        replace_output=True,
    )

    assert result["baseline_compatible"] is True
    assert result["effective_mode"] == "incremental"
    assert result["selected_components"] == ["assets"]
    assert result["run_tests"] is True
    assert not (output / "stale.txt").exists()
    assert (output / "provenance.json").is_file()


@pytest.mark.parametrize(
    ("attestation", "message"),
    (
        (None, "attestation is required"),
        ("c" * 40, "does not match the external artifact attestation"),
    ),
)
def test_prepare_forces_full_without_matching_external_source_attestation(
    tmp_path: Path,
    stub_impact: None,
    attestation: str | None,
    message: str,
) -> None:
    baseline = tmp_path / "baseline"
    plan_path = tmp_path / "plan.json"
    _make_bundle(baseline)
    _write_json(plan_path, _plan())

    result = artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=tmp_path / "output",
        state_path=tmp_path / "state.json",
        runtime_fingerprint_path=_runtime_path(tmp_path),
        baseline=baseline,
        baseline_source_commit=attestation,
        replace_output=True,
    )

    assert result["baseline_compatible"] is False
    assert result["effective_mode"] == "full"
    assert message in str(result["fallback_reason"])


def test_prepare_forces_full_on_runtime_renderer_mismatch(
    tmp_path: Path, stub_impact: None
) -> None:
    baseline = tmp_path / "baseline"
    plan_path = tmp_path / "plan.json"
    _make_bundle(baseline)
    _write_json(plan_path, _plan())
    current_runtime = json.loads(json.dumps(RUNTIME_FINGERPRINT))
    current_runtime["inputs"]["runner"]["image_version"] = "20260808.1"
    current_runtime["fingerprint"] = artifacts._stable_hash(current_runtime["inputs"])

    result = artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=tmp_path / "output",
        state_path=tmp_path / "state.json",
        runtime_fingerprint_path=_runtime_path(tmp_path, current_runtime),
        baseline=baseline,
        baseline_source_commit=BASELINE_COMMIT,
        replace_output=True,
    )

    assert result["baseline_compatible"] is False
    assert result["effective_mode"] == "full"
    assert "runtime-renderer fingerprint mismatch" in str(result["fallback_reason"])


def test_prepare_forces_full_on_tampered_bundle_relevant_input_hash(
    tmp_path: Path, stub_impact: None
) -> None:
    baseline = tmp_path / "baseline"
    plan_path = tmp_path / "plan.json"
    _make_bundle(baseline)
    _write_json(plan_path, _plan())
    provenance_path = baseline / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["bundle"]["relevant_inputs_hash"] = "sha256:tampered"
    _write_json(provenance_path, provenance)

    result = artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=tmp_path / "output",
        state_path=tmp_path / "state.json",
        runtime_fingerprint_path=_runtime_path(tmp_path),
        baseline=baseline,
        baseline_source_commit=BASELINE_COMMIT,
        replace_output=True,
    )

    assert result["baseline_compatible"] is False
    assert "bundle relevant-input hash is inconsistent" in str(result["fallback_reason"])


def test_prepare_forces_full_on_tampered_reused_component_hash(
    tmp_path: Path, stub_impact: None
) -> None:
    baseline = tmp_path / "baseline"
    plan_path = tmp_path / "plan.json"
    _make_bundle(baseline)
    _write_json(plan_path, _plan(selected=("assets",)))
    provenance_path = baseline / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["components"]["catalog"]["relevant_inputs_hash"] = "sha256:tampered"
    _write_json(provenance_path, provenance)

    result = artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=tmp_path / "output",
        state_path=tmp_path / "state.json",
        runtime_fingerprint_path=_runtime_path(tmp_path),
        baseline=baseline,
        baseline_source_commit=BASELINE_COMMIT,
        replace_output=True,
    )

    assert result["baseline_compatible"] is False
    assert "reused-component relevant-input hash is inconsistent: catalog" in str(
        result["fallback_reason"]
    )


def test_prepare_allows_changed_inputs_for_a_selected_component(
    tmp_path: Path, stub_impact: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = tmp_path / "baseline"
    plan_path = tmp_path / "plan.json"
    _make_bundle(baseline)
    _write_json(plan_path, _plan(selected=("assets",)))
    current = json.loads(json.dumps(REPOSITORY_FINGERPRINTS))
    current["components"]["assets"] = "sha256:changed-selected-component"
    monkeypatch.setattr(artifacts, "compute_input_fingerprints", lambda _root: current)

    result = artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=tmp_path / "output",
        state_path=tmp_path / "state.json",
        runtime_fingerprint_path=_runtime_path(tmp_path),
        baseline=baseline,
        baseline_source_commit=BASELINE_COMMIT,
        replace_output=True,
    )

    assert result["baseline_compatible"] is True
    assert result["effective_mode"] == "incremental"


def test_prepare_forces_full_when_an_unselected_component_changed(
    tmp_path: Path, stub_impact: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = tmp_path / "baseline"
    output = tmp_path / "output"
    state = tmp_path / "state.json"
    plan_path = tmp_path / "plan.json"
    _make_bundle(baseline)
    _write_json(plan_path, _plan())
    current = json.loads(json.dumps(REPOSITORY_FINGERPRINTS))
    current["components"]["catalog"] = "sha256:changed"
    monkeypatch.setattr(artifacts, "compute_input_fingerprints", lambda _root: current)

    result = artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=output,
        state_path=state,
        runtime_fingerprint_path=_runtime_path(tmp_path),
        baseline=baseline,
        baseline_source_commit=BASELINE_COMMIT,
        replace_output=True,
    )

    assert result["baseline_compatible"] is False
    assert result["effective_mode"] == "full"
    assert result["selected_components"] == list(COMPONENTS)
    assert "catalog" in str(result["fallback_reason"])
    assert list(output.iterdir()) == []


def test_runtime_fingerprint_captures_and_verifies_pinned_renderer_identity() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    environment = {
        "GITHUB_ACTIONS": "true",
        "ImageOS": "ubuntu24",
        "ImageVersion": "20260801.1",
        "QT_QPA_PLATFORM": "offscreen",
        "RUNNER_ARCH": "X64",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux",
    }

    system_versions = {
        name: f"1.0.{index}" for index, name in enumerate(runtime.QT_SYSTEM_PACKAGES)
    }
    captured = runtime.capture_runtime_fingerprint(
        repo_root,
        environ=environment,
        system_version_reader=system_versions.__getitem__,
    )
    validated = runtime.validate_runtime_fingerprint(captured)
    expected_versions = validated["inputs"]["dependencies"]
    installed = runtime.verify_runtime_fingerprint(
        validated,
        repo_root,
        environ=environment,
        version_reader=expected_versions.__getitem__,
        system_version_reader=system_versions.__getitem__,
    )

    assert captured == runtime.capture_runtime_fingerprint(
        repo_root,
        environ=environment,
        system_version_reader=system_versions.__getitem__,
    )
    assert captured["inputs"]["python"]["version"] == "3.14.4"
    assert captured["inputs"]["qt"]["qpa_platform"] == "offscreen"
    assert captured["inputs"]["runner"]["image_version"] == "20260801.1"
    assert captured["inputs"]["system_packages"] == system_versions
    assert installed == expected_versions

    with pytest.raises(runtime.RuntimeFingerprintError, match="exact pins"):
        runtime.verify_runtime_fingerprint(
            validated,
            repo_root,
            environ=environment,
            version_reader=lambda name: "0.0" if name == "pyside6" else expected_versions[name],
            system_version_reader=system_versions.__getitem__,
        )
    drifted_system_versions = dict(system_versions)
    drifted_system_versions["libegl1"] = "2.0"
    with pytest.raises(runtime.RuntimeFingerprintError, match="no longer matches"):
        runtime.verify_runtime_fingerprint(
            validated,
            repo_root,
            environ=environment,
            version_reader=expected_versions.__getitem__,
            system_version_reader=drifted_system_versions.__getitem__,
        )
    with pytest.raises(runtime.RuntimeFingerprintError, match="ImageOS and ImageVersion"):
        runtime.capture_runtime_fingerprint(repo_root, environ={"GITHUB_ACTIONS": "true"})


def test_runtime_cli_exposes_the_canonical_system_package_set(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert runtime.main(["system-packages"]) == 0
    assert capsys.readouterr().out.splitlines() == list(runtime.QT_SYSTEM_PACKAGES)
    assert "libglib2.0-0t64" in runtime.QT_SYSTEM_PACKAGES
    assert "libglib2.0-0" not in runtime.QT_SYSTEM_PACKAGES


def test_ci_installs_system_renderer_packages_before_runtime_capture() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    install_at = workflow.index("Install fingerprinted Qt runtime libraries")
    capture_at = workflow.index("Capture the QA/PQ renderer runtime identity")
    prepare_at = workflow.index("Validate reuse provenance and select effective work")
    assert install_at < capture_at < prepare_at
    assert workflow.count("scripts/qa_pq_runtime.py system-packages") == 3


def test_none_plan_without_baseline_falls_back_to_full(tmp_path: Path, stub_impact: None) -> None:
    plan_path = tmp_path / "plan.json"
    _write_json(plan_path, _plan(mode="none", selected=()))

    result = artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=tmp_path / "output",
        state_path=tmp_path / "state.json",
        runtime_fingerprint_path=_runtime_path(tmp_path),
        replace_output=True,
    )

    assert result["effective_mode"] == "full"
    assert result["run_tests"] is True
    assert result["fallback_reason"] == "no prior canonical QA/PQ bundle was available"


def test_none_plan_reuses_a_compatible_bundle_without_running_tests(
    tmp_path: Path, stub_impact: None
) -> None:
    baseline = tmp_path / "baseline"
    output = tmp_path / "output"
    state = tmp_path / "state.json"
    plan_path = tmp_path / "plan.json"
    _make_bundle(baseline)
    _write_json(plan_path, _plan(mode="none", selected=()))
    expected_evidence = _read_json_list(baseline / "evidence.json")
    expected_manifests = {
        relative: json.loads((baseline / relative).read_text(encoding="utf-8"))
        for relative in artifacts.VISUAL_MANIFESTS
    }

    prepared = artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=output,
        state_path=state,
        runtime_fingerprint_path=_runtime_path(tmp_path),
        baseline=baseline,
        baseline_source_commit=BASELINE_COMMIT,
        replace_output=True,
    )
    finalized = artifacts.finalize_bundle(state_path=state, output=output)

    assert prepared["baseline_compatible"] is True
    assert prepared["effective_mode"] == "none"
    assert prepared["run_tests"] is False
    assert finalized["generated_components"] == []
    assert finalized["reused_components"] == sorted(COMPONENTS)
    assert _read_json_list(output / "evidence.json") == expected_evidence
    assert {
        relative: json.loads((output / relative).read_text(encoding="utf-8"))
        for relative in artifacts.VISUAL_MANIFESTS
    } == expected_manifests
    provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    assert all(component["status"] == "reused" for component in provenance["components"].values())
    artifacts.validate_bundle_files(output)


def test_full_prepare_preserves_only_checked_in_visual_baselines(
    tmp_path: Path, stub_impact: None
) -> None:
    plan_path = tmp_path / "plan.json"
    output = tmp_path / "output"
    baseline = output / "visual" / "baselines" / "reference.png"
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(b"qualified baseline")
    (output / "stale.txt").write_text("stale", encoding="utf-8")
    _write_json(plan_path, _plan(mode="full", selected=COMPONENTS))

    result = artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=output,
        state_path=tmp_path / "state.json",
        runtime_fingerprint_path=_runtime_path(tmp_path),
        replace_output=True,
    )

    assert result["effective_mode"] == "full"
    assert baseline.read_bytes() == b"qualified baseline"
    assert not (output / "stale.txt").exists()


def test_incremental_finalize_replaces_selected_records_and_preserves_others(
    tmp_path: Path, stub_impact: None
) -> None:
    baseline = tmp_path / "baseline"
    output = tmp_path / "output"
    state = tmp_path / "state.json"
    plan_path = tmp_path / "plan.json"
    _make_bundle(baseline)
    _write_json(plan_path, _plan())
    artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=output,
        state_path=state,
        runtime_fingerprint_path=_runtime_path(tmp_path),
        baseline=baseline,
        baseline_source_commit=BASELINE_COMMIT,
        replace_output=True,
    )

    _write_json(output / "evidence.json", [_event("UI-PQ-ASSET-001", "fresh asset evidence")])
    _write_deviations(
        output / "deviations.csv",
        [{"test_id": "UI-PQ-ASSET-001", "status": "closed", "message": "fresh"}],
    )
    fresh_capture, fresh_comparison = _record(output, "ui_pq_asset_new")
    _write_json(
        output / "visual" / "business_workflow_manifest.json",
        {"captures": [fresh_capture], "comparisons": [fresh_comparison]},
    )

    result = artifacts.finalize_bundle(state_path=state, output=output)

    evidence = _read_json_list(output / "evidence.json")
    asset_event = next(event for event in evidence if event["test_id"] == "UI-PQ-ASSET-001")
    assert asset_event["message"] == "fresh asset evidence"
    assert any(event["test_id"] == "UI-PQ-CAT-001" for event in evidence)
    manifest = json.loads(
        (output / "visual" / "business_workflow_manifest.json").read_text(encoding="utf-8")
    )
    names = {record["name"] for record in manifest["captures"]}
    assert names == {"ui_pq_add_track_dialog_populated", "ui_pq_asset_new"}
    provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["components"]["assets"]["source_commit"] == CURRENT_COMMIT
    assert provenance["components"]["catalog"]["source_commit"] == BASELINE_COMMIT
    assert provenance["components"]["catalog"]["status"] == "reused"
    assert provenance["bundle"]["relevant_inputs_hash"] == artifacts._stable_hash(
        provenance["fingerprints"]
    )
    assert all(
        component["relevant_inputs_hash"]
        == artifacts._component_relevant_hash(name, provenance["fingerprints"])
        for name, component in provenance["components"].items()
    )
    assert result["reused_components"] == ["catalog", "core-inventory"]


def _read_json_list(path: Path) -> list[dict[str, object]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, list)
    return value


def test_finalize_rejects_unowned_fresh_manifest_entries(tmp_path: Path, stub_impact: None) -> None:
    baseline = tmp_path / "baseline"
    output = tmp_path / "output"
    state = tmp_path / "state.json"
    plan_path = tmp_path / "plan.json"
    _make_bundle(baseline)
    _write_json(plan_path, _plan())
    artifacts.prepare_bundle(
        plan_path=plan_path,
        repo_root=tmp_path,
        output=output,
        state_path=state,
        runtime_fingerprint_path=_runtime_path(tmp_path),
        baseline=baseline,
        baseline_source_commit=BASELINE_COMMIT,
        replace_output=True,
    )
    _write_json(output / "evidence.json", [_event("UI-PQ-ASSET-001")])
    unknown_capture, unknown_comparison = _record(output, "unmapped_new_capture")
    _write_json(
        output / "visual" / "business_workflow_manifest.json",
        {"captures": [unknown_capture], "comparisons": [unknown_comparison]},
    )

    with pytest.raises(artifacts.ArtifactCompatibilityError, match="no selected component owner"):
        artifacts.finalize_bundle(state_path=state, output=output)


def test_non_business_selection_preserves_the_business_manifest(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _make_bundle(bundle)
    manifests = {
        relative: json.loads((bundle / relative).read_text(encoding="utf-8"))
        for relative in artifacts.VISUAL_MANIFESTS
    }
    baseline = manifests["visual/business_workflow_manifest.json"]

    artifacts._merge_manifests(bundle, manifests, ["core-inventory"])

    preserved = json.loads(
        (bundle / "visual" / "business_workflow_manifest.json").read_text(encoding="utf-8")
    )
    assert preserved == baseline


def test_bundle_validation_rejects_tampered_visual_output(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _make_bundle(bundle)
    target = bundle / "visual" / "screenshots" / "ui_pq_asset_old.png"
    target.write_bytes(b"tampered")

    with pytest.raises(artifacts.ArtifactCompatibilityError, match="hash mismatch"):
        artifacts.validate_bundle_files(bundle)
