# Prevent Unintended Shared-Metadata Updates and Restore ISRC Generation

## Category

bugfix

## Original prompt, cleaned

When I update track metadata, for example the album title, unrelated records also get updated on save, causing a gigantic mess in the database.

Investigate why and propose a fix. The code is in production and running against a working database, so the change needs to be production-safe.

When updating shared metadata such as the album title or UPC, before overwriting anything, show a dialog listing the linked tracks that will receive the new shared metadata. Include checkboxes so I can uncheck tracks that I do not want to update as an extra fail-safe for the future.

I also discovered that uploading a new track through drag and drop does not create an ISRC automatically. Investigate and fix that.

Create an extra button in Track Edit that manually generates a new canonical ISRC for that track on command in case a future creation method fails.

## Context preserved

- The application and database are already in production use.
- Existing profile data must not be destructively migrated or guessed into new relationships.
- Shared-metadata propagation must be visible and selectively confirmable before a write.
- Drag-and-drop creation and manual recovery must reuse the canonical ISRC generator.

## Redactions

None
