#!/usr/bin/env python3
"""
Build and install ISRCManager (PySide6) without bundling a database.

- Detects and re-execs into ./.venv if present.
- Ensures PyInstaller is available in the active environment.
- Builds a GUI app (default --onedir; pass --onefile to override).
- Prompts the user for an install directory (GUI); defaults to a safe user path.
- Creates a project layout there and copies the packaged app.
- Does NOT package or copy any existing Database files.

Usage:
  python build_and_install.py
  python build_and_install.py --onefile
  python build_and_install.py --console   # show console window (debug)
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
import venv

from typing import Optional
# ---- Project constants ----
PROJECT_ROOT = Path(__file__).resolve().parent
# ENTRY_SCRIPT is initially None; will be set by pick_entry_script if needed
ENTRY_SCRIPT: Path | None = None
APP_NAME     = "ISRCManager"
ICON_PATH: Path | None = None
def pick_entry_script() -> Path:
    """
    Open a file picker dialog to let the user choose a Python entry script (*.py).
    Returns the selected Path, or raises SystemExit if canceled.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
        root = tk.Tk()
        root.withdraw()
        root.update()
        messagebox.showinfo(
            title="ISRCManager Installer",
            message="Select the Python entry script for your application (.py)."
        )
        script_path = filedialog.askopenfilename(
            title="Select entry script",
            filetypes=[("Python scripts", "*.py")],
            initialdir=str(PROJECT_ROOT)
        )
        root.destroy()
        if not script_path:
            raise SystemExit("[error] No entry script selected. Aborting.")
        p = Path(script_path)
        if not p.exists() or not p.is_file() or p.suffix.lower() != ".py":
            raise SystemExit(f"[error] Invalid entry script selected: {p}")
        return p
    except Exception as e:
        raise SystemExit(f"[error] Could not select entry script: {e}")

# Optional assets (don’t include Database)
ASSETS = [PROJECT_ROOT / "LogoWhite.png"]  # will be placed under assets/ if present

# ---- Helpers ----
def in_venv() -> bool:
    return (
        hasattr(sys, "real_prefix")
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
        or "VIRTUAL_ENV" in os.environ
    )

def reexec_in_dotvenv_if_found():
    venv_dir = PROJECT_ROOT / ".venv"
    if not in_venv() and venv_dir.exists():
        py = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if py.exists():
            print(f"[info] Re-executing inside virtualenv: {py}")
            os.execv(str(py), [str(py), __file__, *sys.argv[1:]])

def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        return
    except Exception:
        pass
    print("[info] Installing PyInstaller…")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"])

def add_data_arg(src: Path, dst_rel: str) -> list[str]:
    # Do NOT add Database here (we’re not bundling it).
    sep = ";" if os.name == "nt" else ":"
    return ["--add-data", f"{src}{sep}{dst_rel}"]

def discover_asset_datas() -> list[str]:
    args: list[str] = []
    for p in ASSETS:
        if p.exists():
            args += add_data_arg(p, f"assets/{p.name}")
    return args

def safe_default_install_dir() -> Path:
    system = platform.system().lower()
    home = Path.home()
    if system == "darwin":  # macOS (user apps folder)
        candidate = home / "Applications" / APP_NAME
    elif system == "windows":
        local_appdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        candidate = local_appdata / APP_NAME
    else:  # linux / other unix
        candidate = home / ".local" / "share" / APP_NAME
    return candidate

def pick_install_dir(default_dir: Path) -> Path:
    # Try a GUI folder picker via Tkinter; fall back to default on headless.
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
        root = tk.Tk()
        root.withdraw()
        root.update()
        messagebox.showinfo(
            title="ISRCManager Installer",
            message="Select an installation folder (user-writable, no admin privileges required).",
        )
        # Ensure default exists so dialog can open there
        default_dir.parent.mkdir(parents=True, exist_ok=True)
        chosen = filedialog.askdirectory(
            initialdir=str(default_dir.parent),
            title="Choose installation folder",
            mustexist=False,
        )
        root.destroy()
        if chosen:
            return Path(chosen)
    except Exception as e:
        print(f"[warn] GUI picker unavailable ({e}); using default path.")
    return default_dir

def pick_icon_file() -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.update()
        system = platform.system().lower()
        if system == "darwin":
            filetypes = [("ICNS files", "*.icns")]
            title = "Select an icon file (.icns)"
        elif system == "windows":
            filetypes = [("ICO files", "*.ico")]
            title = "Select an icon file (.ico)"
        else:
            # For other systems, no icon selection
            root.destroy()
            return None
        icon_path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        root.destroy()
        if icon_path:
            return Path(icon_path)
    except Exception as e:
        print(f"[warn] Icon picker unavailable ({e}); skipping icon selection.")
    return None

