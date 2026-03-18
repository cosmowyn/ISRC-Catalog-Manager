# Undo, History, and Snapshots

Current product version: `2.0.0`

ISRC Catalog Manager is built for work that should be recoverable.

Catalog maintenance often involves high-consequence operations:

- bulk edits
- imports
- document migration
- metadata cleanup
- profile restore
- file-backed record changes

This guide explains how the app approaches undo, history, and restore safety.

## Why Recovery Matters In A Catalog App

Music catalog work is cumulative. A mistake is not just a typo on screen; it can become:

- a broken export
- a lost document
- an incorrect code
- an overwritten relationship
- a damaged release structure

That is why the application uses a layered recovery model rather than relying on a simple in-memory undo stack.

## The Recovery Model

The app uses a hybrid strategy built around three ideas:

### 1. Reversible history for normal actions

Day-to-day mutations such as edits, settings changes, and supported CRUD actions are recorded into persistent history so they can be undone and redone where appropriate.

### 2. Snapshot protection for high-risk workflows

Heavier operations, including restore flows, imports, and legacy license migration, are protected by snapshot-style recovery so the system can move the profile backward safely even when multiple files and tables are involved.

### 3. File-aware recovery

The application does not only protect database rows. Where supported, it also keeps history aware of managed files such as:

- stored licenses
- contract documents
- asset registry files
- release and track media

This matters because a music catalog is not only metadata. It is metadata plus the files that prove and deliver it.

## What Users Can Do

From the History menu, users can:

- undo the latest reversible action
- redo the latest reversed action
- inspect the persistent history log
- create a manual snapshot before a risky change
- restore a previous snapshot when necessary

The goal is not just convenience. It is confidence.

## Where This Is Especially Important

### Imports and large edits

When a large import or cleanup action touches many records, users need a way back if the mapping or source data was wrong.

### Legacy license migration

When migrating legacy license PDFs into structured contracts and documents, the app now:

- creates a pre-migration restore point
- copies and verifies document data
- only removes legacy rows and files after verification
- records the migration in history so it can be traced and reversed through the supported restore path

### Restore workflows

Database restore is inherently a full-state operation. That is why it is handled as a protected history boundary rather than a casual row-by-row undo.

## Product Promise

The application is designed so users can work with more confidence in heavier workflows:

- imports should not feel like a gamble
- migrations should not be one-way leaps
- settings and theme changes should not be fragile
- managed-file workflows should not silently destroy references

That safety model is part of the product itself, not a hidden engineering detail.

## Technical Direction

Under the hood, the app’s history system is designed around a hybrid of:

- logical inverse actions for normal reversible operations
- snapshot-backed recovery for high-risk and high-volume workflows
- persistent history storage instead of a session-only memory stack

This is the right fit for a desktop catalog application that spans SQLite data, managed files, settings, and profile-level state.

## In Practice

For the user, the important result is straightforward:

- you can work faster because important actions are recoverable
- you can migrate older data with less fear
- you can try larger cleanup passes without depending on luck
- you can treat the app as a durable working system rather than a fragile spreadsheet replacement
