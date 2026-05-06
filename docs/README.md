# Documentation Hub

The in-app help system is the primary user-facing manual for ISRC Catalog Manager.

Use `Help > Help Contents` inside the application when you want the full guided documentation experience:

- quick-start chapters for orientation
- searchable topic pages for everyday workflows
- deeper chapters for repertoire structure, imports, storage, authenticity, diagnostics, and recovery

This `docs/` directory is the repository-side companion to that help surface. It keeps concise current-state guides available for browsing on GitHub or alongside source checkouts, while the in-app help remains the integrated manual.

## Core Product Docs

- [Repository README](../README.md): product overview, build/install guidance, and project context
- [Media Player Guide](media-player.md): audio-player auditioning, waveform, queue, album playlist, export, and app sound controls
- [Catalog Workspace Workflows](catalog-workspace-workflows.md): docked workspace, catalog managers, media intake, and daily review flow
- [Code Registry Workflows](code-registry-workflows.md): internal business codes, external catalog identifiers, generation, linking, and Registry SHA-256 Keys
- [Contract Template Workflows](contract-template-workflows.md): template import, symbol generation, fill-form drafting, live HTML preview, and PDF export
- [Template Conversion Workflow](template-conversion-workflow.md): rigid CSV/XLSX/XML template inspection, source mapping, saved reusable upload templates, preview, and faithful export
- [Bundled HTML License Template Example](../HTML license template/README.md): print-safe starter package, placeholder list, asset rules, draft-generation notes, and legal disclaimer
- [Import and Merge Workflows](import-and-merge-workflows.md): exchange import, XML review, mapping, match rules, and reviewed media attachment
- [Repertoire Knowledge System](repertoire_knowledge_system.md): tracks, releases, works, parties, contracts, rights, documents, and assets

## Operations and Delivery

- [Audio Authenticity Workflow](audio-authenticity-workflow.md): authentic masters, provenance copies, verification, and scope
- [Attachment Storage Modes](file_storage_modes.md): database-backed versus managed-file-backed records
- [GS1 Workflow Guide](gs1_workflow.md): workbook validation, grouped product editing, and export
- [Diagnostics and Recovery](diagnostics-and-recovery.md): quality review, diagnostics, cleanup, migration, and logs
- [Undo, History, and Snapshots](undo_redo_strategy.md): recovery model, snapshots, backups, and retention
- [Release Notes](../RELEASE_NOTES.md): latest automated release TL;DR and release metadata source
- [Release Build Automation](release-builds.md): tag-triggered GitHub release packaging, checksums, and in-app update manifest flow

## Customization

- [Theme Builder Guide](theme_builder.md): theme library, visual builder, media badge icons, preview controls, and advanced QSS

## Internal Continuity Docs

- [Implementation Handoffs](implementation_handoffs/): internal implementation notes and historical continuity files
- [Modularization Strategy](modularization_strategy.md): internal code-organization notes

## Recommended Reading Order

1. Start with the product [README](../README.md).
2. Open `Help > Help Contents` inside the app for the integrated manual.
3. Use the topic guides here when you want a repository-side companion for a specific workflow.