def pick_readme_file() -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.update()
        filetypes = [("Text files", "*.txt"), ("All files", "*.*")]
        title = "Select a README file (.txt)"
        readme_path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        root.destroy()
        if readme_path:
            return Path(readme_path)
    except Exception as e:
        print(f"[warn] README picker unavailable ({e}); skipping README selection.")
    return None

# def make_project_layout(base_dir: Path):
#     """
#     Create a clean project directory structure WITHOUT copying any database files.
#     Layout:
#       <base_dir>/
#         ISRCManager[.app or dir or exe...]
#         Database/
#           backups/
#           exports/
#           logs/
#         README_INSTALL.txt
#     """
#     base_dir.mkdir(parents=True, exist_ok=True)
#     # Database skeleton (empty)
#     (base_dir / "Database" / "backups").mkdir(parents=True, exist_ok=True)
#     (base_dir / "Database" / "exports").mkdir(parents=True, exist_ok=True)
#     (base_dir / "Database" / "logs").mkdir(parents=True, exist_ok=True)
#     # Assets dir if we have any assets
#     if any(p.exists() for p in ASSETS):
#         (base_dir / "assets").mkdir(parents=True, exist_ok=True)
#         for p in ASSETS:
#             if p.exists():
#                 shutil.copy2(p, base_dir / "assets" / p.name)
#     # Drop a small README
#     readme_path = os.path.join(os.getcwd(), 'README.txt')
#     if readme_path:
#         shutil.copy(readme_path, base_dir / "README.txt")

