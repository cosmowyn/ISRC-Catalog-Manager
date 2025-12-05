# ISRC Manager  
Created by **M. van de Kleut**  
22-aug-2025

---

# IMPORTANT LEGAL NOTICE

To legally generate and assign industry-standard registration codes, you must first acquire the correct registrant prefixes and identifiers from the relevant authorities. These codes are part of international systems for music identification and royalty collection.

Using self-invented or fake codes is strictly prohibited.  
Such codes are invalid and may cause:  
- Rejection by digital distributors  
- Loss of royalty payments  
- Legal and contractual violations  
- Damage to your reputation as an artist or label  

Always ensure your codes are officially registered before use.

---

# Worldwide Standards Overview

## 1. ISRC (International Standard Recording Code)
- Identifies individual sound recordings and music videos.  
- Format: CC-XXX-YY-NNNNN  
- Apply for an ISRC registrant prefix via your national ISRC agency.  
- In countries without a national agency, apply via IFPI:  
  https://isrc.ifpi.org

## 2. UPC / EAN
- Identifies complete releases as products.  
- Required by distributors.  
- Issued by GS1.

## 3. ISWC (International Standard Musical Work Code)
- Identifies compositions (songs).  
- Assigned automatically by your local PRO when registering works.

## 4. IPI/CAE
- Identifies songwriters, composers, and publishers.  
- Assigned when joining your local PRO.

---

# Netherlands-Specific Responsibilities

- ISRC: SENA — https://www.sena.nl  
- UPC/EAN: GS1 Nederland — https://www.gs1.nl  
- ISWC: BUMA/STEMRA — https://www.bumastemra.nl  
- IPI/CAE: Assigned by BUMA/STEMRA  

---

# ISRC Manager: Overview

ISRC Manager is a desktop application for managing ISRCs, metadata, and release information.  
It is designed for independent artists, producers, and small labels who require professional-grade catalog management without complex enterprise tools.

The application provides:
- Automatic ISRC generation in ISO 3901 format  
- Metadata management with customizable fields  
- Audio and image preview capabilities  
- Multiple profile support  
- Full audit logging and backup system  
- Import/export tools for XML metadata  
- A built-in license management system  
- A cross-platform icon factory for building distributable applications  

---

# Features

## ISRC Code Generation
- Fully compliant with ISO 3901.  
- Supports up to 99 independent profiles (artist/label/sublabel).  
- Tracks last-used designation codes per profile.  
- Automatically assigns ISRC year based on creation date.  
- Allows reuse of the original ISRC year when importing older releases.

## Metadata Management
- Supports standard and custom metadata fields.  
- Built-in support for text, date, checkbox, dropdown, image blob, and audio blob fields.  
- Audio and image data may be stored directly in the database (up to 256 MB per file).

## Database & Profile Handling
- Independent ISRC sequences per profile.  
- Each profile can store unique settings and field layouts.  
- SQLite backend for stability and portability.

## Media Previews
- Built-in audio preview window with waveform (macOS fully supported; Windows waveform display is a known limitation).  
- Image preview window for artwork and promotional assets.  
- Spacebar quick preview shortcut.

## Auditing, Backups, and Logging
- Automatic timestamped backups in `/Database/backups/`.  
- Full action logs stored in `/Database/logs/`.  
- Pre-restore backup creation before applying imported data.

## Import/Export
- Export metadata to XML for distribution or archival.  
- Import XML catalogs with an optional dry-run validation mode.  
- Detailed import result report with pass/fail breakdown.  
- If the XML includes unknown custom fields, the import will stop and log the missing field definitions.

---

# License Management System

The License Manager allows you to:
- Store multiple license records linked to track titles  
- Associate licenses with profiles
- Manage Licensee parties
- See how many licenses are linked to a licensee

---

# Icon Factory (Cross-Platform)

A complete icon creation tool is integrated into the build workflow.  
It supports:

- macOS: `.icns`  
- Windows: `.ico`  
- Linux: `.png` (512×512)

Features:
- GUI file picker using Tkinter  
- Automatic square cropping  
- Optional centre-crop if the selected image is not 1:1  
- Upscaling to meet platform-specific resolutions  
- Multi-size ICO generation for Windows  
- Automatic output directory grouping by OS  

This allows users to generate branded application icons during the build process without external tools.

---

# Build Script (build.py)

The build script is designed to work safely on clean systems with no preinstalled dependencies.  
It automatically handles:

- Virtual environment creation  
- Requirements installation  
- PyInstaller setup  
- Optional icon generation  
- Application packaging  
- Installation to a user-writable directory  

## New Startup Workflow

When launching the script, the user is presented with two options:

### 1. Create Environment Only
- Creates `.venv` inside the project  
- Installs all required dependencies  
- Skips PyInstaller build  
- Skips icon generation  
- Exits cleanly after environment setup  
- Safe for users who want to prepare a development environment without building the app

### 2. Full Build (Build Application Binary)
- Performs everything in option 1  
- Prompts for an icon (or uses the icon factory)  
- Builds a distributable application using PyInstaller  
- Prompts the user for an installation directory  
- Copies the built app to the selected target  
- Recreates the Windows project structure if applicable  

Both flows use Tkinter dialogs when available and automatically fall back to console prompts if GUI elements are unavailable.

---

# Installation

## Prerequisites
- macOS, Windows, or Linux  
- Python 3.9+  

## Running the Installer

Navigate to the project folder and run:

```
python build.py
```

You will be prompted to choose:

- Create environment only  
- Or build the full distributable application  

After a successful build, the installer will ask for a destination folder and install the packaged app there.

The install process will never overwrite your existing Database folder.

---

# Usage

## Starting the Application
You may start the app by either:
- launching the built executable  
- or running `python ISRC_manager.py` directly in the project environment  

Upon first launch you will:
- choose a project directory  
- allow the database to initialize automatically  

## Profiles
Each profile maintains:
- its own ISRC sequences  
- custom metadata layout  
- license associations  
- appearance settings  

Switch between profiles at any time.

## Adding Records
- Add a track to automatically receive an ISRC  
- Modify metadata fields as needed  
- Attach audio or artwork directly to the record if desired  

## Custom Fields
Available field types:
- Text  
- Checkbox  
- Date  
- Dropdown  
- Blob_image  
- Blob_audio  

Custom fields appear as new columns in the table view and are stored in the database.

## Backups
Backups are created automatically and stored under:
- `/Database/backups/`  
Logs are stored in:
- `/Database/logs/`  

## Import/Export
- Export to XML in SENA-compatible format  
- Import XML with optional dry-run  
- Import will validate field structure and warn about mismatches  

---

# Keyboard Shortcuts

Audio Preview:
- Space: Play / Pause  
- Escape: Close  
- Left Arrow: Scrub backwards  
- Right Arrow: Scrub forwards  

---

# Support
- Bug reports may be submitted via GitHub Issues.  
- Pull requests are welcome.  
- This project is primarily intended for personal and independent use.

---

# License
Provided "as is" without warranty. Free to use, copy, and distribute for any purpose, provided that original credits are retained. Not for resale.