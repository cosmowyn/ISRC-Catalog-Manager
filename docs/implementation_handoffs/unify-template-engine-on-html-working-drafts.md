# Unify Template Engine On HTML Working Drafts

## 1. Previous template-engine backend behavior

Before this change, the contract-template backend used three materially different paths:

- HTML imports were already HTML-native:
  - the imported HTML file or package was stored as a managed HTML bundle
  - draft synchronization, live preview, and PDF export all operated on HTML working files
- DOCX imports preserved the original DOCX source, but DOCX effectively remained the primary working/export format:
  - placeholder replacement for export happened against DOCX bytes
  - PDF export for DOCX-derived drafts came from a DOCX-oriented path
  - the live HTML preview was gated off because the revision was not `source_format == "html"`
- Pages imports preserved the original Pages file and used a Pages -> DOCX bridge for scan/export work:
  - Pages content was converted to DOCX for ingestion and export workflows
  - the live HTML preview was likewise unavailable because the revision was not treated as HTML-working

That split meant the preview pipeline and the true working/export pipeline were not unified for Pages and DOCX revisions.

## 2. Pages -> DOCX -> HTML working-draft pipeline

Pages revisions now follow a single normalized backend path:

1. the original imported `.pages` file is stored unchanged as the source asset
2. when an HTML working draft is needed, the revision is converted:
   - Pages -> DOCX through the existing Pages adapter
   - DOCX -> HTML through the new DOCX-to-HTML normalization adapter
3. the resulting HTML bundle is stored in managed template source storage
4. drafting, preview rendering, and PDF export all operate from that HTML working draft

The original Pages source is never overwritten during drafting or export.

## 3. DOCX -> HTML working-draft pipeline

DOCX revisions now normalize into HTML as their working format:

1. the original imported `.docx` file is stored unchanged as the source asset
2. the revision is normalized into an HTML bundle through the DOCX-to-HTML adapter
3. the HTML bundle is stored as the working-draft source for later preview/draft sync/export work
4. drafting, preview rendering, and PDF export all run from that HTML working draft

DOCX placeholder replacement compatibility is still preserved by emitting a resolved DOCX artifact for DOCX- and Pages-derived exports, but that DOCX artifact is now additive compatibility output, not the true working/export engine.

## 4. Original-source preservation model

The original imported source remains authoritative and unchanged:

- HTML imports continue to preserve their HTML source/bundle
- DOCX imports preserve the original DOCX bytes unchanged
- Pages imports preserve the original Pages bytes unchanged

The normalized HTML bundle is stored separately from the original source file and is used as the working-draft/edit representation. `source_format` on template/revision records still means the original source type for backward compatibility.

## 5. Preview/export integration changes

The preview/export seam is now unified around “supports an HTML working draft” instead of “is an HTML source revision.”

Structural changes:

- DOCX/Pages revisions can now materialize an HTML working-draft source path
- draft sync no longer hard-requires `source_format == "html"`
- preview sessions no longer hard-require `source_format == "html"`
- fill-workspace preview controls are enabled whenever the selected revision can be prepared as an HTML working draft
- PDF export always renders from the HTML working draft

Compatibility behavior preserved:

- DOCX- and Pages-derived exports still write a resolved DOCX artifact
- HTML-derived exports continue to write a resolved HTML artifact and PDF
- preview payload semantics keep `source_format` as the original imported format and now add `working_format = "html"`

## 6. User guidance added

The import/admin workspace description now includes best-practice guidance:

- print-safe HTML templates provide the best fidelity
- Pages and DOCX imports are preserved unchanged and normalized into HTML working drafts

This keeps the workflow familiar while making the fidelity guidance explicit but non-alarming.

## 7. Tests added/updated

Updated and expanded coverage includes:

- DOCX import now asserts:
  - original DOCX bytes are preserved
  - an HTML working-draft source can be resolved
- Pages import now asserts:
  - original Pages bytes are preserved
  - the Pages adapter plus DOCX-to-HTML normalization produce an HTML working-draft source
- blocked Pages imports still remain stored but do not incorrectly claim an HTML working draft
- DOCX export now asserts:
  - PDF export is rendered from the HTML working draft
  - preview payload includes `working_format = "html"`
  - resolved HTML artifacts are retained alongside compatibility DOCX artifacts
- Pages export now asserts:
  - original Pages bytes remain unchanged
  - PDF export runs through the HTML working draft
  - the Pages PDF handoff path is no longer used for the real PDF export engine
- workspace dialog coverage now asserts:
  - DOCX-derived revisions can render the live HTML preview
  - fill-tab export retains `pdf`, `resolved_docx`, and `resolved_html`
- app-shell export coverage was updated to match the new artifact set

## 8. Risks/caveats

- Conversion fidelity is still bounded by the available conversion stack:
  - Pages fidelity depends on the existing Pages -> DOCX bridge
  - DOCX fidelity depends on the DOCX -> HTML normalization adapter
  - on macOS the adapter can use native `textutil`
  - outside that path, the fallback is a best-effort OOXML-to-HTML conversion and should not be described as pixel-perfect
- The offscreen Qt WebEngine test environment can still hit unrelated GPU/context-loss issues when large live-preview suites run together. The focused preview/export regressions for the new pipeline pass, and that boundary should remain documented honestly.

## 9. Explicit outcome statement

HTML is now the only true working draft format for contract-template drafting, editing, preview rendering, and PDF export.

Pages and DOCX imports are still supported and their original source files are still preserved unchanged, but both now normalize into HTML working drafts so the preview layer and the real export path run from the same backend representation.
