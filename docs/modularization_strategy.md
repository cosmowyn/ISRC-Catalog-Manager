# Modularization Strategy

Current product version: `2.0.0`

This document explains how the application is being modernized internally without changing its user-facing behavior.

ISRC Catalog Manager has grown into a broad local-first catalog platform. That growth has been intentional, but it also means the codebase needs clear modular boundaries so the product can keep expanding without becoming brittle.

## Why Modularization Matters Here

The app now covers:

- track and release catalog workflows
- works, parties, contracts, rights, and assets
- GS1 metadata
- import/export tooling
- quality scanning
- history and snapshots
- theme building
- background tasks

That is a meaningful desktop product, not a small utility script. Modularization matters because the product now deserves a maintainable internal architecture equal to its feature depth.

## Current Direction

The project is moving away from a monolithic entry file and toward focused packages that keep responsibilities clear.

The direction is practical rather than theoretical:

- preserve runtime behavior
- preserve database compatibility
- preserve settings and file layout
- extract cohesive pieces only when the move reduces risk and improves maintainability

In other words, this is not a rewrite. It is a controlled maturation of a working application.

## What Has Already Been Split Out

The codebase already includes dedicated packages for major product areas such as:

- `isrc_manager.works`
- `isrc_manager.parties`
- `isrc_manager.contracts`
- `isrc_manager.rights`
- `isrc_manager.assets`
- `isrc_manager.search`

The application shell has also become more testable through extracted bootstrap and shell helpers rather than keeping every responsibility inside `ISRC_manager.py`.

## Architectural Goal

The long-term target is a codebase where:

- the entry point stays thin
- the main window focuses on composition and delegation
- feature logic lives in focused services and dialogs
- database access is isolated from UI concerns
- domain rules can be tested without booting the whole shell

The intended dependency direction is:

`ui -> services -> repositories/db -> domain`

This keeps the product easier to maintain as the feature set grows.

## What Should Stay Thin

Some code belongs close to the entry path:

- startup orchestration
- top-level window composition
- high-level action wiring
- app lifecycle and shutdown coordination

The goal is not to move everything out of sight. It is to stop mixing product logic, file operations, database logic, and UI assembly in the same oversized methods.

## Why This Matters For Users

Even though modularization is a developer-facing topic, it supports clear product outcomes:

- safer feature expansion
- lower regression risk
- faster test coverage growth
- more predictable maintenance
- easier onboarding for contributors

That matters for a catalog application expected to grow in capability while protecting existing workspaces.

## Testing And Modularization

As modules are extracted, the project also gains stronger coverage around:

- real app startup
- dialog/controller behavior
- workflow integration
- migrations
- background-task safety

This means modularization is not just about cleaner files. It is also about creating reliable seams for verification.

## Product Philosophy Behind The Refactor

The project is being treated like a finished desktop product, not a disposable internal script.

That means the internal architecture is expected to support:

- long-term maintenance
- safe feature growth
- stable packaged builds
- documentation that stays aligned with reality

The modularization strategy exists to support that standard.
