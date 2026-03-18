# Demo Workspace

Current product version: `2.0.0`

This folder contains the reproducible demo tooling for the repository.

The generated catalog uses only fictional names, codes, artwork, licenses, and media. Nothing in the demo bundle is taken from a real artist, label, or customer profile.

## Build the Demo Workspace

From the project root:

```bash
.venv/bin/python demo/build_demo_workspace.py
```

That creates a LOCALAPPDATA-style demo tree under `demo/.runtime/` with:

- a fictional profile database
- managed audio and artwork files
- sample license PDFs
- a few snapshot/history records for showcase screenshots

## Capture README Screenshots

```bash
.venv/bin/python demo/capture_demo_screenshots.py
```

That refreshes the demo workspace and writes new screenshots to `docs/screenshots/`.