def build_binary(onefile: bool, console: bool):
    global ENTRY_SCRIPT
    if ENTRY_SCRIPT is None:
        ENTRY_SCRIPT = pick_entry_script()
    if not ENTRY_SCRIPT or not ENTRY_SCRIPT.exists():
        raise SystemExit(f"[error] Entry script not found: {ENTRY_SCRIPT}")

    global ICON_PATH
    if ICON_PATH is None:
        ICON_PATH = pick_icon_file()

    pyinstaller_cmd = [sys.executable, "-m", "PyInstaller"]
    common = [
        str(ENTRY_SCRIPT),
        "--name", APP_NAME,
        "--noconfirm",
        "--clean"
    ]
    if not console:
        common.append("--windowed")
    common.append("--onefile" if onefile else "--onedir")

    # DO NOT include Database; only optional assets
    common += discover_asset_datas()

    # Add icon if exists and appropriate for platform
    system = platform.system().lower()
    if ICON_PATH and ICON_PATH.exists():
        if system == "windows" and ICON_PATH.suffix.lower() == ".ico":
            common += ["--icon", str(ICON_PATH)]
        elif system == "darwin" and ICON_PATH.suffix.lower() == ".icns":
            common += ["--icon", str(ICON_PATH)]

    print("[info] PyInstaller command:", " ".join(common))
    proc = subprocess.run(pyinstaller_cmd + common, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        print("\n[error] PyInstaller failed with the following output (last 200 lines shown):\n")
        lines = proc.stdout.splitlines()
        tail = "\n".join(lines[-200:])
        print(tail)
        raise SystemExit(f"PyInstaller exited with code {proc.returncode}. See output above.")

def locate_built_artifact(onefile: bool, console: bool) -> Path:
    dist = PROJECT_ROOT / "dist"
    system = platform.system().lower()

    if onefile:
        # Onefile: single executable on all OSes
        if system == "windows":
            candidates = [dist / f"{APP_NAME}.exe"]
        else:
            candidates = [dist / APP_NAME]
    else:
        if system == "darwin":
            # Onedir on macOS:
            # - windowed ⇒ .app bundle
            # - console  ⇒ plain directory
            candidates = [dist / f"{APP_NAME}.app", dist / APP_NAME]
        elif system == "windows":
            candidates = [dist / APP_NAME]  # onedir creates a folder
        else:
            candidates = [dist / APP_NAME]  # onedir creates a folder

    for c in candidates:
        if c.exists():
            return c

    # If nothing matched, return the first candidate so caller can error clearly
    return candidates[0]

def install_artifact(artifact: Path, install_base: Path):
    install_base.mkdir(parents=True, exist_ok=True)
    system = platform.system().lower()
    target = install_base / artifact.name

    # Warn if app allready exists.
    if target.exists() and not target.suffix:
        print(f"[warning] Application already exists at: {target}")
        return

    if artifact.is_dir():
        print(f"[info] Copying directory bundle to {target}")
        shutil.copytree(artifact, target)
    else:
        print(f"[info] Copying binary to {target}")
        shutil.copy2(artifact, target)

    # On Linux/macOS onefile, optionally create a launcher script for convenience
    if system in ("linux", "darwin") and artifact.is_file():
        launcher = install_base / ("run_" + APP_NAME.lower())
        launcher.write_text(f"#!/usr/bin/env bash\n\"$(dirname \"$0\")/{artifact.name}\"\n", encoding="utf-8")
        launcher.chmod(0o755)

    # Windows-only: ensure persistent project directories exist next to the app
    if system == "windows":
        project_dirs = [
            install_base / "Database",
            install_base / "Database" / "backups",
            install_base / "Database" / "exports",
            install_base / "Database" / "logs",
        ]
        for d in project_dirs:
            d.mkdir(parents=True, exist_ok=True)
        print(f"[info] Ensured Windows project layout in {install_base}")   

# ---------- venv / requirements helpers ----------
def venv_bin_dir(venv_path: Path) -> Path:
    return venv_path / ("Scripts" if os.name == "nt" else "bin")

def venv_python(venv_path: Path) -> Path:
    return venv_bin_dir(venv_path) / ("python.exe" if os.name == "nt" else "python")

def create_venv(venv_path: Path):
    print(f"[setup] Creating virtual environment at: {venv_path}")
    venv.EnvBuilder(with_pip=True, clear=False, upgrade=True, symlinks=os.name != "nt").create(str(venv_path))
    if not venv_python(venv_path).exists():
        print("[setup] Failed to create virtual environment (python not found in venv).", file=sys.stderr)
        sys.exit(2)

def ensure_requirements(project_dir: Path) -> Path:
    req = project_dir / "requirements.txt"
    if not req.exists():
        req.write_text(
            "PySide6==6.9.1\n"
            "pyinstaller==6.15.0\n",
            encoding="utf-8"
        )
        print(f"[setup] Created default requirements.txt at {req}")
    else:
        print(f"[setup] Found existing requirements.txt at {req}")
    return req

def pip_install(venv_py: Path, requirements_file: Path):
    print("[setup] Upgrading pip...")
    subprocess.check_call([str(venv_py), "-m", "pip", "install", "--upgrade", "pip", "--no-cache-dir"])
    print(f"[setup] Installing requirements from {requirements_file} ...")
    subprocess.check_call([
        str(venv_py), "-m", "pip", "install", "--no-cache-dir", "-r", str(requirements_file)
    ])
    print("[setup] Dependencies installed successfully.")

def _pick_build_options_by_os() -> tuple[bool, bool]:
    """
    Returns (onefile, console) based on OS:
      - Windows: onefile, no console (GUI)
      - macOS:   onedir,  console shown
      - Linux:   onefile, no console (sane default)
    """
    sysname = platform.system().lower()
    if sysname == "windows":
        return True, False
    if sysname == "darwin":
        return False, False
    # Linux / other
    return True, False

def main():
    # Ensure .venv exists first, then re-exec into it if needed
    venv_path = PROJECT_ROOT / ".venv"
    if not venv_path.exists():
        create_venv(venv_path)
    reexec_in_dotvenv_if_found()

    # Inside .venv now (or already was). Ensure pip + requirements installed.
    try:
        req_file = ensure_requirements(PROJECT_ROOT)
        vpy = venv_python(venv_path)
        pip_install(vpy, req_file)
    except Exception as e:
        print(f"[warn] Skipping requirements install step: {e}")

    ensure_pyinstaller()

    # 1)
    _onefile, _console = _pick_build_options_by_os()
    build_binary(onefile=_onefile, console=_console)

    # Locate:
    artifact = locate_built_artifact(onefile=_onefile, console=_console)
    if not artifact.exists():
        # Optional: dump dist contents to help debugging
        try:
            print("[debug] dist contents:", [p.name for p in (PROJECT_ROOT / "dist").iterdir()])
        except Exception:
            pass
        raise SystemExit("[error] Build succeeded but artifact not found; check PyInstaller output.")

    # 2) Pick install location (user-writable)
    default_dir = safe_default_install_dir()
    install_root = pick_install_dir(default_dir)
    print(f"[info] Install path: {install_root}")

    # 3) Copy the packaged app into the chosen location
    install_artifact(artifact, install_root)



    print("\n[ok] Installation complete.")
    print(f"- Location: {install_root}")
    if platform.system().lower() == "darwin":
        if artifact.suffix == ".app":
            print(f"- Launch: open \"{install_root / artifact.name}\"")
        else:
            print(f"- Launch: \"{install_root / ('run_' + APP_NAME.lower())}\"")
    elif platform.system().lower() == "windows":
        print(f"- Launch: {install_root / (APP_NAME + '.exe')}")
    else:
        print(f"- Launch: {install_root / ('run_' + APP_NAME.lower())}")

if __name__ == "__main__":
    main()
