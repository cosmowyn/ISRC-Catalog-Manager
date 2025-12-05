#!/usr/bin/env python3
"""
Icon generator for Python applications.

- Lets user pick an image file via GUI dialog (tkinter)
- Validates extension (jpg, jpeg, png, gif, tif, tiff, bmp, webp)
- Ensures 1:1 aspect ratio (option to re-select or auto-crop centered)
- Validates resolution for macOS (warn & allow reselect or accept)
- Asks which OS(es) to target (Windows, macOS, Linux) via GUI
- Asks for base output name via GUI
- Saves icons into:
    <app_root>/output/<OS_NAME>/<prefix><basename>.<ext>
"""

import sys
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog
except ImportError:
    print("tkinter is required for the GUI dialogs.")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("Pillow is required. Install with: pip install pillow")
    sys.exit(1)


ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".bmp", ".webp"}

MIN_MACOS_ICON_SIZE = 1024  # recommended base size for macOS .icns

OS_OPTIONS = {
    "1": {"name": "Windows", "prefix": "win_", "ext": ".ico"},
    "2": {"name": "macOS",   "prefix": "mac_", "ext": ".icns"},
    "3": {"name": "Linux",   "prefix": "linux_", "ext": ".png"},
}


def get_app_root() -> Path:
    """Return the root directory of the app (script folder, or CWD as fallback)."""
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path.cwd()


def select_image_file(root: tk.Tk) -> Path:
    """Open a file dialog to select an image, validate extension, and return the path."""
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
            # User cancelled: ask if they really want to quit
            if messagebox.askyesno(
                "No file selected",
                "No image was selected.\n\nDo you want to quit?",
                parent=root,
            ):
                sys.exit(0)
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
            # Loop again for another selection


def crop_to_center_square(
    img: Image.Image,
    add_margin: bool = False,
    margin_px: int = 20
) -> Image.Image:
    """
    Crop image to centered 1:1 square.

    If add_margin is True, the cropped square is placed into a slightly
    larger transparent canvas, adding 'margin_px' pixels on all sides.
    """
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    right = left + side
    bottom = top + side

    cropped = img.crop((left, top, right, bottom))

    if add_margin and margin_px > 0:
        # Create transparent canvas slightly larger than cropped image
        new_side = side + 2 * margin_px
        canvas = Image.new("RGBA", (new_side, new_side), (0, 0, 0, 0))
        canvas.paste(cropped, (margin_px, margin_px))
        return canvas

    return cropped


def get_square_image(root: tk.Tk) -> Image.Image:
    """
    Select an image and ensure it's square.
    If not square, let user choose to crop center or pick another image.
    Also validate that the final square image is large enough for macOS
    (MIN_MACOS_ICON_SIZE x MIN_MACOS_ICON_SIZE); if not, warn user and
    let them reselect or accept upscaling.
    Returns an RGBA square image.
    """
    while True:
        img_path = select_image_file(root)
        img = Image.open(img_path)

        # Always work in RGBA to have alpha available for icons
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        w, h = img.size

        # === Aspect-ratio check & handling ===
        if w != h:
            resp = messagebox.askyesno(
                "Image is not square",
                (
                    f"Selected image size: {w}x{h} (ratio is not 1:1).\n\n"
                    "Yes: Auto-crop to centered square (with safe margin).\n"
                    "No: Select a different image."
                ),
                parent=root,
            )
            if resp:
                # Add a small safe margin so content isn't flush against edges
                img = crop_to_center_square(img, add_margin=True, margin_px=20)
                sw, sh = img.size
                messagebox.showinfo(
                    "Image cropped",
                    f"Image cropped to centered square with margin: {sw}x{sh}",
                    parent=root,
                )
            else:
                # Go back to file selection
                continue
        else:
            messagebox.showinfo(
                "Image is square",
                f"Selected image is already square: {w}x{h}",
                parent=root,
            )

        # At this point, img is square (possibly with margin)
        side = img.size[0]

        # === Resolution validation for macOS compatibility ===
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
                # User wants to pick a different image
                continue

        # Either large enough already, or user accepted a smaller one
        return img


