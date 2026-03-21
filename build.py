#!/usr/bin/env python3
"""
Deterministic PyInstaller build helper for stable local releases.

Behavior:
- Builds the app from fixed repo metadata and fixed build assets.
- Uses icons from ``build_assets/icons/app_logo.*``.
- Bundles an optional runtime splash from ``build_assets/splash.*``.
- Cleans ``build/`` and ``dist/`` before each run.
- Stages a versioned release artifact under ``dist/release/``.

Notes:
- Branding is customized by replacing the same-named files in ``build_assets/``
  before running this script.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from isrc_manager.constants import APP_NAME as DEFAULT_APP_NAME
except Exception:
    DEFAULT_APP_NAME = "ISRCManager"


ENTRY_SCRIPT = "ISRC_manager.py"
APP_NAME = DEFAULT_APP_NAME
PROJECT_ROOT = Path(__file__).resolve().parent
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
BUILD_ASSETS_DIR = PROJECT_ROOT / "build_assets"
ICONS_DIR = BUILD_ASSETS_DIR / "icons"
ICON_BASENAME = "app_logo"
SPLASH_BASENAME = "splash"
SPLASH_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif")


def _is_windows() -> bool:
    return os.name == "nt"


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _platform_tag() -> str:
    if _is_windows():
        return "windows"
    if _is_macos():
        return "macos"
    return "linux"


def _generated_assets_dir(project_root: Path) -> Path:
    generated = project_root / "build" / "generated_assets"
    generated.mkdir(parents=True, exist_ok=True)
    return generated


def _icons_dir(project_root: Path) -> Path:
    return project_root / "build_assets" / "icons"


def _windows_icon_path(project_root: Path) -> Path:
    return _icons_dir(project_root) / f"{ICON_BASENAME}.ico"


def _macos_icon_path(project_root: Path) -> Path:
    return _icons_dir(project_root) / f"{ICON_BASENAME}.icns"


def _png_icon_path(project_root: Path) -> Path:
    return _icons_dir(project_root) / f"{ICON_BASENAME}.png"


def _project_version(pyproject_path: Path) -> str:
    try:
        import tomllib

        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        version = str(data.get("project", {}).get("version") or "").strip()
        if version:
            return version
    except Exception:
        pass

    text = pyproject_path.read_text(encoding="utf-8")
    match = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"\s*$', text)
    if not match:
        raise RuntimeError(f"Could not determine project version from {pyproject_path}")
    return match.group(1).strip()


def _release_basename(version: str) -> str:
    return f"{APP_NAME}-{version}-{_platform_tag()}"


def _resolve_build_python() -> Path:
    build_python = Path(sys.executable).resolve()
    if not build_python.exists():
        raise FileNotFoundError(f"Current Python interpreter does not exist:\n  {build_python}")
    return build_python


def _print_build_diagnostics(project_root: Path, build_python: Path) -> None:
    print(f"Build Python: {build_python}")
    print(f"sys.executable: {sys.executable}")
    print(f"sys.version: {sys.version.replace(chr(10), ' ')}")
    print(f"Current working directory: {Path.cwd().resolve()}")
    print(f"Project root: {project_root}")


def _verify_pyinstaller(build_python: Path) -> None:
    result = subprocess.run(
        [str(build_python), "-m", "PyInstaller", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        version_text = (result.stdout or result.stderr or "").strip()
        if version_text:
            print(f"PyInstaller version: {version_text}")
        return

    print("ERROR: PyInstaller is not available in the current build interpreter.")
    print(f"Interpreter: {build_python}")
    if result.stdout:
        print("\nPyInstaller stdout:")
        print(result.stdout)
    if result.stderr:
        print("\nPyInstaller stderr:")
        print(result.stderr)
    raise RuntimeError(
        "PyInstaller check failed. Install PyInstaller into the same interpreter "
        "that is running build.py."
    )


def _require_tool(tool_name: str) -> None:
    if shutil.which(tool_name) is None:
        raise RuntimeError(
            f"Required tool '{tool_name}' not found on PATH.\n"
            "Provide the native platform icon file instead or install the missing tool."
        )


def _convert_image_to_icns_mac(image_path: Path, project_root: Path) -> Path:
    if not _is_macos():
        raise RuntimeError("ICNS conversion is only supported on macOS in this script.")

    _require_tool("sips")
    _require_tool("iconutil")

    out_dir = _generated_assets_dir(project_root) / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)

    iconset_dir = out_dir / f"{ICON_BASENAME}.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir, ignore_errors=True)
    iconset_dir.mkdir(parents=True, exist_ok=True)

    sizes = [16, 32, 128, 256, 512]
    for base in sizes:
        out_png_1x = iconset_dir / f"icon_{base}x{base}.png"
        subprocess.run(
            [
                "sips",
                "-z",
                str(base),
                str(base),
                str(image_path),
                "--out",
                str(out_png_1x),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        out_png_2x = iconset_dir / f"icon_{base}x{base}@2x.png"
        subprocess.run(
            [
                "sips",
                "-z",
                str(base * 2),
                str(base * 2),
                str(image_path),
                "--out",
                str(out_png_2x),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    out_icns = out_dir / f"{ICON_BASENAME}.icns"
    out_icns.unlink(missing_ok=True)
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(out_icns)],
        check=True,
        capture_output=True,
        text=True,
    )
    shutil.rmtree(iconset_dir, ignore_errors=True)

    if not out_icns.exists():
        raise RuntimeError("ICNS conversion failed: output file was not created.")
    return out_icns


def _convert_image_to_ico_qt(image_path: Path, project_root: Path) -> Path:
    try:
        from PySide6.QtGui import QImage
    except Exception as exc:
        raise RuntimeError(
            "Could not import PySide6 to convert the Windows icon to .ico."
        ) from exc

    out_dir = _generated_assets_dir(project_root) / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_ico = out_dir / f"{ICON_BASENAME}.ico"

    image = QImage(str(image_path))
    if image.isNull():
        raise RuntimeError(f"Could not load icon image for ICO conversion: {image_path}")

    out_ico.unlink(missing_ok=True)
    if not image.save(str(out_ico), "ICO") or not out_ico.exists():
        raise RuntimeError(
            f"ICO conversion failed for '{image_path}'. "
            "Provide a valid .ico file or a readable source image."
        )
    return out_ico


def _resolve_icon(project_root: Path) -> str | None:
    windows_icon = _windows_icon_path(project_root)
    macos_icon = _macos_icon_path(project_root)
    png_icon = _png_icon_path(project_root)

    if _is_windows():
        if windows_icon.exists():
            return str(windows_icon)
        if png_icon.exists():
            return str(_convert_image_to_ico_qt(png_icon, project_root))
        return None

    if _is_macos():
        if macos_icon.exists():
            return str(macos_icon)
        if png_icon.exists():
            return str(_convert_image_to_icns_mac(png_icon, project_root))
        return None

    if png_icon.exists():
        return str(png_icon)
    return None


def _resolve_runtime_splash_asset(project_root: Path) -> str | None:
    for ext in SPLASH_EXTENSIONS:
        candidate = project_root / "build_assets" / f"{SPLASH_BASENAME}{ext}"
        if candidate.exists():
            return str(candidate)
    return None


def _add_data_separator() -> str:
    return ";" if _is_windows() else ":"


def _pyinstaller_add_data(source: str | Path, destination: str) -> str:
    return f"{source}{_add_data_separator()}{destination}"


def _pyinstaller_cmd(
    build_python: Path,
    entry_script: Path,
    app_name: str,
    icon: str | None,
    runtime_splash_asset: str | None,
) -> list[str]:
    cmd = [
        str(build_python),
        "-m",
        "PyInstaller",
        str(entry_script),
        "--name",
        app_name,
        "--noconfirm",
        "--clean",
        "--windowed",
        "--log-level",
        "INFO",
    ]

    if _is_windows():
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    if runtime_splash_asset:
        cmd.extend(
            [
                "--add-data",
                _pyinstaller_add_data(runtime_splash_asset, "build_assets"),
            ]
        )

    if icon:
        cmd.extend(["--icon", icon])

    return cmd


def _expected_artifact_candidates(project_root: Path) -> list[Path]:
    dist_dir = project_root / "dist"
    if _is_windows():
        return [dist_dir / f"{APP_NAME}.exe"]
    if _is_macos():
        return [dist_dir / f"{APP_NAME}.app", dist_dir / APP_NAME]
    return [dist_dir / APP_NAME]


def _find_built_artifact(project_root: Path) -> Path:
    candidates = _expected_artifact_candidates(project_root)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _write_release_manifest(
    dist_dir: Path,
    source_artifact: Path,
    staged_artifact: Path,
    *,
    app_version: str,
) -> Path:
    manifest_path = dist_dir / "release_manifest.json"
    payload = {
        "app_name": APP_NAME,
        "app_version": app_version,
        "platform": _platform_tag(),
        "source_artifact": str(source_artifact),
        "release_artifact": str(staged_artifact),
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


def _stage_release_artifact(source_artifact: Path, dist_dir: Path, *, app_version: str) -> Path:
    release_dir = dist_dir / "release"
    release_dir.mkdir(parents=True, exist_ok=True)

    if source_artifact.is_dir():
        target = release_dir / _release_basename(app_version)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source_artifact, target)
    else:
        target = release_dir / f"{_release_basename(app_version)}{source_artifact.suffix}"
        target.unlink(missing_ok=True)
        shutil.copy2(source_artifact, target)

    _write_release_manifest(
        dist_dir,
        source_artifact,
        target,
        app_version=app_version,
    )
    return target


def main() -> int:
    project_root = PROJECT_ROOT
    entry_script = (project_root / ENTRY_SCRIPT).resolve()
    if not entry_script.exists():
        print(f"ERROR: entry script not found: {entry_script}")
        return 1

    app_version = _project_version(PYPROJECT_PATH)

    os.chdir(project_root)
    print(f"OS: {_platform_tag()}  |  Project: {project_root}")

    build_python = _resolve_build_python()
    _print_build_diagnostics(project_root, build_python)
    try:
        _verify_pyinstaller(build_python)
    except Exception as exc:
        print(str(exc))
        return 1

    try:
        runtime_splash_asset = _resolve_runtime_splash_asset(project_root)
        icon = _resolve_icon(project_root)
    except Exception as exc:
        print(f"ERROR: Could not resolve build assets.\n{exc}")
        return 1

    if runtime_splash_asset:
        print(f"Bundling runtime splash asset: {runtime_splash_asset}")
    else:
        print("No runtime splash asset configured.")

    if icon:
        print(f"Using icon asset: {icon}")
    else:
        print("No icon asset configured for this platform.")

    for directory_name in ("build", "dist"):
        path = project_root / directory_name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    cmd = _pyinstaller_cmd(
        build_python=build_python,
        entry_script=entry_script,
        app_name=APP_NAME,
        icon=icon,
        runtime_splash_asset=runtime_splash_asset,
    )

    print("\nRunning:")
    print(" ".join(f'"{part}"' if " " in part else part for part in cmd))
    print()

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            text=True,
            capture_output=True,
        )
    except Exception as exc:
        print("\nBuild failed.")
        print(str(exc))
        return 1

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if result.returncode != 0:
        print("\nBuild failed.")
        print(f"Return code: {result.returncode}")
        return result.returncode

    out_path = project_root / "dist"
    built_artifact = _find_built_artifact(project_root)
    if not built_artifact.exists():
        print("\nERROR: PyInstaller returned success, but expected output was not found:")
        print(f"Expected one of: {', '.join(str(path) for path in _expected_artifact_candidates(project_root))}")

        if out_path.exists():
            print("\nContents of dist/:")
            for artifact in out_path.rglob("*"):
                rel = artifact.relative_to(out_path)
                print(f"  {rel}")
        else:
            print("\nNote: dist/ folder does not exist at all.")

        print("\nPossible causes:")
        print("- Antivirus or endpoint protection quarantined the output immediately.")
        print("- Build actually failed but only logged to stderr.")
        print("- APP_NAME mismatch versus the produced artifact name.")
        return 2

    staged_artifact = _stage_release_artifact(
        built_artifact,
        out_path,
        app_version=app_version,
    )

    print("\nBuild complete.")
    print(f"Output folder: {out_path}")
    print(f"Release artifact: {staged_artifact}")
    print(f"Release manifest: {out_path / 'release_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
