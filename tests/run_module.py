"""Run one unittest or pytest module with an optional hard timeout."""

from __future__ import annotations

import argparse
import faulthandler
import sys
import time
import unittest
from pathlib import Path
from typing import Iterable

from isrc_manager.external_launch import install_test_process_desktop_safety
from tests.ci_groups import count_test_definitions, has_module_level_test_definitions


def _resolve_module_path(module: str) -> Path:
    prefix = "tests."
    if not module.startswith(prefix):
        raise ValueError(f"Unsupported test module: {module}")
    parts = module.removeprefix(prefix).split(".")
    if not parts or any(not part.isidentifier() for part in parts):
        raise ValueError(f"Unsupported test module: {module}")
    test_root = Path(__file__).resolve().parent
    module_path = test_root.joinpath(*parts).with_suffix(".py").resolve()
    if not module_path.is_relative_to(test_root) or not module_path.is_file():
        raise ValueError(f"Test module is missing: {module}")
    return module_path


def _run_pytest_file(module_path: Path) -> int:
    import pytest

    return int(pytest.main(["--no-cov", str(module_path)]))


def main(argv: Iterable[str] | None = None) -> int:
    install_test_process_desktop_safety()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", help="test module path to execute")
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
    try:
        module_path = _resolve_module_path(args.module)
    except ValueError as exc:
        parser.error(str(exc))
    suite = unittest.defaultTestLoader.loadTestsFromName(args.module)
    case_count = suite.countTestCases()
    definition_count = count_test_definitions(module_path)
    use_pytest = (
        case_count == 0
        or has_module_level_test_definitions(module_path)
        or definition_count > case_count
    )
    pytest_path = module_path if use_pytest else None
    runner = "pytest" if use_pytest else "unittest"
    print(
        f"---- module-start {args.module} runner={runner}"
        + (f" definitions={definition_count}" if use_pytest else f" tests={case_count}")
        + (f" timeout={args.timeout_seconds}s" if args.timeout_seconds is not None else ""),
        flush=True,
    )
    if args.timeout_seconds is not None:
        faulthandler.dump_traceback_later(args.timeout_seconds, repeat=False, exit=True)
    started = time.monotonic()
    try:
        if pytest_path is None:
            result = unittest.TextTestRunner(stream=sys.stdout, verbosity=args.verbosity).run(suite)
            exit_code = 0 if result.wasSuccessful() else 1
        else:
            exit_code = _run_pytest_file(pytest_path)
    finally:
        faulthandler.cancel_dump_traceback_later()
        elapsed = time.monotonic() - started
        print(f"---- module-end {args.module} elapsed={elapsed:.2f}s", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
