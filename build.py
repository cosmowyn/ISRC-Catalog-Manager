#!/usr/bin/env python3
"""
Deterministic PyInstaller build helper for stable local releases.

Behavior:
- Builds the app from fixed repo metadata and a canonical repo layout.
- Prefers assets from ``build_assets/`` and falls back to older local layouts.
- Bundles an optional runtime splash into ``build_assets/`` for packaged builds.
- Cleans ``build/`` and ``dist/`` before each run.
- Stages a versioned release artifact under ``dist/release/``.
- Creates an upload-ready release archive under ``dist/release/packages/``.

Notes:
- Branding is customized by replacing the same-named files in ``build_assets/``
  before running this script.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
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
RESOURCES_DIRNAME = "resources"
VENV_DIR = ".venv"
ICON_BASENAME = "app_logo"
LEGACY_ICON_BASENAME = "icon"
SPLASH_BASENAME = "splash"
SPLASH_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
WINDOWS_ICON_EXTENSIONS = (".ico", ".png", ".jpg", ".jpeg", ".bmp")
MACOS_ICON_EXTENSIONS = (".icns", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif")
LINUX_ICON_EXTENSIONS = (".png", ".ico", ".icns")
SPLASH_VERSION_FONT_SIZE = 12
SPLASH_VERSION_COLOR = (186, 214, 245)
SPLASH_VERSION_TEXT_GAP = 4


@dataclass(frozen=True)
class PyInstallerSelection:
    launcher_prefix: tuple[str, ...]
    verify_cmd: tuple[str, ...]
    label: str
    version_text: str
    fallback_reason: str | None = None


@dataclass(frozen=True)
class ResolutionResult:
    path: Path | None
    kind: str
    source_label: str
    detail: str


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


def _architecture_tag(machine: str | None = None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (machine or platform.machine() or "").lower())
    normalized = normalized.strip("-")
    if normalized in {"amd64", "x86-64", "x86_64"}:
        return "x64"
    if normalized in {"aarch64", "arm64"}:
        return "arm64"
    if normalized in {"i386", "i686", "x86"}:
        return "x86"
    return normalized or "unknown"


def _release_asset_basename(version: str) -> str:
    return f"{APP_NAME}-v{version}-{_platform_tag()}-{_architecture_tag()}"


def _build_splash_version_label(
    version: str,
    build_timestamp: datetime | date | None = None,
) -> str:
    stamp = build_timestamp or datetime.now()
    if isinstance(stamp, datetime):
        seconds_since_midnight = (stamp.hour * 3600) + (stamp.minute * 60) + stamp.second
        return f"Version: {version}-{stamp:%d%m%Y}.{seconds_since_midnight}"
    return f"Version: {version}-{stamp:%d%m%Y}.0"


def _venv_directories(project_root: Path) -> list[tuple[str, Path]]:
    candidates = [
        ("repo-local", project_root / VENV_DIR),
        ("parent-directory", project_root.parent / VENV_DIR),
    ]
    ordered: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for label, candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered.append((label, candidate))
    return ordered


def _venv_python_candidates(project_root: Path) -> list[tuple[str, Path]]:
    python_subpath = Path("Scripts/python.exe" if _is_windows() else "bin/python")
    # Keep the venv launcher path intact instead of resolving symlinks back to the
    # base interpreter. On macOS/Linux, resolving `.venv/bin/python` can escape the
    # virtual environment and make module discovery behave like the global Python.
    return [
        (label, venv_dir / python_subpath) for label, venv_dir in _venv_directories(project_root)
    ]


def _resolve_build_python(project_root: Path) -> Path:
    candidates = [candidate for _, candidate in _venv_python_candidates(project_root)]
    candidates.append(Path(sys.executable).resolve())

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate

    checked = "\n".join(f"  - {candidate}" for candidate in candidates)
    raise FileNotFoundError(
        "Could not resolve a usable Python interpreter.\nChecked in order:\n" f"{checked}"
    )


def _venv_pyinstaller_candidates(project_root: Path) -> list[tuple[str, Path]]:
    if _is_windows():
        launcher_subpath = Path("Scripts/pyinstaller.exe")
        label_map = {
            "repo-local": "repo-local Windows executable",
            "parent-directory": "parent-directory Windows executable",
        }
    else:
        launcher_subpath = Path("bin/pyinstaller")
        label_map = {
            "repo-local": "repo-local venv executable",
            "parent-directory": "parent-directory venv executable",
        }

    return [
        (
            label_map.get(label, f"{label} venv executable"),
            venv_dir / launcher_subpath,
        )
        for label, venv_dir in _venv_directories(project_root)
    ]


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path.resolve())


def _format_cmd(parts: tuple[str, ...] | list[str]) -> str:
    formatted: list[str] = []
    for part in parts:
        if any(char.isspace() for char in part):
            formatted.append(f'"{part}"')
        else:
            formatted.append(part)
    return " ".join(formatted)


def _indented_lines(text: str, prefix: str = "    ") -> list[str]:
    return [f"{prefix}{line}" for line in text.splitlines() if line.strip()]


def _top_level_python_files(project_root: Path) -> list[Path]:
    return sorted(path.resolve() for path in project_root.glob("*.py") if path.is_file())


def _resolve_entry_script(project_root: Path) -> Path:
    entry_script = (project_root / ENTRY_SCRIPT).resolve()
    if entry_script.is_file():
        return entry_script

    lines = [
        "ERROR [entry-script]: Canonical entry script was not found.",
        f"Expected: {entry_script}",
        f"Current working directory: {Path.cwd().resolve()}",
        f"Project root: {project_root.resolve()}",
    ]

    nearby_python = _top_level_python_files(project_root)
    if nearby_python:
        lines.append("Top-level Python files found nearby:")
        lines.extend(f"  - {path.name}" for path in nearby_python)
    else:
        lines.append("Top-level Python files found nearby: none")

    legacy_main = (project_root / "main.py").resolve()
    if legacy_main.is_file():
        lines.append(f"Legacy-looking candidate detected: {legacy_main}")

    lines.append("No automatic fallback entry script was used; build.py requires ISRC_manager.py.")
    raise FileNotFoundError("\n".join(lines))


def _pyinstaller_discovery_error(
    project_root: Path,
    build_python: Path,
    attempts: list[dict[str, str]],
) -> RuntimeError:
    lines = [
        "ERROR [pyinstaller]: Could not discover a working PyInstaller launcher.",
        f"Build Python: {build_python}",
        f"Project root: {project_root.resolve()}",
        "Tried in order:",
    ]

    for attempt in attempts:
        lines.append(f"- {attempt['label']}: {attempt['status']}")
        lines.append(f"  command: {attempt['command']}")
        stdout = attempt.get("stdout", "").strip()
        stderr = attempt.get("stderr", "").strip()
        if stdout:
            lines.append("  stdout:")
            lines.extend(_indented_lines(stdout, prefix="    "))
        if stderr:
            lines.append("  stderr:")
            lines.extend(_indented_lines(stderr, prefix="    "))

    local_executables = _venv_pyinstaller_candidates(project_root)
    lines.extend(
        [
            "Windows discovery order:" if _is_windows() else "Discovery order:",
            *[f"{index}. {path}" for index, (_, path) in enumerate(local_executables, start=1)],
            f"{len(local_executables) + 1}. {build_python} -m PyInstaller",
            f"{len(local_executables) + 2}. pyinstaller (PATH fallback)",
            "Action: install PyInstaller in the repo-local or parent-directory .venv, "
            "install it into the interpreter running build.py, "
            "or expose pyinstaller on PATH.",
        ]
    )

    return RuntimeError("\n".join(lines))


def _pyinstaller_missing_module_output(*texts: str) -> bool:
    patterns = (
        "No module named PyInstaller",
        "No module named 'PyInstaller'",
        'No module named "PyInstaller"',
        "ModuleNotFoundError: No module named 'PyInstaller'",
        'ModuleNotFoundError: No module named "PyInstaller"',
    )
    return any(pattern in text for text in texts if text for pattern in patterns)


def _select_pyinstaller(project_root: Path, build_python: Path) -> PyInstallerSelection:
    attempts: list[dict[str, str]] = []
    candidates: list[dict[str, object]] = []
    local_executables = _venv_pyinstaller_candidates(project_root)
    for index, (label, local_executable) in enumerate(local_executables):
        fallback_reason = None
        if index > 0:
            earlier_labels = [earlier_label for earlier_label, _ in local_executables[:index]]
            fallback_reason = f"{', '.join(earlier_labels)} were unavailable or failed verification"
        candidates.append(
            {
                "label": label,
                "launcher_prefix": (str(local_executable),),
                "verify_cmd": (str(local_executable), "--version"),
                "fallback_reason": fallback_reason,
                "available": local_executable.is_file(),
                "missing_status": f"missing file: {local_executable}",
            }
        )

    candidates.append(
        {
            "label": "current interpreter module",
            "launcher_prefix": (str(build_python), "-m", "PyInstaller"),
            "verify_cmd": (str(build_python), "-m", "PyInstaller", "--version"),
            "fallback_reason": (
                f"{', '.join(label for label, _ in local_executables)} "
                "were unavailable or failed verification"
                if local_executables
                else None
            ),
            "available": True,
            "missing_status": "",
        }
    )
    path_pyinstaller = shutil.which("pyinstaller")
    candidates.append(
        {
            "label": "PATH fallback",
            "launcher_prefix": ("pyinstaller",),
            "verify_cmd": ("pyinstaller", "--version"),
            "fallback_reason": (
                f"{', '.join(label for label, _ in local_executables)}, "
                "and current interpreter module were unavailable or failed verification"
                if local_executables
                else "current interpreter module was unavailable or failed verification"
            ),
            "available": bool(path_pyinstaller),
            "missing_status": "not found on PATH",
        }
    )

    for candidate in candidates:
        label = str(candidate["label"])
        launcher_prefix = tuple(candidate["launcher_prefix"])
        verify_cmd = tuple(candidate["verify_cmd"])

        if not bool(candidate["available"]):
            attempts.append(
                {
                    "label": label,
                    "status": str(candidate["missing_status"]),
                    "command": _format_cmd(list(verify_cmd)),
                }
            )
            continue

        result = subprocess.run(
            list(verify_cmd),
            capture_output=True,
            text=True,
        )
        missing_module_output = _pyinstaller_missing_module_output(
            result.stdout or "",
            result.stderr or "",
        )
        if result.returncode == 0 and not missing_module_output:
            version_text = (result.stdout or result.stderr or "").strip() or "unknown"
            return PyInstallerSelection(
                launcher_prefix=launcher_prefix,
                verify_cmd=verify_cmd,
                label=label,
                version_text=version_text,
                fallback_reason=(
                    str(candidate["fallback_reason"])
                    if candidate["fallback_reason"] is not None
                    else None
                ),
            )

        attempts.append(
            {
                "label": label,
                "status": (
                    "verification output indicates missing PyInstaller module"
                    if missing_module_output
                    else f"verification failed with exit code {result.returncode}"
                ),
                "command": _format_cmd(list(verify_cmd)),
                "stdout": result.stdout or "",
                "stderr": result.stderr or "",
            }
        )

    raise _pyinstaller_discovery_error(project_root, build_python, attempts)


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
        raise RuntimeError("Could not import PySide6 to convert the Windows icon to .ico.") from exc

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


def _icon_extensions() -> tuple[str, ...]:
    if _is_windows():
        return WINDOWS_ICON_EXTENSIONS
    if _is_macos():
        return MACOS_ICON_EXTENSIONS
    return LINUX_ICON_EXTENSIONS


def _asset_locations(project_root: Path, canonical_dir: Path) -> tuple[tuple[Path, str, str], ...]:
    return (
        (canonical_dir, "build_assets", "canonical"),
        (project_root / RESOURCES_DIRNAME, "resources", "fallback"),
        (project_root, "repo root", "fallback"),
    )


def _resolve_asset_candidate(
    project_root: Path,
    *,
    asset_label: str,
    canonical_dir: Path,
    basenames: tuple[str, ...],
    extensions: tuple[str, ...],
) -> ResolutionResult:
    checked: list[str] = []

    for location_path, source_label, kind in _asset_locations(project_root, canonical_dir):
        for basename in basenames:
            for extension in extensions:
                candidate = location_path / f"{basename}{extension}"
                checked.append(_display_path(candidate, project_root))
                if not candidate.is_file():
                    continue

                candidate_resolved = candidate.resolve()
                if kind == "canonical":
                    detail = (
                        f"selected canonical {asset_label} asset "
                        f"{_display_path(candidate_resolved, project_root)}"
                    )
                else:
                    detail = (
                        f"canonical {asset_label} asset was unavailable; selected fallback "
                        f"{_display_path(candidate_resolved, project_root)} from {source_label}"
                    )
                return ResolutionResult(
                    path=candidate_resolved,
                    kind=kind,
                    source_label=source_label,
                    detail=detail,
                )

    return ResolutionResult(
        path=None,
        kind="missing",
        source_label="not found",
        detail=f"no {asset_label} asset found. Checked: {', '.join(checked)}",
    )


def _resolve_icon(project_root: Path) -> ResolutionResult:
    result = _resolve_asset_candidate(
        project_root,
        asset_label="icon",
        canonical_dir=project_root / "build_assets" / "icons",
        basenames=(ICON_BASENAME, LEGACY_ICON_BASENAME),
        extensions=_icon_extensions(),
    )
    if result.path is None:
        return result

    try:
        if _is_windows() and result.path.suffix.lower() != ".ico":
            converted = _convert_image_to_ico_qt(result.path, project_root).resolve()
            return ResolutionResult(
                path=converted,
                kind=result.kind,
                source_label=result.source_label,
                detail=(
                    f"{result.detail}; converted "
                    f"{_display_path(result.path, project_root)} to "
                    f"{_display_path(converted, project_root)}"
                ),
            )

        if _is_macos() and result.path.suffix.lower() != ".icns":
            converted = _convert_image_to_icns_mac(result.path, project_root).resolve()
            return ResolutionResult(
                path=converted,
                kind=result.kind,
                source_label=result.source_label,
                detail=(
                    f"{result.detail}; converted "
                    f"{_display_path(result.path, project_root)} to "
                    f"{_display_path(converted, project_root)}"
                ),
            )
    except Exception as exc:
        raise RuntimeError(
            f"icon conversion failed for {_display_path(result.path, project_root)}: {exc}"
        ) from exc

    return result


def _resolve_runtime_splash_asset(project_root: Path) -> ResolutionResult:
    return _resolve_asset_candidate(
        project_root,
        asset_label="splash",
        canonical_dir=project_root / "build_assets",
        basenames=(SPLASH_BASENAME,),
        extensions=SPLASH_EXTENSIONS,
    )


def _load_splash_version_font(font_size: int):
    try:
        from PIL import ImageFont
    except Exception as exc:
        raise RuntimeError("Could not import Pillow to load the splash version font.") from exc

    font_candidates = (
        "DejaVuSans.ttf",
        "Arial.ttf",
        "LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for candidate in font_candidates:
        try:
            return ImageFont.truetype(candidate, font_size)
        except OSError:
            continue

    fallback_font = ImageFont.load_default()
    font_variant = getattr(fallback_font, "font_variant", None)
    if callable(font_variant):
        try:
            return fallback_font.font_variant(size=font_size)
        except (AttributeError, OSError, TypeError, ValueError):
            pass
    return fallback_font


def _is_splash_divider_pixel(pixel: tuple[int, int, int, int]) -> bool:
    red, green, blue, alpha = pixel
    return (
        alpha > 0
        and 170 <= red <= 249
        and 205 <= green <= 252
        and 235 <= blue <= 255
        and green >= red + 2
        and blue >= green - 10
    )


def _locate_splash_divider(image) -> tuple[int, int, int]:
    width, height = image.size
    search_x_start = round(width * 0.20)
    search_x_stop = round(width * 0.95)
    search_y_start = round(height * 0.35)
    search_y_stop = round(height * 0.65)
    minimum_run = round(width * 0.15)
    best_run: tuple[int, int, int, int] | None = None

    for y in range(search_y_start, search_y_stop):
        run_start: int | None = None
        for x in range(search_x_start, search_x_stop):
            if _is_splash_divider_pixel(image.getpixel((x, y))):
                if run_start is None:
                    run_start = x
                continue

            if run_start is None:
                continue

            run_end = x - 1
            run_length = run_end - run_start + 1
            if run_length >= minimum_run and (best_run is None or run_length > best_run[0]):
                best_run = (run_length, run_start, run_end, y)
            run_start = None

        if run_start is not None:
            run_end = search_x_stop - 1
            run_length = run_end - run_start + 1
            if run_length >= minimum_run and (best_run is None or run_length > best_run[0]):
                best_run = (run_length, run_start, run_end, y)

    if best_run is not None:
        _, run_start, run_end, y = best_run
        return run_start, run_end, y

    fallback_start = round(width * 0.404)
    fallback_end = round(width * 0.807)
    fallback_y = round(height * 0.548)
    return fallback_start, fallback_end, fallback_y


def _stamp_runtime_splash_asset(
    project_root: Path,
    splash_result: ResolutionResult,
    *,
    app_version: str,
    build_timestamp: datetime | date | None = None,
) -> ResolutionResult:
    if splash_result.path is None:
        return splash_result

    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise RuntimeError("Could not import Pillow to stamp the runtime splash.") from exc

    version_label = _build_splash_version_label(app_version, build_timestamp)
    output_path = (_generated_assets_dir(project_root) / f"{SPLASH_BASENAME}.png").resolve()

    with Image.open(splash_result.path) as source_image:
        image = source_image.convert("RGBA")

    line_start, _, line_y = _locate_splash_divider(image)
    draw = ImageDraw.Draw(image)
    font = _load_splash_version_font(SPLASH_VERSION_FONT_SIZE)
    text_bbox = draw.textbbox((0, 0), version_label, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_x = max(0, min(line_start - text_bbox[0], image.width - text_width - 12))
    text_y = max(0, line_y - text_bbox[3] - SPLASH_VERSION_TEXT_GAP)
    draw.text((text_x, text_y), version_label, fill=SPLASH_VERSION_COLOR, font=font)
    image.save(output_path, format="PNG")

    return ResolutionResult(
        path=output_path,
        kind=splash_result.kind,
        source_label=splash_result.source_label,
        detail=(
            f"{splash_result.detail}; stamped {version_label!r} above the divider at "
            f"x={line_start}, y={line_y} and wrote "
            f"{_display_path(output_path, project_root)}"
        ),
    )


def _diag(name: str, value: str) -> None:
    print(f"[diag] {name}: {value}")


def _format_resolution(result: ResolutionResult, project_root: Path) -> str:
    if result.path is None:
        return f"missing ({result.detail})"
    return (
        f"{_display_path(result.path, project_root)} [{result.kind}; source={result.source_label}; "
        f"detail={result.detail}]"
    )


def _print_build_diagnostics(
    project_root: Path,
    build_python: Path,
    entry_script: Path,
    pyinstaller: PyInstallerSelection,
    icon: ResolutionResult,
    splash: ResolutionResult,
) -> None:
    _diag("working directory", str(Path.cwd().resolve()))
    _diag("project root", str(project_root.resolve()))
    _diag("build python", str(build_python))
    _diag("sys.executable", sys.executable)
    _diag("sys.version", sys.version.replace(chr(10), " "))
    _diag("entry script", str(entry_script))
    _diag(
        "pyinstaller launcher",
        f"{pyinstaller.label} -> {_format_cmd(list(pyinstaller.launcher_prefix))}",
    )
    _diag("pyinstaller verify", _format_cmd(list(pyinstaller.verify_cmd)))
    _diag("pyinstaller version", pyinstaller.version_text)
    if pyinstaller.fallback_reason:
        _diag("pyinstaller fallback reason", pyinstaller.fallback_reason)
    _diag("icon", _format_resolution(icon, project_root))
    _diag("splash", _format_resolution(splash, project_root))


def _add_data_separator() -> str:
    return ";" if _is_windows() else ":"


def _pyinstaller_add_data(source: str | Path, destination: str) -> str:
    return f"{source}{_add_data_separator()}{destination}"


def _pyinstaller_cmd(
    pyinstaller_launcher: tuple[str, ...],
    entry_script: Path,
    app_name: str,
    icon: str | None,
    runtime_splash_asset: str | None,
) -> list[str]:
    cmd = [
        *pyinstaller_launcher,
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
    release_package: Path | None = None,
) -> Path:
    manifest_path = dist_dir / "release_manifest.json"
    payload = {
        "app_name": APP_NAME,
        "app_version": app_version,
        "platform": _platform_tag(),
        "architecture": _architecture_tag(),
        "source_artifact": str(source_artifact),
        "release_artifact": str(staged_artifact),
    }
    if release_package is not None:
        payload["release_package"] = str(release_package)
        payload["release_asset_name"] = release_package.name
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

    return target


def _release_package_path(release_dir: Path, *, app_version: str) -> Path:
    packages_dir = release_dir / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    extension = ".zip" if _is_windows() or _is_macos() else ".tar.gz"
    return packages_dir / f"{_release_asset_basename(app_version)}{extension}"


def _zip_release_artifact(staged_artifact: Path, package_path: Path) -> None:
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if staged_artifact.is_dir():
            root = staged_artifact.parent
            for path in sorted(staged_artifact.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root))
            return

        archive.write(staged_artifact, staged_artifact.name)


def _tar_release_artifact(staged_artifact: Path, package_path: Path) -> None:
    with tarfile.open(package_path, "w:gz") as archive:
        archive.add(staged_artifact, arcname=staged_artifact.name, recursive=True)


def _package_release_artifact(
    staged_artifact: Path,
    dist_dir: Path,
    *,
    app_version: str,
) -> Path:
    if not staged_artifact.exists():
        raise FileNotFoundError(f"Release artifact does not exist: {staged_artifact}")

    package_path = _release_package_path(dist_dir / "release", app_version=app_version)
    package_path.unlink(missing_ok=True)

    if _is_windows() or _is_macos():
        _zip_release_artifact(staged_artifact, package_path)
    else:
        _tar_release_artifact(staged_artifact, package_path)

    if not package_path.exists() or package_path.stat().st_size <= 0:
        raise RuntimeError(f"Release package was not created or is empty: {package_path}")
    return package_path


def _clean_build_directories(project_root: Path) -> None:
    for directory_name in ("build", "dist"):
        path = project_root / directory_name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def main() -> int:
    project_root = PROJECT_ROOT

    try:
        entry_script = _resolve_entry_script(project_root)
    except Exception as exc:
        print(str(exc))
        return 1

    try:
        app_version = _project_version(PYPROJECT_PATH)
    except Exception as exc:
        print(f"ERROR [metadata]: {exc}")
        return 1

    try:
        build_python = _resolve_build_python(project_root)
    except Exception as exc:
        print(f"ERROR [python]: {exc}")
        return 1

    os.chdir(project_root)
    print(f"OS: {_platform_tag()}  |  Project: {project_root}")

    _clean_build_directories(project_root)

    try:
        pyinstaller = _select_pyinstaller(project_root, build_python)
    except Exception as exc:
        print(str(exc))
        return 1

    try:
        icon_result = _resolve_icon(project_root)
    except Exception as exc:
        print(f"ERROR [icon]: {exc}")
        return 1

    try:
        splash_result = _resolve_runtime_splash_asset(project_root)
    except Exception as exc:
        print(f"ERROR [splash]: {exc}")
        return 1

    try:
        splash_result = _stamp_runtime_splash_asset(
            project_root,
            splash_result,
            app_version=app_version,
        )
    except Exception as exc:
        print(f"ERROR [splash]: {exc}")
        return 1

    _print_build_diagnostics(
        project_root,
        build_python,
        entry_script,
        pyinstaller,
        icon_result,
        splash_result,
    )

    cmd = _pyinstaller_cmd(
        pyinstaller_launcher=pyinstaller.launcher_prefix,
        entry_script=entry_script,
        app_name=APP_NAME,
        icon=str(icon_result.path) if icon_result.path else None,
        runtime_splash_asset=str(splash_result.path) if splash_result.path else None,
    )

    print("\nRunning:")
    print(_format_cmd(cmd))
    print()

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            text=True,
            capture_output=True,
        )
    except Exception as exc:
        print("\nERROR [build]: Build invocation failed.")
        print(str(exc))
        return 1

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if _pyinstaller_missing_module_output(result.stdout or "", result.stderr or ""):
        print("\nERROR [build]: PyInstaller launcher reported a missing module.")
        return 1
    if result.returncode != 0:
        print("\nERROR [build]: PyInstaller returned a non-zero exit code.")
        print(f"Return code: {result.returncode}")
        return result.returncode

    out_path = project_root / "dist"
    built_artifact = _find_built_artifact(project_root)
    if not built_artifact.exists():
        print(
            "\nERROR [artifact]: PyInstaller returned success, but expected output was not found."
        )
        print(
            "Expected one of: "
            f"{', '.join(str(path) for path in _expected_artifact_candidates(project_root))}"
        )

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
    try:
        release_package = _package_release_artifact(
            staged_artifact,
            out_path,
            app_version=app_version,
        )
    except Exception as exc:
        print(f"\nERROR [package]: {exc}")
        return 3

    _write_release_manifest(
        out_path,
        built_artifact,
        staged_artifact,
        app_version=app_version,
        release_package=release_package,
    )

    print("\nBuild complete.")
    print(f"Output folder: {out_path}")
    print(f"Release artifact: {staged_artifact}")
    print(f"Release package: {release_package}")
    print(f"Release manifest: {out_path / 'release_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
