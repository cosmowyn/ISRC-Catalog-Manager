"""Small SQLite helpers shared across the desktop app."""

from __future__ import annotations

import logging
import sqlite3

_CHECKPOINT_MODES = {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}


def safe_wal_checkpoint(
    conn: sqlite3.Connection | None,
    *,
    mode: str = "TRUNCATE",
    logger: logging.Logger | None = None,
) -> bool:
    """Attempt a WAL checkpoint without turning a successful save into a hard failure."""

    if conn is None:
        return False

    checkpoint_mode = str(mode or "TRUNCATE").strip().upper()
    if checkpoint_mode not in _CHECKPOINT_MODES:
        raise ValueError(f"Unsupported WAL checkpoint mode: {mode}")

    if conn.in_transaction:
        if logger is not None:
            logger.warning(
                "Skipping WAL checkpoint (%s) because the connection is still in a transaction.",
                checkpoint_mode,
            )
        return False

    try:
        result = conn.execute(f"PRAGMA wal_checkpoint({checkpoint_mode})").fetchone()
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            if logger is not None:
                logger.warning("Skipping WAL checkpoint (%s): %s", checkpoint_mode, exc)
            return False
        raise

    if result and int(result[0] or 0) != 0:
        if logger is not None:
            logger.warning(
                "WAL checkpoint (%s) reported busy state: %s",
                checkpoint_mode,
                tuple(result),
            )
        return False

    return True
