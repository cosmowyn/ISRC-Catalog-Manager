# Documentation Hub

The in-app help system is the primary user-facing manual for ISRC Catalog Manager.

Use `Help > Help Contents` inside the application when you want the full guided documentation experience:

- quick-start chapters for orientation
- searchable topic pages for everyday workflows
- deeper chapters for repertoire structure, imports, storage, authenticity, diagnostics, and recovery

This `docs/` directory is the repository-side companion to that help surface. It keeps concise current-state guides available for browsing on GitHub or alongside source checkouts, while the in-app help remains the integrated manual.

## Core Product Docs

- [Repository README](../README.md): product overview, build/install guidance, and project context
- [Catalog Workspace Workflows](catalog-workspace-workflows.md): docked workspace, catalog managers, media intake, and daily review flow
- [Contract Template Workflows](contract-template-workflows.md): template import, symbol generation, fill-form drafting, live HTML preview, and PDF export
- [Import and Merge Workflows](import-and-merge-workflows.md): exchange import, XML review, mapping, match rules, and reviewed media attachment
- [Repertoire Knowledge System](repertoire_knowledge_system.md): tracks, releases, works, parties, contracts, rights, documents, and assets

## Operations and Delivery

- [Audio Authenticity Workflow](audio-authenticity-workflow.md): authentic masters, provenance copies, verification, and scope
- [Attachment Storage Modes](file_storage_modes.md): database-backed versus managed-file-backed records
- [GS1 Workflow Guide](gs1_workflow.md): workbook validation, grouped product editing, and export
- [Diagnostics and Recovery](diagnostics-and-recovery.md): quality review, diagnostics, cleanup, migration, and logs
- [Undo, History, and Snapshots](undo_redo_strategy.md): recovery model, snapshots, backups, and retention

## Customization

- [Theme Builder Guide](theme_builder.md): theme library, visual builder, media badge icons, preview controls, and advanced QSS

## Internal Continuity Docs

- [Implementation Handoffs](implementation_handoffs/): internal implementation notes and historical continuity files
- [Modularization Strategy](modularization_strategy.md): internal code-organization notes

## Recommended Reading Order

1. Start with the product [README](../README.md).
2. Open `Help > Help Contents` inside the app for the integrated manual.
3. Use the topic guides here when you want a repository-side companion for a specific workflow.
