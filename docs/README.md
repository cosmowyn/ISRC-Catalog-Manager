# Documentation Hub

This directory is the user-guide and deep-dive layer for ISRC Catalog Manager.

Use the repository [`README.md`](../README.md) for the product overview, positioning, and feature map. Use the guides here when you want the real workflow detail behind that overview.

## Getting Started

- [Repository README](../README.md) explains what the app is, who it is for, and why the workflow model matters.
- On first launch, the app can optionally open `Application Settings` so you can set registration values, snapshot posture, and appearance before deeper catalog work.
- [Catalog Workspace Workflows](catalog-workspace-workflows.md) is the best first deep dive if you want to understand how the docked desktop workspace is meant to be used day to day.

## Import & Exchange

- [Import and Merge Workflows](import-and-merge-workflows.md) covers exchange import, saved per-format choices, explicit skip targets, JSON/package mapping behavior, XML import, bulk audio attachment, audio tag import/export, matching rules, merge behavior, and package round-tripping.
- [GS1 Workflow Guide](gs1_workflow.md) covers workbook preparation and verified export from catalog data.

## Catalog & Repertoire Workflows

- [Catalog Workspace Workflows](catalog-workspace-workflows.md) explains the docked workspace model, tabbed managers, release assignment, saved searches, and relationship review.
- [Repertoire Knowledge System](repertoire_knowledge_system.md) explains how tracks, releases, works, parties, contracts, rights, documents, and assets fit together.

## Operations & Recovery

- [Diagnostics and Recovery](diagnostics-and-recovery.md) covers quality review, async diagnostics and repairs, suggested fixes, storage migration adoption/resume behavior, history budget reporting, cleanup, trim, and logs.
- [Attachment Storage Modes](file_storage_modes.md) explains database-backed versus managed-file-backed storage and why that matters for portability and maintenance.
- [Undo, History, and Snapshots](undo_redo_strategy.md) explains the recovery model behind edits, imports, retention and safety levels, history storage budgets, and higher-risk workflows.

## Customization

- [Theme Builder Guide](theme_builder.md) documents the visual builder, starter themes, BLOB icon tooling, selector reference, and advanced QSS workflow.

## Developer / Internal Docs

- [Modularization Strategy](modularization_strategy.md) tracks internal structure and code-organization work.
- [Implementation Handoffs](implementation_handoffs/) contains follow-up notes, implementation summaries, and audit documents.
- [Screenshots](screenshots/) contains reference images used by the documentation set.

## Recommended Reading Order

- Start with the product [README](../README.md).
- Read [Import and Merge Workflows](import-and-merge-workflows.md) if external metadata intake matters to you.
- Read [Catalog Workspace Workflows](catalog-workspace-workflows.md) and [Repertoire Knowledge System](repertoire_knowledge_system.md) for daily catalog operations.
- Read [Diagnostics and Recovery](diagnostics-and-recovery.md) and [Undo, History, and Snapshots](undo_redo_strategy.md) once you are working with larger or riskier catalog changes.
