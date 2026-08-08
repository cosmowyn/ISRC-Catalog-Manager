"""Capture and verify the runtime identity used for UI QA/PQ rendering."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import sysconfig
import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scripts import qa_pq_fingerprints as _fingerprints
elif __package__:
    from . import qa_pq_fingerprints as _fingerprints
else:
    import qa_pq_fingerprints as _fingerprints  # type: ignore[import-not-found,no-redef]

RUNTIME_SCHEMA_VERSION = 2
DECLARED_PACKAGES = ("numpy", "pillow", "pyside6", "pytest", "pytest-cov")
DERIVED_QT_PACKAGES = ("pyside6-addons", "pyside6-essentials", "shiboken6")
REQUIRED_PACKAGES = (*DECLARED_PACKAGES, *DERIVED_QT_PACKAGES)
QT_SYSTEM_PACKAGES = (
    "libegl1",
    "libgl1",
    "libglib2.0-0t64",
    "libopengl0",
    "libpulse-mainloop-glib0",
    "libx11-xcb1",
    "libxcb-cursor0",
    "libxcb-icccm4",
    "libxcb-image0",
    "libxcb-keysyms1",
    "libxcb-randr0",
    "libxcb-render-util0",
    "libxcb-shape0",
    "libxcb-shm0",
    "libxcb-sync1",
    "libxcb-xfixes0",
    "libxcb-xinerama0",
    "libxcb-xkb1",
    "libxkbcommon0",
    "libxkbcommon-x11-0",
)
_EXACT_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_,.-]+\])?==([^;\s]+)$")


class RuntimeFingerprintError(RuntimeError):
    """Raised when a runtime fingerprint is incomplete, inconsistent, or unverified."""


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _project_runtime_inputs(repo_root: Path) -> tuple[str, dict[str, str]]:
    project_path = repo_root / "pyproject.toml"
    try:
        with project_path.open("rb") as stream:
            project = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeFingerprintError(
            f"cannot read runtime pins from {project_path}: {exc}"
        ) from exc
    project_table = project.get("project")
    if not isinstance(project_table, dict):
        raise RuntimeFingerprintError("pyproject.toml has no project table")
    requirements = list(project_table.get("dependencies") or [])
    optional = project_table.get("optional-dependencies") or {}
    if not isinstance(optional, dict):
        raise RuntimeFingerprintError("project optional-dependencies must be a table")
    requirements.extend(optional.get("dev") or [])
    pins: dict[str, str] = {}
    for requirement in requirements:
        match = _EXACT_PIN_RE.fullmatch(str(requirement).strip())
        if match is None:
            continue
        name = _normalize_package_name(match.group(1))
        if name in DECLARED_PACKAGES:
            version = match.group(2)
            if name in pins and pins[name] != version:
                raise RuntimeFingerprintError(f"conflicting exact runtime pins for {name}")
            pins[name] = version
    missing = sorted(set(DECLARED_PACKAGES) - set(pins))
    if missing:
        raise RuntimeFingerprintError(
            "missing exact renderer/test dependency pins: " + ", ".join(missing)
        )
    for name in DERIVED_QT_PACKAGES:
        pins[name] = pins["pyside6"]
    requires_python = project_table.get("requires-python")
    if not isinstance(requires_python, str) or not requires_python.strip():
        raise RuntimeFingerprintError("project requires-python is missing")
    return requires_python.strip(), dict(sorted(pins.items()))


def _dpkg_version(package: str) -> str:
    try:
        completed = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", package],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeFingerprintError(
            f"cannot read installed system renderer package {package}: {exc}"
        ) from exc
    version = completed.stdout.strip()
    if not version:
        raise RuntimeFingerprintError(f"installed system renderer package {package} has no version")
    return version


def _system_package_versions(
    environment: Mapping[str, str],
    *,
    version_reader: Callable[[str], str] | None,
) -> dict[str, str]:
    github_actions = str(environment.get("GITHUB_ACTIONS") or "").lower() == "true"
    runner_os = str(environment.get("RUNNER_OS") or platform.system()).lower()
    if not github_actions or runner_os != "linux":
        return {}
    reader = _dpkg_version if version_reader is None else version_reader
    versions: dict[str, str] = {}
    for package in QT_SYSTEM_PACKAGES:
        try:
            version = str(reader(package)).strip()
        except RuntimeFingerprintError:
            raise
        except Exception as exc:
            raise RuntimeFingerprintError(
                f"cannot read installed system renderer package {package}: {exc}"
            ) from exc
        if not version:
            raise RuntimeFingerprintError(
                f"installed system renderer package {package} has no version"
            )
        versions[package] = version
    return versions


def capture_runtime_fingerprint(
    repo_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    system_version_reader: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic descriptor without importing project dependencies."""
    environment = os.environ if environ is None else environ
    requires_python, dependencies = _project_runtime_inputs(repo_root)
    github_actions = str(environment.get("GITHUB_ACTIONS") or "").lower() == "true"
    image_os = str(environment.get("ImageOS") or "").strip()
    image_version = str(environment.get("ImageVersion") or "").strip()
    if github_actions and (not image_os or not image_version):
        raise RuntimeFingerprintError(
            "GitHub-hosted runtime identity requires ImageOS and ImageVersion"
        )
    inputs = {
        "dependencies": dependencies,
        "python": {
            "abi": str(sysconfig.get_config_var("SOABI") or ""),
            "cache_tag": str(sys.implementation.cache_tag or ""),
            "implementation": sys.implementation.name,
            "requires_python": requires_python,
            "version": platform.python_version(),
        },
        "qt": {
            "auto_screen_scale_factor": str(environment.get("QT_AUTO_SCREEN_SCALE_FACTOR") or ""),
            "font_dpi": str(environment.get("QT_FONT_DPI") or ""),
            "qpa_platform": str(environment.get("QT_QPA_PLATFORM") or ""),
            "scale_factor": str(environment.get("QT_SCALE_FACTOR") or ""),
            "screen_scale_factors": str(environment.get("QT_SCREEN_SCALE_FACTORS") or ""),
        },
        "runner": {
            "arch": str(environment.get("RUNNER_ARCH") or platform.machine()),
            "environment": str(
                environment.get("RUNNER_ENVIRONMENT")
                or ("github-hosted" if github_actions else "local")
            ),
            "image_os": image_os or f"local-{platform.system().lower()}",
            "image_version": image_version or platform.release(),
            "os": str(environment.get("RUNNER_OS") or platform.system()),
        },
        "system_packages": _system_package_versions(
            environment,
            version_reader=system_version_reader,
        ),
    }
    return {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "fingerprint": _fingerprints.stable_hash(inputs),
        "inputs": inputs,
    }


