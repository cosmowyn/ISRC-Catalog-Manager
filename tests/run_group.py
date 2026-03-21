"""Run grouped unittest modules with bounded module-level subprocess timeouts."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from typing import Iterable

from tests import ci_groups

DEFAULT_GROUP_TIMEOUT_SECONDS: dict[str, int] = {
    "catalog-services": 10 * 60,
    "exchange-import": 15 * 60,
    "history-storage-migration": 15 * 60,
    "ui-app-workflows": 40 * 60,
}

DEFAULT_MODULE_TIMEOUT_SECONDS: dict[str, int] = {
    "catalog-services": 2 * 60,
    "exchange-import": 3 * 60,
    "history-storage-migration": 3 * 60,
    "ui-app-workflows": 5 * 60,
}

PARENT_TIMEOUT_GRACE_SECONDS = 30


def _resolve_modules(group: str | None, modules: Iterable[str]) -> tuple[str, ...]:
    explicit_modules = tuple(modules)
    if explicit_modules:
        return explicit_modules
    if group is None:
        raise ValueError("Specify either a test group or one or more --module values.")
    return ci_groups.group_modules(group)


def _effective_timeout_seconds(
    *,
    module_timeout_seconds: int | None,
    group_timeout_seconds: int | None,
    group_elapsed_seconds: float,
) -> int | None:
    effective_timeout = module_timeout_seconds
    if group_timeout_seconds is not None:
        remaining = group_timeout_seconds - group_elapsed_seconds
        if remaining <= 0:
            return 0
        remaining_seconds = max(1, int(remaining))
        if effective_timeout is None:
            effective_timeout = remaining_seconds
        else:
            effective_timeout = min(effective_timeout, remaining_seconds)
    return effective_timeout


def _build_module_command(
    module: str,
    *,
    timeout_seconds: int | None,
    verbosity: int,
    coverage: bool,
) -> list[str]:
    command = [sys.executable]
    if coverage:
        command.extend(["-m", "coverage", "run", "--parallel-mode"])
    command.extend(["-m", "tests.run_module", module, "--verbosity", str(verbosity)])
    if timeout_seconds is not None:
        command.extend(["--timeout-seconds", str(timeout_seconds)])
    return command


def _run_module(
    module: str,
    *,
    timeout_seconds: int | None,
    verbosity: int,
    coverage: bool,
) -> tuple[bool, float]:
    command = _build_module_command(
        module,
        timeout_seconds=timeout_seconds,
        verbosity=verbosity,
        coverage=coverage,
    )
    print(
        f"==> Running module: {module}"
        + (f" [timeout={timeout_seconds}s]" if timeout_seconds is not None else "")
        + (" [coverage]" if coverage else ""),
        flush=True,
    )
    started = time.monotonic()
    env = os.environ.copy()
    env.setdefault("PYTHONFAULTHANDLER", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        completed = subprocess.run(
            command,
            check=False,
            timeout=(
                timeout_seconds + PARENT_TIMEOUT_GRACE_SECONDS
                if timeout_seconds is not None
                else None
            ),
            env=env,
        )
        success = completed.returncode == 0
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - started
        print(
            f"error: parent timeout expired while waiting for module {module} after {elapsed:.2f}s",
            file=sys.stderr,
            flush=True,
        )
        return False, elapsed

    elapsed = time.monotonic() - started
    print(
        f"<== Finished module: {module} in {elapsed:.2f}s" + ("" if success else " [failed]"),
        flush=True,
    )
    if not success:
        print(
            f"error: module {module} exited with status {completed.returncode}",
            file=sys.stderr,
            flush=True,
        )
    return success, elapsed


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", nargs="?", choices=ci_groups.GROUP_ORDER)
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        help="Run one or more explicit unittest modules instead of a predefined group",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run ci_groups verification before executing modules",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Run each module through coverage in parallel-mode",
    )
    parser.add_argument(
        "--module-timeout-seconds",
        type=int,
        default=None,
        help="Per-module hard timeout in seconds",
    )
    parser.add_argument(
        "--group-timeout-seconds",
        type=int,
        default=None,
        help="Whole-run hard timeout budget in seconds",
    )
    parser.add_argument(
        "--verbosity",
        type=int,
        default=2,
        help="unittest verbosity passed to child module runs",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    group = args.group
    modules = _resolve_modules(group, args.module)
    if args.verify:
        errors = ci_groups.verify_grouping()
        if errors:
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            return 1

    group_timeout_seconds = args.group_timeout_seconds
    if group_timeout_seconds is None and group is not None:
        group_timeout_seconds = DEFAULT_GROUP_TIMEOUT_SECONDS.get(group)

    module_timeout_seconds = args.module_timeout_seconds
    if module_timeout_seconds is None and group is not None:
        module_timeout_seconds = DEFAULT_MODULE_TIMEOUT_SECONDS.get(group)

    group_started = time.monotonic()
    module_timings: list[tuple[str, float]] = []
    overall_success = True

    print(
        "Starting grouped test run:"
        f" group={group or '<explicit-modules>'}"
        f" modules={len(modules)}"
        f" group_timeout={group_timeout_seconds or 'none'}"
        f" module_timeout={module_timeout_seconds or 'none'}"
        f" coverage={args.coverage}",
        flush=True,
    )

    for index, module in enumerate(modules, start=1):
        elapsed = time.monotonic() - group_started
        effective_timeout = _effective_timeout_seconds(
            module_timeout_seconds=module_timeout_seconds,
            group_timeout_seconds=group_timeout_seconds,
            group_elapsed_seconds=elapsed,
        )
        if effective_timeout == 0:
            print(
                f"error: group timeout exceeded before module {index}/{len(modules)}: {module}",
                file=sys.stderr,
                flush=True,
            )
            return 1
        print(f"[{index}/{len(modules)}] elapsed={elapsed:.2f}s next={module}", flush=True)
        success, module_elapsed = _run_module(
            module,
            timeout_seconds=effective_timeout,
            verbosity=args.verbosity,
            coverage=args.coverage,
        )
        module_timings.append((module, module_elapsed))
        if not success:
            overall_success = False
            break

    total_elapsed = time.monotonic() - group_started
    slowest = sorted(module_timings, key=lambda item: item[1], reverse=True)[:5]
    print(f"Completed grouped test run in {total_elapsed:.2f}s", flush=True)
    if slowest:
        print("Slowest modules:", flush=True)
        for module, elapsed in slowest:
            print(f"  {elapsed:8.2f}s  {module}", flush=True)

    return 0 if overall_success and len(module_timings) == len(modules) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
