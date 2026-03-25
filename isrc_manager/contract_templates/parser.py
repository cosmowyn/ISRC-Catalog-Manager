"""Strict placeholder grammar helpers for contract template workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_PLACEHOLDER_RE = re.compile(r"\{\{([^{}]+)\}\}")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class InvalidPlaceholderError(ValueError):
    """Raised when a placeholder token is not valid canonical syntax."""


@dataclass(frozen=True, slots=True)
class PlaceholderToken:
    binding_kind: str
    namespace: str | None
    key: str
    canonical_symbol: str


@dataclass(frozen=True, slots=True)
class PlaceholderOccurrence:
    token: PlaceholderToken
    raw_text: str
    start_index: int
    end_index: int


def _normalize_segment(segment: str) -> str:
    if not segment or not _SEGMENT_RE.fullmatch(segment):
        raise InvalidPlaceholderError(f"Unsupported placeholder segment: {segment!r}")
    normalized = segment.lower().replace("-", "_")
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        raise InvalidPlaceholderError(f"Unsupported placeholder segment: {segment!r}")
    return normalized


def parse_placeholder(raw: str) -> PlaceholderToken:
    text = str(raw or "")
    if not text.startswith("{{") or not text.endswith("}}"):
        raise InvalidPlaceholderError(f"Placeholder must use double braces: {raw!r}")
    inner = text[2:-2]
    if not inner:
        raise InvalidPlaceholderError("Placeholder cannot be empty")
    if re.search(r"\s", inner):
        raise InvalidPlaceholderError("Whitespace is not allowed inside canonical placeholders")
    if "{" in inner or "}" in inner:
        raise InvalidPlaceholderError("Nested placeholders are not allowed")

    parts = inner.split(".")
    if not parts:
        raise InvalidPlaceholderError(f"Malformed placeholder: {raw!r}")

    binding_kind = _normalize_segment(parts[0])
    if binding_kind == "db":
        if len(parts) != 3:
            raise InvalidPlaceholderError("Database placeholders must use db.namespace.key")
        namespace = _normalize_segment(parts[1])
        key = _normalize_segment(parts[2])
        if namespace == "custom" and not re.fullmatch(r"cf_\d+", key):
            raise InvalidPlaceholderError("Custom database placeholders must use cf_<id>")
        canonical = f"{{{{db.{namespace}.{key}}}}}"
        return PlaceholderToken(
            binding_kind="db",
            namespace=namespace,
            key=key,
            canonical_symbol=canonical,
        )

    if binding_kind == "manual":
        if len(parts) != 2:
            raise InvalidPlaceholderError("Manual placeholders must use manual.key")
        key = _normalize_segment(parts[1])
        canonical = f"{{{{manual.{key}}}}}"
        return PlaceholderToken(
            binding_kind="manual",
            namespace=None,
            key=key,
            canonical_symbol=canonical,
        )

    raise InvalidPlaceholderError(f"Unsupported placeholder binding kind: {binding_kind}")


def extract_placeholders(text: str) -> tuple[PlaceholderOccurrence, ...]:
    occurrences: list[PlaceholderOccurrence] = []
    for match in _PLACEHOLDER_RE.finditer(str(text or "")):
        raw_text = match.group(0)
        try:
            token = parse_placeholder(raw_text)
        except InvalidPlaceholderError:
            continue
        occurrences.append(
            PlaceholderOccurrence(
                token=token,
                raw_text=raw_text,
                start_index=int(match.start()),
                end_index=int(match.end()),
            )
        )
    return tuple(occurrences)


def dedupe_placeholders(
    items: Iterable[PlaceholderToken | PlaceholderOccurrence],
) -> tuple[PlaceholderToken, ...]:
    seen: set[str] = set()
    deduped: list[PlaceholderToken] = []
    for item in items:
        token = item.token if isinstance(item, PlaceholderOccurrence) else item
        if token.canonical_symbol in seen:
            continue
        seen.add(token.canonical_symbol)
        deduped.append(token)
    return tuple(deduped)
