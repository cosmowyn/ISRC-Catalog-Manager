
# Created by M. van de Kleut
22-aug-2025

License:
This software is provided "as is", without warranty of any kind.
Free to use, copy, and distribute for any purpose, provided that
original credits are retained. Not for resale.

# ISRC Manager

## IMPORTANT LEGAL NOTICE
To legally generate and assign industry-standard registration codes, you must first acquire the correct registrant prefixes and identifiers from the relevant authorities. These codes are not arbitrary: they are part of international and national systems for music identification and royalty collection. 

Using self-invented or fake codes is strictly prohibited. Such codes are INVALID and may cause:
- Rejection by digital distributors (Spotify, Apple Music, etc.)
- Loss of royalty payments
- Legal and contractual violations
- Damage to your reputation as an artist or label

Always ensure your codes are officially registered before use.


### WORLDWIDE
1. ISRC (International Standard Recording Code)
- Purpose: Identifies individual sound recordings and music videos.
- Format: CC-XXX-YY-NNNNN (Country, Registrant Code, Year, Designation Code).
- How to get it:
  • Apply for an ISRC Registrant Code (your prefix) via your national ISRC agency, usually your local music rights organisation.
  • In countries without a local agency, you can apply directly through the IFPI (International Federation of the Phonographic Industry).
  • Official list of national agencies: https://isrc.ifpi.org

2. UPC / EAN (Universal Product Code / European Article Number)
- Purpose: Identifies albums or releases as whole products (not individual tracks).
- Required by digital distributors.
- How to get it:
  • Purchase UPC/EAN codes from GS1 (global organisation managing barcodes).
  • Some distributors can provide UPC/EAN codes if you do not have your own, but they then remain the legal owner of the code.

3. ISWC (International Standard Musical Work Code)
- Purpose: Identifies underlying musical compositions (songs, not recordings).
- How to get it:
  • ISWC codes are issued automatically when you register a work with your local collecting society (ASCAP, PRS, BUMA/STEMRA, etc.).
  • You cannot self-generate ISWC codes.

4. IPI/CAE Number (Interested Parties Information / Composer-Author-Publisher)
- Purpose: Identifies songwriters, composers, and publishers for royalty collection.
- How to get it:
  • Assigned automatically when you join a collecting society (ASCAP, BMI, PRS, BUMA/STEMRA, etc.).


### NETHERLANDS SPECIFIC
In the Netherlands, the following organisations are responsible:

1. ISRC
- Managed by SENA (Stichting ter Exploitatie van Naburige Rechten), the official Dutch rights organisation for phonogram producers and performing artists.
- Application: Request your ISRC registrant code directly via SENA.
- Website: https://www.sena.nl

2. UPC/EAN
- Managed by GS1 Nederland.
- Application: Register for a GS1 account to purchase UPC/EAN barcode ranges.
- Website: https://www.gs1.nl

3. ISWC
- Managed by BUMA/STEMRA, the Dutch collecting society for composers and publishers.
- Application: Works registered in the BUMA/STEMRA portal automatically receive ISWC codes.
- Website: https://www.bumastemra.nl

4. IPI/CAE
- Assigned by BUMA/STEMRA when you join as a songwriter, composer, or publisher.
- Every member gets a unique IPI/CAE number used internationally.


### LEGAL REMINDER
Only use officially assigned prefixes and registration codes.
Manually inventing or assigning codes is NOT PERMITTED and will make your catalog invalid.
Always obtain your codes from your recognised national organisation before creating releases.




ISRC Manager is a desktop application for managing International Standard Recording Codes (ISRCs) and music metadata.  
It is designed for independent artists, producers, and small labels who want professional-grade catalog management without expensive or complex enterprise tools.  

The application helps you:
- Auto-generate ISRCs in the official ISO format
- Store, edit, and manage all track metadata in a customizable way
- Preview audio and image files directly inside the app
- Maintain multiple artist/label profiles
- Keep an audit trail of all changes with logging and backups
- Import/export your catalog to portable formats
- Ensure your release data is ready for digital distribution


