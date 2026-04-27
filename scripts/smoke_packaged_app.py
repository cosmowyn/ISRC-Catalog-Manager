"""Run the frozen release artifact enough to prove it starts."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from isrc_manager.packaged_smoke import PACKAGED_SMOKE_TEST_ARGUMENT

DEFAULT_TIMEOUT_SECONDS = 45.0


class SmokeTestError(RuntimeError):
    """Raised when the packaged artifact cannot be smoke-tested."""


def _read_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        raise SmokeTestError(f"release manifest was not created: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SmokeTestError(f"release manifest is not a JSON object: {manifest_path}")
    return manifest


def _manifest_artifact_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_artifact = str(manifest.get("release_artifact") or "").strip()
    if not raw_artifact:
        raise SmokeTestError("release manifest does not include release_artifact")

    artifact = Path(raw_artifact)
    if artifact.is_absolute():
        return artifact

    project_root = manifest_path.resolve().parent.parent
    return (project_root / artifact).resolve()


def _normalize_platform(platform_key: str | None) -> str:
    normalized = str(platform_key or "").strip().lower()
    if normalized in {"windows", "win32"}:
        return "windows"
    if normalized in {"macos", "darwin"}:
        return "macos"
    if normalized:
        return normalized
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return "linux"


def _candidate_names(artifact: Path, app_name: str | None) -> list[str]:
    names = [str(value).strip() for value in (app_name, artifact.name, artifact.stem) if value]
    return list(dict.fromkeys(names))


def _macos_bundle_executable(bundle: Path, app_name: str | None) -> Path:
    macos_dir = bundle / "Contents" / "MacOS"
    if not macos_dir.is_dir():
        raise SmokeTestError(f"macOS app bundle is missing Contents/MacOS: {bundle}")

    plist_executable = None
    plist_path = bundle / "Contents" / "Info.plist"
    if plist_path.is_file():
        try:
            with plist_path.open("rb") as plist_file:
                plist = plistlib.load(plist_file)
            plist_executable = str(plist.get("CFBundleExecutable") or "").strip() or None
        except Exception as exc:
            raise SmokeTestError(f"could not read app bundle Info.plist: {plist_path}") from exc

    candidates = _candidate_names(bundle, plist_executable or app_name)
    for candidate_name in candidates:
        candidate = macos_dir / candidate_name
        if candidate.is_file():
            return candidate

    executable_children = [
        child
        for child in sorted(macos_dir.iterdir())
        if child.is_file() and os.access(child, os.X_OK)
    ]
    if executable_children:
        return executable_children[0]

    raise SmokeTestError(f"could not resolve app bundle executable under {macos_dir}")


def _validate_executable(executable: Path, platform_key: str) -> Path:
    if not executable.is_file():
        raise SmokeTestError(f"packaged executable was not found: {executable}")
    if platform_key != "windows" and not os.access(executable, os.X_OK):
        raise SmokeTestError(f"packaged executable is not executable: {executable}")
    return executable


def resolve_executable(
    release_artifact: Path,
    *,
    platform_key: str | None = None,
    app_name: str | None = None,
) -> Path:
    """Resolve the runnable executable inside a staged platform artifact."""
    platform = _normalize_platform(platform_key)
    if not release_artifact.exists():
        raise SmokeTestError(f"release artifact was not created: {release_artifact}")

    if platform == "macos" and release_artifact.suffix.lower() == ".app":
        return _validate_executable(
            _macos_bundle_executable(release_artifact, app_name),
            platform,
        )

    if release_artifact.is_dir():
        suffix = ".exe" if platform == "windows" else ""
        candidates = [
            release_artifact / f"{candidate_name}{suffix}"
            for candidate_name in _candidate_names(release_artifact, app_name)
        ]
        for candidate in candidates:
            if candidate.is_file():
                return _validate_executable(candidate, platform)

        executable_children = [
            child
            for child in sorted(release_artifact.iterdir())
            if child.is_file() and (platform == "windows" or os.access(child, os.X_OK))
        ]
        if executable_children:
            return _validate_executable(executable_children[0], platform)

    return _validate_executable(release_artifact, platform)


def _isolated_environment(root: Path, platform_key: str) -> dict[str, str]:
    env = os.environ.copy()
    home = root / "home"
    config = root / "config"
    data = root / "data"
    cache = root / "cache"
    temp = root / "tmp"
    appdata = root / "AppData" / "Roaming"
    localappdata = root / "AppData" / "Local"
    for directory in (home, config, data, cache, temp, appdata, localappdata):
        directory.mkdir(parents=True, exist_ok=True)

    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config),
            "XDG_DATA_HOME": str(data),
            "XDG_CACHE_HOME": str(cache),
            "APPDATA": str(appdata),
            "LOCALAPPDATA": str(localappdata),
            "TMP": str(temp),
            "TEMP": str(temp),
            "TMPDIR": str(temp),
        }
    )
    if _normalize_platform(platform_key) == "linux":
        env["QT_QPA_PLATFORM"] = env.get("QT_QPA_PLATFORM") or "offscreen"
    else:
        env.pop("QT_QPA_PLATFORM", None)
    return env


def _format_command(command: list[str]) -> str:
    return " ".join(
        f'"{part}"' if any(char.isspace() for char in part) else part for part in command
    )


def run_smoke_test(
    executable: Path,
    *,
    platform_key: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [str(executable), PACKAGED_SMOKE_TEST_ARGUMENT]
    try:
        completed = subprocess.run(
            command,
            cwd=str(executable.parent),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise SmokeTestError(
            f"packaged executable timed out after {timeout_seconds:g}s: "
            f"{_format_command(command)}"
        ) from exc

    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        raise SmokeTestError(
            f"packaged executable failed with exit code {completed.returncode}: "
            f"{_format_command(command)}"
        )

    print(f"Packaged binary smoke test passed for {platform_key}: {executable}")
    return completed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default="dist/release_manifest.json",
        help="Path to the release manifest written by build.py.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("PACKAGED_SMOKE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        help="Seconds to wait for the packaged executable to exit.",
    )
    args = parser.parse_args(argv)

    try:
        manifest_path = Path(args.manifest)
        manifest = _read_manifest(manifest_path)
        platform_key = _normalize_platform(str(manifest.get("platform") or ""))
        artifact = _manifest_artifact_path(manifest_path, manifest)
        executable = resolve_executable(
            artifact,
            platform_key=platform_key,
            app_name=str(manifest.get("app_name") or ""),
        )

        with tempfile.TemporaryDirectory(prefix="isrc-packaged-smoke-") as temp_dir:
            env = _isolated_environment(Path(temp_dir), platform_key)
            run_smoke_test(
                executable,
                platform_key=platform_key,
                timeout_seconds=args.timeout,
                env=env,
            )
    except (OSError, ValueError, SmokeTestError) as exc:
        print(f"ERROR [packaged-smoke]: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
