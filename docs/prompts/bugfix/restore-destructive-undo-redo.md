# Restore Destructive Undo and Redo

## Category

bugfix

## Original prompt, cleaned

Investigate the undo/redo stack. When deleting records from the database and trying to undo it, I get an error message saying that it is not allowed. The purpose of Undo is to reverse destructive actions by the user.

Patch the findings and restore full undo/redo capability.

## Context preserved

- Diagnose the error raised when undoing database record deletion.
- Restore Undo and Redo for destructive user actions, rather than weakening protected database invariants.
- Preserve unrelated records while replaying an action.

## Redactions

None.
