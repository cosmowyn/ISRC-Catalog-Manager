# Architecture Metrics

This file is the mandatory planning record for architecture metrics captured at major de-monolithization gates. Phase 0 must initialize the first gate baseline before implementation starts. Later phase handoffs must update this file when the phase changes architecture metrics or establishes a new gate baseline.

This planning-remediation pass created the required structure only; it did not implement metric scripts or CI gates.

## Required Metrics
- `ISRC_manager.py` LOC
- `App` LOC while it still exists
- compatibility alias count
- root import count
- module LOC over warning threshold
- module LOC over mandatory split threshold
- import cycle count
- package parity status
- tests still using root imports

## Thresholds
- module warning threshold: 1200 LOC
- module mandatory split threshold: 2500 LOC

## Gate Records
Add one entry per major gate:

```text
## <Gate / Phase Name> — <YYYY-MM-DD HH:MM TZ>
- ISRC_manager.py LOC:
- App LOC:
- compatibility alias count:
- root import count:
- module LOC over warning threshold:
- module LOC over mandatory split threshold:
- import cycle count:
- package parity status:
- tests still using root imports:
- notes / exceptions:
```

## CI / Tooling Notes
Future implementation may add scripts or CI checks to collect or enforce these metrics. This file only defines the planning contract until such tooling exists.