def ask_target_os(root: tk.Tk) -> list[dict]:
    """Ask user which OS(es) to target via a GUI dialog, return list of OS option dicts."""

    dialog = tk.Toplevel(root)
    dialog.title("Select target operating systems")
    dialog.transient(root)
    dialog.grab_set()

    tk.Label(
        dialog,
        text="Select target OS(es) for the icon:",
        anchor="w",
        justify="left",
    ).pack(padx=10, pady=(10, 5), fill="x")

    vars_map: dict[str, tk.BooleanVar] = {}
    for key, opt in OS_OPTIONS.items():
        var = tk.BooleanVar(value=False)
        cb = tk.Checkbutton(dialog, text=opt["name"], variable=var)
        cb.pack(anchor="w", padx=20)
        vars_map[key] = var

    selection: list[str] = []

    def on_ok() -> None:
        sel = [k for k, v in vars_map.items() if v.get()]
        if not sel:
            messagebox.showerror(
                "No selection",
                "Please select at least one target OS.",
                parent=dialog,
            )
            return
        selection.extend(sel)
        dialog.destroy()

    def on_cancel() -> None:
        # no selection, dialog closed
        dialog.destroy()

    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=10)

    ok_btn = tk.Button(btn_frame, text="OK", width=10, command=on_ok)
    ok_btn.pack(side="left", padx=5)

    cancel_btn = tk.Button(btn_frame, text="Cancel", width=10, command=on_cancel)
    cancel_btn.pack(side="left", padx=5)

    dialog.protocol("WM_DELETE_WINDOW", on_cancel)

    # Center dialog roughly over root
    dialog.update_idletasks()
    x = root.winfo_x() + (root.winfo_width() // 2) - (dialog.winfo_width() // 2)
    y = root.winfo_y() + (root.winfo_height() // 2) - (dialog.winfo_height() // 2)
    dialog.geometry(f"+{x}+{y}")

    root.wait_window(dialog)

    if not selection:
        # User cancelled
        if messagebox.askyesno(
            "No OS selected",
            "No target OS was selected.\n\nDo you want to quit?",
            parent=root,
        ):
            sys.exit(0)
        else:
            # Try again
            return ask_target_os(root)

    return [OS_OPTIONS[k] for k in sorted(selection)]


def ask_base_name(root: tk.Tk) -> str:
    """Ask for a base file name (without extension) via GUI dialog."""
    while True:
        name = simpledialog.askstring(
            "Icon file name",
            "Enter base file name (without extension):",
            parent=root,
        )
        if name is None:
            # User cancelled, confirm exit
            if messagebox.askyesno(
                "Cancel",
                "No file name entered.\n\nDo you want to quit?",
                parent=root,
            ):
                sys.exit(0)
            else:
                continue

        name = name.strip()
        if not name:
            messagebox.showerror(
                "Invalid name",
                "Name cannot be empty.",
                parent=root,
            )
            continue

        # Replace spaces with underscores to keep file names 'safe-ish'
        name = name.replace(" ", "_")
        return name


def ensure_output_dir(app_root: Path, os_name: str) -> Path:
    """
    Ensure output/<OS_NAME> exists under app_root,
    and return that directory.
    """
    out_dir = app_root / "output" / os_name
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def generate_windows_icon(img: Image.Image, out_path: Path) -> None:
    """Generate a multi-size .ico for Windows."""
    # Ensure at least 256x256 for highest size
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


def generate_macos_icon(img: Image.Image, out_path: Path) -> None:
    """Generate a .icns for macOS."""
    # Use a large base, Pillow will create smaller sizes
    if img.size[0] < MIN_MACOS_ICON_SIZE:
        img = img.resize((MIN_MACOS_ICON_SIZE, MIN_MACOS_ICON_SIZE), Image.LANCZOS)

    img.save(out_path, format="ICNS")


def generate_linux_icon(img: Image.Image, out_path: Path) -> None:
    """Generate a PNG icon for Linux (512x512)."""
    target_size = 512
    if img.size[0] != target_size:
        img = img.resize((target_size, target_size), Image.LANCZOS)

    img.save(out_path, format="PNG")


def main() -> None:
    # Create the root Tk instance and make it visible / on top
    root = tk.Tk()
    root.title("Icon Factory")

    # Make the window small and unobtrusive
    root.geometry("300x100+200+200")

    # Bring it to the front (important on macOS)
    root.update_idletasks()
    root.lift()
    root.attributes("-topmost", True)
    root.after(200, lambda: root.attributes("-topmost", False))

    app_root = get_app_root()

    square_img = get_square_image(root)
    os_targets = ask_target_os(root)
    base_name = ask_base_name(root)

    created_files: list[str] = []

    for os_opt in os_targets:
        os_name = os_opt["name"]
        prefix = os_opt["prefix"]
        ext = os_opt["ext"]

        out_dir = ensure_output_dir(app_root, os_name)
        out_path = out_dir / f"{prefix}{base_name}{ext}"

        if os_name == "Windows":
            generate_windows_icon(square_img, out_path)
        elif os_name == "macOS":
            generate_macos_icon(square_img, out_path)
        elif os_name == "Linux":
            generate_linux_icon(square_img, out_path)

        created_files.append(str(out_path))

    messagebox.showinfo(
        "Done",
        "Icon(s) generated:\n\n" + "\n".join(created_files),
        parent=root,
    )

if __name__ == "__main__":
    main()