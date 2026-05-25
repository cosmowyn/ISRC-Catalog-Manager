# Lean Codebase Remediation Plan (QA/QC Closure)

## Closure outcome

Both targeted duplication findings have been confirmed as intentional and are **closed** from active remediation:

- Watermark helpers: `confirmed intentional`
- Track service/protocol names: `confirmed intentional`

## Remaining follow-up action

No code-level remediation is required for this closure. The remaining required action is environment readiness before full validation.

Recommended next steps (documentation-only recommendations):

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -e .[dev]
```

Then rerun full validation with the grouped test runner:

```bash
QT_QPA_PLATFORM=offscreen python3 -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600
```

If that group completes successfully, continue with the remaining relevant groups:

- `exchange-import`
- `history-storage-migration`
- `ui-app-workflows`

This action should be performed in a prepared runtime/test environment before any claims of full validation completion.
