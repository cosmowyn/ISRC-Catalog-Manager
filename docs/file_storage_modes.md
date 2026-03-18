# Attachment Storage Modes

ISRC Catalog Manager now supports two storage modes for file-backed records across the catalog.

The goal is simple: keep the user-facing workflow consistent while letting teams choose whether files should live inside the profile database or in app-managed local storage.

## What Uses This

The dual-storage model applies to file-backed records such as:

- track audio
- track and album artwork
- release artwork
- custom `blob_audio` and `blob_image` fields
- license PDFs
- contract documents
- asset versions
- GS1 workbook templates

If a record is file-backed, the app now treats storage choice as part of the record rather than assuming everything must be a BLOB or everything must be a managed file.

## The Two Modes

### Database mode

In `Database` mode, the raw file bytes are stored in the profile database.

Use this when you want:

- fewer external file dependencies
- a more self-contained profile
- file-backed records to travel with the database itself

### Managed file mode

In `Managed file` mode, the app copies the source file into an app-controlled storage folder and stores only the managed path in the database.

Use this when you want:

- files to remain visible on disk
- lighter database growth
- a storage layout that is easier to inspect outside the UI

The managed file is never just a pointer to the original user-selected source path. The app copies the file into its own managed area first, then stores the managed location.

## Managed Storage Behavior

Managed storage is designed to be local, controlled, and resilient:

- the app uses its own storage roots rather than depending on arbitrary external paths
- duplicate filenames are handled safely
- stored files are organized by app-managed subfolders where appropriate
- paths are validated before use
- stale managed files are only removed when they are no longer referenced

This makes managed-file mode usable without depending on the original import location staying intact.

## Choosing Or Converting A Mode

For new file-backed records, the UI now offers a storage choice at the point where a file is attached or imported.

For existing records, supported editors, browser panels, and context menus can convert records between modes. The rest of the app is expected to keep behaving the same way after the conversion:

- open
- preview
- export or save as
- replace
- delete
- package export/import

## Legacy Compatibility

Older records remain readable.

If a legacy row has no explicit storage mode yet, the app infers the effective mode from the data that already exists:

- a stored BLOB is treated as `Database`
- a managed stored path is treated as `Managed file`

This keeps older profiles working without forcing a one-time manual migration just to read existing records.

## Conversion Safety

The conversion flow is designed to avoid partial state changes.

In practical terms, the app:

- reads the current source representation first
- writes the target representation
- verifies the target before finalizing the record update
- only removes obsolete managed files when they are no longer referenced

The aim is to avoid silent data loss, broken pointers, and orphan cleanup mistakes during mode switches.

## Metadata Handling

The storage layer preserves the file bytes plus the record metadata already tracked by the app, including values such as:

- filename
- MIME type
- size
- checksum where applicable

Format-aware tag writing remains a separate workflow used for exported tagged audio copies. Storage conversion itself is focused on preserving bytes and catalog metadata rather than inventing format-specific metadata rewrites during every mode change.

## Exchange And Portability

Plain tabular exports continue to describe file-backed records through metadata and paths where appropriate.

ZIP package export/import is the portability layer for actual file contents. Package workflows now:

- materialize both database-backed and managed-file-backed records into portable package files
- preserve the recorded storage mode in the manifest
- restore that mode during import

That means a database-backed attachment can round-trip through a package without being silently downgraded into a path-backed record, and a managed-file-backed record can remain managed on the other side.

## GS1 Template Storage

The same design now applies to the configured GS1 workbook template.

Teams can keep the validated workbook:

- inside the profile database, or
- as a managed local file

The export workflow stays the same either way, and the template can be converted later if storage needs change.
