# Run History Replay in the Background

## Category

bugfix

## Original prompt, cleaned

Undo and Redo work, but when redoing, the app appears hung because the process operates on the UI thread.

Offload the process to a worker thread with a truthful, updating progress bar to inform the user that the work is still in operation.

## Context preserved

- Undo and Redo are functionally working.
- Redo currently makes the application appear hung because replay runs on the UI thread.
- History replay must run on a worker thread.
- The user must see a progress bar that advances according to work actually completed.

## Redactions

None
