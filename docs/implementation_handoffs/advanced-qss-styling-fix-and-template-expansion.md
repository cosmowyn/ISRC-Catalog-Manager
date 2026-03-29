# Advanced QSS Styling Fix And Template Expansion

## 1. Root Cause Of The Stylesheet Apply Failure

The runtime stylesheet failure was not a single editor hint problem. It came from two connected issues in the existing advanced QSS pipeline:

- `custom_qss` is appended directly into the generated app stylesheet in `isrc_manager/theme_builder.py`, so malformed advanced QSS can poison the whole applied stylesheet.
- The live preview safeguard in `ApplicationSettingsDialog._refresh_theme_previews()` was broken because it validated `values["theme_settings"]...` even though `values` does not exist in that scope. That meant the intended "hold the last valid advanced QSS" path was not reliable during theme preview refresh.

There was also a generator-quality issue in the editor itself:

- the advanced editor exposed property completions for `max-height`, `max-width`, and `outline`, but those fell back to blank `property: ;` starter lines because they did not have real property templates.
- selector-catalog double click inserted a bare selector instead of a full rule/template, which made it easy to feed incomplete QSS into the live preview workflow.

## 2. Fixes Made To QSS Generation / Application

The implementation keeps the existing advanced QSS system, but hardens the real failure points:

- Fixed `ApplicationSettingsDialog._refresh_theme_previews()` so it validates `theme_values["custom_qss"]` correctly and only previews the last known good advanced QSS when the current editor text is invalid.
- Left the app-level apply path using the same shared validation gate, so preview and apply now follow the same contract.
- Added real starter templates for previously exposed-but-unmapped properties:
  - `max-height`
  - `max-width`
  - `outline`
- Kept raw QSS editing available, but reduced accidental invalid input by making the safer full-template path more prominent in the selector catalog.

## 3. Current Autocomplete Limitations Found

Before this pass, autocomplete was already context-aware, but it still had several gaps for non-expert users:

- fuller widget templates existed, but users still had to discover them through `[template]` completions or a secondary catalog action
- the selector catalog inserted raw selectors by default on double click
- reference-entry-specific context existed in code (`build_qss_reference_template()`), but the UI was bypassing it and inserting only raw selector-based templates
- template detail text was still terse enough that the "start from a full scaffold and delete what you do not need" workflow was easy to miss

## 4. New Widget-Template Strategy Implemented

The implementation now leans into the existing template system instead of inventing a second authoring flow:

- selector catalog double click now inserts a full template instead of a bare selector
- the catalog keeps a separate explicit `Insert Selector Only` action for power users who want raw selector text
- the primary catalog action is now `Insert Full Template`
- reference-driven template insertion now uses `build_qss_reference_template()`, so inserted templates include a short context note from the selected reference entry and, for object-name entries, automatically expand into typed selectors like `QPushButton#theme_save_button`

This keeps advanced flexibility while making the safer template-first workflow the default path.

## 5. Editor / Autocomplete Improvements

The editor/autocomplete experience was expanded without redesigning the whole theme settings page:

- template completion detail text now explicitly explains that the inserted result is a full working template and that users can delete unused blocks
- template completion ranking was biased upward so full templates are easier to discover in selector context
- selector-template insertion now replaces the whole current selector text range instead of only the last compound fragment, which avoids partial-selector leftovers when users expand a selector into a full template
- `QssCodeEditor` now supports reference-entry-aware template insertion through `insert_template_for_reference_entry()`
- theme-page help text now points users toward the full-template path more clearly

## 6. Tests Added / Updated

Updated tests now cover the real regression surfaces for this pass:

- `tests/test_qss_autocomplete.py`
  - descendant selector template insertion replaces the full selector text cleanly
  - generated templates apply without Qt parser warnings
  - extended property completions use real starter values
  - reference-entry template insertion includes contextual header comments and typed selectors
  - dialog-level selector reference template insertion uses the fuller reference-aware template path
- `tests/test_theme_builder.py`
  - invalid advanced QSS keeps the last valid preview stylesheet instead of replacing it
  - invalid advanced QSS rejection still works through the shared theme-application payload path

## 7. Risks / Caveats

- validation is still intentionally lightweight and permissive for power users. It is better aligned now because preview and apply use the same gate, but it is not a full semantic QSS linter.
- template coverage is only as broad as the current widget metadata/template catalog. The new workflow makes those templates easier to reach, but app-specific selector/template expansion can still be extended further in later passes.
- `ISRC_manager.py` still has unrelated pre-existing Ruff findings outside this advanced-QSS scope, so focused lint verification was run on the touched QSS/editor test files plus compile/test coverage for the dialog integration.

## 8. Explicit Outcome Statement

Advanced styling now provides fuller widget-specific QSS templates and more reliable stylesheet application. Users can still edit raw QSS directly, but the default selector-reference workflow now steers them toward complete working templates, and the live preview/apply path no longer depends on the broken preview safeguard that previously let invalid advanced QSS reach stylesheet application more easily.