## Features
ISRC Code Generation
- Automatically generates ISRC codes according to the ISO 3901 standard.
- Supports multiple profiles (e.g., per artist, label, or sublabel).
- Guarantees uniqueness by tracking the last issued sequence.

Metadata Management
- Fully customizable fields (titles, genres, release dates, contributors, etc.).
- Support for both standard fields (Title, Artist, Year, etc.) and custom user-defined fields.
- Metadata can include audio/image blobs for direct previews.

Database & Profiles
- Each profile manages its own ISRC code sequence.
- Switch profiles seamlessly — perfect for users handling multiple catalogs.
- SQLite database backend (fast, reliable, lightweight).

Media Previews
- Preview audio tracks (WAV, MP3, FLAC, etc.) with waveform and playback controls.
- Preview images (cover art, promotional materials).

Auditing & Backups
- All actions are logged with timestamps.
- Automatic backup of your database.
- Logs can be inspected for full transparency.

Import / Export
- Export metadata to CSV/JSON for distribution or reporting.
- Import existing catalogs to avoid manual entry.

User-Friendly UI
- Built with PySide6 (Qt for Python).
- Resizable table view with column reordering and custom layouts.
- Column order and visibility persist per profile.


## Why Use ISRC Manager?
- Indie Friendly: Designed for independent artists and labels, not giant companies.
- All-in-One: No need for Excel sheets, random ISRC generators, or fragmented tools.
- Compliance Ready: Ensures ISRCs follow the ISO 3901 format, ready for distributors.
- Future-Proof: Data stays portable (SQLite database + exports).
- Control: You own your data, nothing is uploaded or locked to a cloud provider.


## Installation
1. Prerequisites
- Operating System: macOS, Windows, or Linux
- Python: Version 3.9+ must be installed

2. Run the Installer
This project includes a universal installer: build.py

1. Download and extract the project folder.
2. Open a terminal (Command Prompt or shell).
3. Navigate to the extracted folder.
4. Run the installer with:

    python build.py

The installer will:
- Detect your operating system
- Build the application environment
- Ask you where to install the project package (safe user directory, no admin rights needed)
- Recreate the project structure and place the executable script there

3. Start the Application
After installation, start the app by running:

    python ISRC_manager_rev50.py


## Usage
1. Start the App
- On first launch, create or select a project directory.
- The database is initialized automatically.

2. Profiles
- Set up artist/label profiles under Settings → Profiles.
- Each profile maintains its own ISRC sequences and settings.

3. Adding Tracks
- Click Add Record to enter metadata.
- ISRC codes are auto-assigned, but you can edit manually if needed.

4. Custom Fields
- Add your own metadata fields in Settings → Custom Fields.
- These appear in the main table.

5. Media Previews
- Right-click a cell containing audio/image blobs → Preview.
- Use the built-in player for playback and waveform navigation.

6. Backups
- The app automatically creates backups in the /Database/backups/ folder.
- Logs are stored in /Database/logs/.

7. Import/Export
- File → Export to CSV/JSON for distribution.
- File → Import to bring in existing metadata.


## Keyboard Shortcuts
Audio preview dialog:
- Space: Play / Pause audio
- Escape: Close the dialog
- Left Arrow: Scrub backward
- Right Arrow: Scrub forward


## Project Structure
ISRC Manager/
├── Assets/                # Icons and logos
├── Database/              # User database, backups, logs
├── ISRC_manager_rev50.py  # Main application
├── build.py             # Universal installer
├── unit_test.py           # Unit tests
└── README.txt             # This file


## Support
This project is designed primarily for personal use, but is shared openly for indie creators.  
- Issues and bug reports can be submitted via GitHub.
- Contributions via pull requests are welcome.


## License
Free to use, modify, and share, resale prohibited.


ISRC Manager gives you professional catalog control without the complexity of enterprise systems.