def validate_runtime_fingerprint(value: object) -> dict[str, Any]:
    """Return a validated runtime document whose hash matches its inputs."""
    if not isinstance(value, dict) or value.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise RuntimeFingerprintError("runtime fingerprint schema is missing or incompatible")
    inputs = value.get("inputs")
    fingerprint = value.get("fingerprint")
    if not isinstance(inputs, dict) or set(inputs) != {
        "dependencies",
        "python",
        "qt",
        "runner",
        "system_packages",
    }:
        raise RuntimeFingerprintError("runtime fingerprint inputs are incomplete")
    if not all(isinstance(inputs.get(key), dict) for key in inputs):
        raise RuntimeFingerprintError("runtime fingerprint input groups must be objects")
    dependencies = inputs["dependencies"]
    if set(dependencies) != set(REQUIRED_PACKAGES) or not all(
        isinstance(name, str) and isinstance(version, str) and version
        for name, version in dependencies.items()
    ):
        raise RuntimeFingerprintError("runtime dependency pins are incomplete")
    system_packages = inputs["system_packages"]
    if not all(
        isinstance(name, str) and isinstance(version, str) and version
        for name, version in system_packages.items()
    ):
        raise RuntimeFingerprintError("system renderer package versions are invalid")
    runner = inputs["runner"]
    requires_system_packages = (
        str(runner.get("environment") or "") == "github-hosted"
        and str(runner.get("os") or "").lower() == "linux"
    )
    if requires_system_packages and set(system_packages) != set(QT_SYSTEM_PACKAGES):
        raise RuntimeFingerprintError("system renderer package versions are incomplete")
    expected = _fingerprints.stable_hash(inputs)
    if not isinstance(fingerprint, str) or fingerprint != expected:
        raise RuntimeFingerprintError("runtime fingerprint hash is inconsistent")
    return {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "inputs": inputs,
    }


def load_runtime_fingerprint(path: Path) -> dict[str, Any]:
    """Read and validate a runtime fingerprint document."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeFingerprintError(f"invalid runtime fingerprint {path}: {exc}") from exc
    return validate_runtime_fingerprint(value)


def verify_runtime_fingerprint(
    recorded: Mapping[str, Any],
    repo_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    version_reader: Callable[[str], str] = importlib.metadata.version,
    system_version_reader: Callable[[str], str] | None = None,
) -> dict[str, str]:
    """Verify current identity and installed distributions against a captured descriptor."""
    validated = validate_runtime_fingerprint(dict(recorded))
    current = capture_runtime_fingerprint(
        repo_root,
        environ=environ,
        system_version_reader=system_version_reader,
    )
    if validated != current:
        raise RuntimeFingerprintError("captured runtime fingerprint no longer matches this runner")
    expected_versions = validated["inputs"]["dependencies"]
    mismatches: list[str] = []
    installed: dict[str, str] = {}
    for name, expected in expected_versions.items():
        try:
            actual = str(version_reader(name))
        except importlib.metadata.PackageNotFoundError:
            actual = "<missing>"
        installed[name] = actual
        if actual != expected:
            mismatches.append(f"{name}={actual} (expected {expected})")
    if mismatches:
        raise RuntimeFingerprintError(
            "installed runtime does not match exact pins: " + ", ".join(mismatches)
        )
    return dict(sorted(installed.items()))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "system-packages", help="print required Linux renderer packages, one per line"
    )
    capture = subparsers.add_parser("capture", help="capture the runner and renderer identity")
    capture.add_argument("--repo-root", type=Path, default=Path.cwd())
    capture.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify", help="verify identity and installed dependency pins")
    verify.add_argument("--repo-root", type=Path, default=Path.cwd())
    verify.add_argument("--input", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "system-packages":
        sys.stdout.write("\n".join(QT_SYSTEM_PACKAGES) + "\n")
        return 0
    try:
        if args.command == "capture":
            result: object = capture_runtime_fingerprint(args.repo_root)
            _write_json(args.output, result)
        else:
            recorded = load_runtime_fingerprint(args.input)
            result = {
                "fingerprint": recorded["fingerprint"],
                "installed": verify_runtime_fingerprint(recorded, args.repo_root),
                "verified": True,
            }
    except RuntimeFingerprintError as exc:
        parser = build_parser()
        parser.error(str(exc))
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
