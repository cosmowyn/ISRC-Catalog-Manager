#!/usr/bin/env python3
"""
Build and install ISRCManager (PySide6) without bundling a database.

- Detects and re-execs into ./.venv if present.
- Ensures required dependencies are installed into that environment.
- Can either:
    * Only create/refresh the virtual environment + dependencies, or
    * Also build and install the packaged application via PyInstaller.
- Prompts the user on launch which mode to use (GUI dialog if possible,
  falling back to a console prompt).
- Prompts the user for an install directory (GUI); defaults to a safe user path.
- Creates a project layout there and copies the packaged app.
- Does NOT package or copy any existing Database files.

Typical usage:
  python build_and_install.py
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

# Pillow is loaded lazily so this script can run on a clean machine.
Image = None  # type: ignore[assignment]


def ensure_pillow_loaded():
    """
    Lazy-load Pillow's Image module.

    Returns:
        Image module object if available, otherwise None.
    """
    global Image
    if Image is not None:
        return Image
    try:
        from PIL import Image as _Image  # type: ignore[import]
        Image = _Image
    except ImportError:
        Image = None
    return Image


# Icon-factory constants (used when creating icons via GUI)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".bmp", ".webp"}
MIN_MACOS_ICON_SIZE = 1024  # Recommended base size for macOS .icns

# ---- Project constants ----
PROJECT_ROOT = Path(__file__).resolve().parent
# ENTRY_SCRIPT is initially None; will be set by pick_entry_script if needed
ENTRY_SCRIPT: Path | None = None
APP_NAME = "ISRCManager"
ICON_PATH: Path | None = None

# ---- Shared Tk root (single instance for all dialogs) ----
_tk_root = None


def get_tk_root():
    """
    Create (once) and return a shared Tk root, centered on screen.

    We keep this root alive for the lifetime of the build script to avoid
    macOS/Tk AppleEvent crashes and to prevent the window from "disappearing".
    """
    global _tk_root
    if _tk_root is not None:
        return _tk_root

    import tkinter as tk

    root = tk.Tk()
    root.title("ISRCManager build")

    # Small, centered window
    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    win_w, win_h = 400, 300
    x = (screen_w // 2) - (win_w // 2)
    y = (screen_h // 2) - (win_h // 2)
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")

    # Keep it visible, bring to front once
    root.deiconify()
    root.lift()
    try:
        root.attributes("-topmost", True)
        root.after(500, lambda: root.attributes("-topmost", False))
    except Exception:
        # attributes may fail on some platforms; ignore
        pass

    _tk_root = root
    return _tk_root


def destroy_tk_root():
    """Destroy the shared Tk root (if created)."""
    global _tk_root
    if _tk_root is not None:
        try:
            _tk_root.destroy()
        except Exception:
            pass
        _tk_root = None


def pick_entry_script() -> Path:
    """
    Open a file picker dialog to let the user choose a Python entry script (*.py).
    Returns the selected Path, or raises SystemExit if canceled.
    """
    try:
        from tkinter import filedialog, messagebox

        root = get_tk_root()
        root.update()

        messagebox.showinfo(
            title="ISRCManager Installer",
            message="Select the Python entry script for your application (.py).",
            parent=root,
        )
        script_path = filedialog.askopenfilename(
            title="Select entry script",
            filetypes=[("Python scripts", "*.py")],
            initialdir=str(PROJECT_ROOT),
            parent=root,
        )
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

# ---- Icon factory helpers (GUI-based) ----


def _factory_select_image_file(root) -> Path | None:
    """Open a file dialog to select an image, validate extension, and return the path."""
    if ensure_pillow_loaded() is None:
        return None

    from tkinter import filedialog, messagebox

    filetypes = [
        ("Image files", "*.jpg *.jpeg *.png *.gif *.tif *.tiff *.bmp *.webp"),
        ("All files", "*.*"),
    ]

    while True:
        path_str = filedialog.askopenfilename(
            title="Select source image",
            filetypes=filetypes,
            parent=root,
        )
        if not path_str:
            if messagebox.askyesno(
                "No file selected",
                "No image was selected.\n\nDo you want to cancel icon creation?",
                parent=root,
            ):
                return None
            else:
                continue

        path = Path(path_str)
        if path.suffix.lower() in ALLOWED_EXTENSIONS:
            return path
        else:
            messagebox.showerror(
                "Unsupported file type",
                f"Selected file has unsupported extension: {path.suffix}",
                parent=root,
            )
            # loop again


def _factory_crop_to_center_square(img) -> "Image.Image":
    """Crop image to centered 1:1 square."""
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    right = left + side
    bottom = top + side
    return img.crop((left, top, right, bottom))


def _factory_get_square_image(root) -> "Image.Image | None":
    """
    Select an image and ensure it's square.
    If not square, let user choose to crop center or pick another image.
    Also validate that the final square image is large enough for macOS
    (MIN_MACOS_ICON_SIZE x MIN_MACOS_ICON_SIZE); if not, warn user and
    let them reselect or accept upscaling.
    Returns an RGBA square image, or None if user cancels.
    """
    if ensure_pillow_loaded() is None:
        return None

    from tkinter import messagebox

    while True:
        img_path = _factory_select_image_file(root)
        if img_path is None:
            return None

        img = Image.open(img_path)

        if img.mode != "RGBA":
            img = img.convert("RGBA")

        w, h = img.size

        if w != h:
            resp = messagebox.askyesno(
                "Image is not square",
                (
                    f"Selected image size: {w}x{h} (ratio is not 1:1).\n\n"
                    "Yes: Auto-crop to centered square.\n"
                    "No: Select a different image."
                ),
                parent=root,
            )
            if resp:
                img = _factory_crop_to_center_square(img)
                sw, sh = img.size
                messagebox.showinfo(
                    "Image cropped",
                    f"Image cropped to centered square: {sw}x{sh}",
                    parent=root,
                )
            else:
                continue
        else:
            messagebox.showinfo(
                "Image is square",
                f"Selected image is already square: {w}x{h}",
                parent=root,
            )

        side = img.size[0]

        if side < MIN_MACOS_ICON_SIZE:
            resp = messagebox.askyesno(
                "Low resolution for macOS",
                (
                    f"Current square image is {side}x{side}.\n\n"
                    f"For optimal macOS icon compatibility, a minimum of "
                    f"{MIN_MACOS_ICON_SIZE}x{MIN_MACOS_ICON_SIZE} is recommended.\n\n"
                    "Yes: Use this image anyway (it will be upscaled if needed).\n"
                    "No: Select a different (larger) image."
                ),
                parent=root,
            )
            if not resp:
                continue

        return img


def _factory_ask_base_name(root) -> str | None:
    """Ask for a base file name (without extension) via a custom centered dialog."""
    from tkinter import Toplevel, Label, Entry, Button, StringVar, messagebox
    import tkinter as tk

    result: dict[str, str | None] = {"value": None}

    dialog = Toplevel(root)
    dialog.title("Icon file name")
    dialog.transient(root)
    dialog.grab_set()

    Label(
        dialog,
        text="Enter base file name for the icon (without extension):",
        anchor="w",
        justify="left",
    ).pack(padx=10, pady=(10, 5), fill="x")

    name_var = StringVar()
    entry = Entry(dialog, textvariable=name_var)
    entry.pack(padx=10, pady=(0, 10), fill="x")
    entry.focus_set()

    def on_ok() -> None:
        name = name_var.get().strip()
        if not name:
            messagebox.showerror(
                "Invalid name",
                "Name cannot be empty.",
                parent=dialog,
            )
            return
        result["value"] = name.replace(" ", "_")
        dialog.destroy()

    def on_cancel() -> None:
        if messagebox.askyesno(
            "Cancel",
            "No file name entered.\n\nDo you want to cancel icon creation?",
            parent=dialog,
        ):
            result["value"] = None
            dialog.destroy()

    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=(0, 10))

    ok_btn = Button(btn_frame, text="OK", width=10, command=on_ok)
    ok_btn.pack(side="left", padx=5)

    cancel_btn = Button(btn_frame, text="Cancel", width=10, command=on_cancel)
    cancel_btn.pack(side="left", padx=5)

    dialog.protocol("WM_DELETE_WINDOW", on_cancel)

    # Center dialog on screen (not relative to possibly-hidden root)
    dialog.update_idletasks()
    screen_w = dialog.winfo_screenwidth()
    screen_h = dialog.winfo_screenheight()
    win_w = dialog.winfo_width()
    win_h = dialog.winfo_height()
    x = (screen_w // 2) - (win_w // 2)
    y = (screen_h // 2) - (win_h // 2)
    dialog.geometry(f"+{x}+{y}")

    root.wait_window(dialog)
    return result["value"]


def _factory_output_dir(os_name: str) -> Path:
    """
    Ensure output/<OS_NAME> exists under PROJECT_ROOT,
    and return that directory.
    """
    out_dir = PROJECT_ROOT / "output" / os_name
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _factory_generate_windows_icon(img, out_path: Path) -> None:
    """Generate a multi-size .ico for Windows."""
    ensure_pillow_loaded()
    min_side = min(img.size)
    if min_side < 256:
        img = img.resize((256, 256), Image.LANCZOS)

    icon_sizes = [
        (16, 16),
        (24, 24),
        (32, 32),
        (48, 48),
        (64, 64),
        (128, 128),
        (256, 256),
    ]
    img.save(out_path, format="ICO", sizes=icon_sizes)


def _factory_generate_macos_icon(img, out_path: Path) -> None:
    """Generate a .icns for macOS."""
    ensure_pillow_loaded()
    if img.size[0] < MIN_MACOS_ICON_SIZE:
        img = img.resize((MIN_MACOS_ICON_SIZE, MIN_MACOS_ICON_SIZE), Image.LANCZOS)
    img.save(out_path, format="ICNS")


def _factory_generate_linux_icon(img, out_path: Path) -> None:
    """Generate a PNG icon for Linux (512x512)."""
    ensure_pillow_loaded()
    target_size = 512
    if img.size[0] != target_size:
        img = img.resize((target_size, target_size), Image.LANCZOS)
    img.save(out_path, format="PNG")


def _factory_create_icon_for_current_os(root) -> Path | None:
    """
    Create an icon for the current OS using GUI prompts.
    Skips OS-choice dialog: uses platform.system() to choose target type.
    Returns the path to the generated icon file, or None if cancelled.
    """
    from tkinter import messagebox

    if ensure_pillow_loaded() is None:
        messagebox.showerror(
            "Pillow not available",
            "Pillow (PIL) is not installed in this environment.\n"
            "Icon creation is not possible.",
            parent=root,
        )
        return None

    system = platform.system().lower()

    if system == "darwin":
        os_name = "macOS"
        prefix = "mac_"
        ext = ".icns"
        generator = _factory_generate_macos_icon
    elif system == "windows":
        os_name = "Windows"
        prefix = "win_"
        ext = ".ico"
        generator = _factory_generate_windows_icon
    else:
        os_name = "Linux"
        prefix = "linux_"
        ext = ".png"
        generator = _factory_generate_linux_icon

    img = _factory_get_square_image(root)
    if img is None:
        return None

    base_name = _factory_ask_base_name(root)
    if base_name is None:
        return None

    out_dir = _factory_output_dir(os_name)
    out_path = out_dir / f"{prefix}{base_name}{ext}"

    generator(img, out_path)

    messagebox.showinfo(
        "Icon created",
        f"Icon generated for {os_name}:\n\n{out_path}",
        parent=root,
    )
    return out_path


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
        from tkinter import filedialog, messagebox

        root = get_tk_root()
        root.update()

        messagebox.showinfo(
            title="ISRCManager Installer",
            message="Select an installation folder (user-writable, no admin privileges required).",
            parent=root,
        )
        # Ensure default exists so dialog can open there
        default_dir.parent.mkdir(parents=True, exist_ok=True)
        chosen = filedialog.askdirectory(
            initialdir=str(default_dir.parent),
            title="Choose installation folder",
            mustexist=False,
            parent=root,
        )
        if chosen:
            return Path(chosen)
    except Exception as e:
        print(f"[warn] GUI picker unavailable ({e}); using default path.")
    return default_dir


def pick_icon_file() -> Path | None:
    """
    GUI helper:
    - Ask if the user already has an icon file or wants to create one.
    - If they have one: let them pick an existing .ico/.icns (depending on OS).
    - If they want to create one: run the integrated icon factory for current OS.
    """
    try:
        from tkinter import filedialog, messagebox

        system = platform.system().lower()
        if system not in ("darwin", "windows"):
            # For other systems, keep previous behavior: no icon selection
            return None

        root = get_tk_root()
        root.update()

        resp = messagebox.askyesno(
            "Application Icon",
            (
                "Do you already have an application icon file?\n\n"
                "Yes: Select an existing icon file for this build.\n"
                "No: Create a new icon now using the icon factory."
            ),
            parent=root,
        )

        icon_path: Path | None = None

        if resp:
            # Existing icon route
            if system == "darwin":
                filetypes = [("ICNS files", "*.icns")]
                title = "Select an icon file (.icns)"
            else:  # windows
                filetypes = [("ICO files", "*.ico")]
                title = "Select an icon file (.ico)"

            path_str = filedialog.askopenfilename(
                title=title,
                filetypes=filetypes,
                parent=root,
            )
            if path_str:
                icon_path = Path(path_str)
        else:
            # Use the GUI icon factory and skip OS-choice (current OS only)
            icon_path = _factory_create_icon_for_current_os(root)

        return icon_path
    except Exception as e:
        print(f"[warn] Icon picker unavailable ({e}); skipping icon selection.")
    return None


def pick_readme_file() -> Path | None:
    try:
        from tkinter import filedialog

        root = get_tk_root()
        root.update()

        filetypes = [("Text files", "*.txt"), ("All files", "*.*")]
        title = "Select a README file (.txt)"
        readme_path = filedialog.askopenfilename(title=title, filetypes=filetypes, parent=root)
        if readme_path:
            return Path(readme_path)
    except Exception as e:
        print(f"[warn] README picker unavailable ({e}); skipping README selection.")
    return None


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
        "--name",
        APP_NAME,
        "--noconfirm",
        "--clean",
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

    # Warn if app already exists.
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
        launcher.write_text(
            f"#!/usr/bin/env bash\n\"$(dirname \"$0\")/{artifact.name}\"\n", encoding="utf-8"
        )
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
            "pyinstaller==6.15.0\n"
            "pillow==12.0.0\n",
            encoding="utf-8",
        )
        print(f"[setup] Created default requirements.txt at {req}")
    else:
        print(f"[setup] Found existing requirements.txt at {req}")
    return req


def pip_install(venv_py: Path, requirements_file: Path):
    print("[setup] Upgrading pip...")
    subprocess.check_call(
        [str(venv_py), "-m", "pip", "install", "--upgrade", "pip", "--no-cache-dir"]
    )
    print(f"[setup] Installing requirements from {requirements_file} ...")
    subprocess.check_call(
        [str(venv_py), "-m", "pip", "install", "--no-cache-dir", "-r", str(requirements_file)]
    )
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


def ask_build_mode() -> str:
    """
    Ask the user whether to:
      - only prepare the environment ("env_only"), or
      - prepare env + build & install app ("build").

    Prefers a Tkinter dialog if available, falls back to console input.

    Returns:
        "env_only" or "build". Exits the script on user cancellation.
    """
    # First try a GUI dialog
    try:
        from tkinter import messagebox

        root = get_tk_root()
        root.update()

        msg = (
            "This script can perform two types of setup:\n\n"
            "  • Prepare a Python virtual environment and install all required\n"
            "    Python packages (no build).\n"
            "  • Prepare the environment and also build & install the\n"
            "    ISRCManager application using PyInstaller.\n\n"
            "Do you want to build and install the application now?\n\n"
            "Yes  → Create environment AND build/install the app.\n"
            "No   → Only create/refresh the environment (no build).\n"
        )

        res = messagebox.askyesno(
            "ISRCManager setup",
            msg,
            parent=root,
        )
        if res:
            print("[mode] Environment + build/install selected.")
            return "build"
        else:
            print("[mode] Environment-only setup selected.")
            return "env_only"
    except Exception as e:
        print(f"[warn] GUI mode selection unavailable ({e}); falling back to console prompt.")

    # Console fallback
    while True:
        print(
            "\nISRCManager setup options:\n"
            "  [b]  Create virtual environment, install dependencies,\n"
            "       and build/install the ISRCManager application.\n"
            "  [e]  Only create/refresh the virtual environment and\n"
            "       install dependencies (no build, no installer).\n"
            "  [q]  Quit without making changes.\n"
        )
        choice = input("Choose mode [b/e/q]: ").strip().lower()
        if choice in ("b", "build"):
            print("[mode] Environment + build/install selected.")
            return "build"
        if choice in ("e", "env", "env_only"):
            print("[mode] Environment-only setup selected.")
            return "env_only"
        if choice in ("q", "quit", "exit"):
            print("[info] User aborted setup.")
            sys.exit(0)
        print("Invalid choice, please enter 'b', 'e' or 'q'.")


def main():
    # Ensure .venv exists first, then re-exec into it if needed
    venv_path = PROJECT_ROOT / ".venv"
    if not venv_path.exists():
        create_venv(venv_path)
    reexec_in_dotvenv_if_found()

    # Decide what to do: env-only or env + build
    mode = ask_build_mode()

    # Inside .venv now (or already was). Ensure pip + requirements installed.
    try:
        req_file = ensure_requirements(PROJECT_ROOT)
        vpy = venv_python(venv_path)
        pip_install(vpy, req_file)
    except Exception as e:
        print(f"[warn] Skipping requirements install step: {e}")

    # If the user only wanted the environment, stop here
    if mode == "env_only":
        print("\n[ok] Environment setup complete. No build or installation was performed.")
        destroy_tk_root()
        return

    # Otherwise, continue with the build/install as before
    ensure_pyinstaller()

    # 1) Build binary
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

    # Cleanly tear down Tk root at the very end
    destroy_tk_root()


if __name__ == "__main__":
    main()