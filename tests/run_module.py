"""Run a single unittest module with an optional hard timeout."""

from __future__ import annotations

import argparse
import faulthandler
import sys
import time
import unittest
from typing import Iterable

from isrc_manager.external_launch import install_test_process_desktop_safety


def main(argv: Iterable[str] | None = None) -> int:
    install_test_process_desktop_safety()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", help="unittest module path to execute")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Hard timeout enforced with faulthandler.dump_traceback_later",
    )
    parser.add_argument(
        "--verbosity",
        type=int,
        default=2,
        help="unittest verbosity for the module run",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    faulthandler.enable(all_threads=True)
    suite = unittest.defaultTestLoader.loadTestsFromName(args.module)
    case_count = suite.countTestCases()
    print(
        f"---- module-start {args.module} tests={case_count}"
        + (f" timeout={args.timeout_seconds}s" if args.timeout_seconds is not None else ""),
        flush=True,
    )
    if args.timeout_seconds is not None:
        faulthandler.dump_traceback_later(args.timeout_seconds, repeat=False, exit=True)
    started = time.monotonic()
    try:
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=args.verbosity).run(suite)
    finally:
        faulthandler.cancel_dump_traceback_later()
        elapsed = time.monotonic() - started
        print(f"---- module-end {args.module} elapsed={elapsed:.2f}s", flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
