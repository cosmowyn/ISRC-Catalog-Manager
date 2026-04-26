"""SemVer parsing, comparison, and bump helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class SemVerError(ValueError):
    """Raised when a version string is not valid SemVer."""


def _validate_identifier_group(value: str | None, *, prerelease: bool) -> tuple[str, ...]:
    if not value:
        return ()
    identifiers = tuple(value.split("."))
    for identifier in identifiers:
        if identifier == "":
            raise SemVerError("SemVer identifiers cannot be empty.")
        if (
            prerelease
            and identifier.isdigit()
            and len(identifier) > 1
            and identifier.startswith("0")
        ):
            raise SemVerError("Numeric pre-release identifiers cannot contain leading zeroes.")
    return identifiers


@total_ordering
@dataclass(frozen=True, slots=True)
class SemVer:
    """A strict SemVer 2.0.0 version value."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: object) -> "SemVer":
        text = str(value or "").strip()
        match = _SEMVER_RE.fullmatch(text)
        if not match:
            raise SemVerError(f"Invalid SemVer version: {text!r}")
        prerelease = _validate_identifier_group(match.group("prerelease"), prerelease=True)
        build = _validate_identifier_group(match.group("build"), prerelease=False)
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            prerelease=prerelease,
            build=build,
        )

    @property
    def without_build(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            base = f"{base}-" + ".".join(self.prerelease)
        return base

    def bump(self, level: str) -> "SemVer":
        clean_level = str(level or "").strip().lower()
        if clean_level == "major":
            return SemVer(self.major + 1, 0, 0)
        if clean_level == "minor":
            return SemVer(self.major, self.minor + 1, 0)
        if clean_level == "patch":
            return SemVer(self.major, self.minor, self.patch + 1)
        raise ValueError(f"Unsupported SemVer bump level: {level!r}")

    def __str__(self) -> str:
        text = self.without_build
        if self.build:
            text = f"{text}+" + ".".join(self.build)
        return text

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        core = (self.major, self.minor, self.patch)
        other_core = (other.major, other.minor, other.patch)
        if core != other_core:
            return core < other_core
        return _compare_prerelease(self.prerelease, other.prerelease) < 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return False
        return (
            self.major,
            self.minor,
            self.patch,
            self.prerelease,
        ) == (
            other.major,
            other.minor,
            other.patch,
            other.prerelease,
        )


def _compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    if not left and not right:
        return 0
    if not left:
        return 1
    if not right:
        return -1
    for left_part, right_part in zip(left, right):
        if left_part == right_part:
            continue
        left_numeric = left_part.isdigit()
        right_numeric = right_part.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_part) < int(right_part) else 1
        if left_numeric:
            return -1
        if right_numeric:
            return 1
        return -1 if left_part < right_part else 1
    if len(left) == len(right):
        return 0
    return -1 if len(left) < len(right) else 1


def parse_semver(value: object) -> SemVer:
    return SemVer.parse(value)


def bump_version(version: object, level: str) -> str:
    return str(SemVer.parse(version).bump(level))


def is_valid_semver(value: object) -> bool:
    try:
        SemVer.parse(value)
    except SemVerError:
        return False
    return True
