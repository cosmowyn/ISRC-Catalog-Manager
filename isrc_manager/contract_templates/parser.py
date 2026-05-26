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
    indexed: bool = False
    manual_type: str | None = None
    manual_options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlaceholderOccurrence:
    token: PlaceholderToken
    raw_text: str
    start_index: int
    end_index: int


def _consume_optional_indexed_suffix(
    parts: tuple[str, ...],
    *,
    error_message: str,
    expected_part_count: int,
) -> tuple[tuple[str, ...], bool]:
    if len(parts) == expected_part_count + 1:
        if _normalize_segment(parts[-1]) != "indexed":
            raise InvalidPlaceholderError(error_message)
        return tuple(parts[:expected_part_count]), True
    if len(parts) != expected_part_count:
        raise InvalidPlaceholderError(error_message)
    return tuple(parts), False


def _normalize_segment(segment: str) -> str:
    if not segment or not _SEGMENT_RE.fullmatch(segment):
        raise InvalidPlaceholderError(f"Unsupported placeholder segment: {segment!r}")
    normalized = segment.lower().replace("-", "_")
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        raise InvalidPlaceholderError(f"Unsupported placeholder segment: {segment!r}")
    return normalized


def _split_placeholder_parts(inner: str) -> tuple[str, ...]:
    parts: list[str] = []
    current: list[str] = []
    in_options = False
    for char in inner:
        if char == "[":
            if in_options:
                raise InvalidPlaceholderError("Nested option brackets are not allowed")
            in_options = True
            current.append(char)
            continue
        if char == "]":
            if not in_options:
                raise InvalidPlaceholderError("Unmatched option bracket")
            in_options = False
            current.append(char)
            continue
        if char == "." and not in_options:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    if in_options:
        raise InvalidPlaceholderError("Unclosed option bracket")
    parts.append("".join(current))
    return tuple(parts)


def _parse_manual_segment(segment: str) -> tuple[str, str | None, tuple[str, ...], str]:
    match = re.fullmatch(
        r"(?P<key>[A-Za-z0-9_-]+)(?:\$(?P<manual_type>bool|list)\[(?P<options>[^\[\]{}]*)\])?",
        segment,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise InvalidPlaceholderError(
            "Manual placeholders must use manual.key, manual.key.indexed, "
            "manual.key$type[option;option], or manual.key$type[option;option].indexed"
        )
    key = _normalize_segment(match.group("key"))
    manual_type = match.group("manual_type")
    if manual_type is None:
        return key, None, (), key
    clean_type = _normalize_segment(manual_type)
    if clean_type not in {"bool", "list"}:
        raise InvalidPlaceholderError("Manual typed placeholders support $bool[...] and $list[...]")
    raw_options = str(match.group("options") or "")
    options = tuple(option.strip() for option in raw_options.split(";") if option.strip())
    if not options:
        raise InvalidPlaceholderError("Manual typed placeholders require at least one option")
    for option in options:
        if any(char in option for char in "{}[]"):
            raise InvalidPlaceholderError(f"Unsupported manual option: {option!r}")
    typed_segment = f"{key}${clean_type}[{';'.join(options)}]"
    return key, clean_type, options, typed_segment


def parse_placeholder(raw: str) -> PlaceholderToken:
    text = str(raw or "")
    if not text.startswith("{{") or not text.endswith("}}"):
        raise InvalidPlaceholderError(f"Placeholder must use double braces: {raw!r}")
    inner = text[2:-2]
    if not inner:
        raise InvalidPlaceholderError("Placeholder cannot be empty")
    if "{" in inner or "}" in inner:
        raise InvalidPlaceholderError("Nested placeholders are not allowed")

    parts = _split_placeholder_parts(inner)
    if not parts:
        raise InvalidPlaceholderError(f"Malformed placeholder: {raw!r}")

    binding_kind = _normalize_segment(parts[0])
    if binding_kind == "db":
        if len(parts) == 2:
            key = _normalize_segment(parts[1])
            if key != "index":
                raise InvalidPlaceholderError("Database control placeholders support db.index")
            return PlaceholderToken(
                binding_kind="db_index",
                namespace="duplicate",
                key=key,
                canonical_symbol="{{db.index}}",
            )
        if _normalize_segment(parts[1]) == "index":
            raise InvalidPlaceholderError("Database control placeholders support db.index")
        db_parts, indexed = _consume_optional_indexed_suffix(
            tuple(parts[1:]),
            expected_part_count=2,
            error_message="Database placeholders must use db.namespace.key or db.namespace.key.indexed",
        )
        namespace = _normalize_segment(db_parts[0])
        key = _normalize_segment(db_parts[1])
        if namespace == "custom" and not re.fullmatch(r"cf_\d+", key):
            raise InvalidPlaceholderError("Custom database placeholders must use cf_<id>")
        suffix = ".indexed" if indexed else ""
        canonical = f"{{{{db.{namespace}.{key}{suffix}}}}}"
        return PlaceholderToken(
            binding_kind="db",
            namespace=namespace,
            key=key,
            canonical_symbol=canonical,
            indexed=indexed,
        )

    if binding_kind == "manual":
        manual_parts, indexed = _consume_optional_indexed_suffix(
            tuple(parts[1:]),
            expected_part_count=1,
            error_message=(
                "Manual placeholders must use manual.key, manual.key.indexed, "
                "manual.key$type[option;option], or manual.key$type[option;option].indexed"
            ),
        )
        key, manual_type, manual_options, canonical_key = _parse_manual_segment(manual_parts[0])
        suffix = ".indexed" if indexed else ""
        canonical = f"{{{{manual.{canonical_key}{suffix}}}}}"
        return PlaceholderToken(
            binding_kind="manual",
            namespace=None,
            key=key,
            canonical_symbol=canonical,
            indexed=indexed,
            manual_type=manual_type,
            manual_options=manual_options,
        )

    if binding_kind == "current":
        current_parts, indexed = _consume_optional_indexed_suffix(
            tuple(parts[1:]),
            expected_part_count=1,
            error_message="Current placeholders must use current.key or current.key.indexed",
        )
        key = _normalize_segment(current_parts[0])
        if key != "year":
            raise InvalidPlaceholderError("Current placeholders currently support current.year")
        suffix = ".indexed" if indexed else ""
        canonical = f"{{{{current.{key}{suffix}}}}}"
        return PlaceholderToken(
            binding_kind="current",
            namespace=None,
            key=key,
            canonical_symbol=canonical,
            indexed=indexed,
        )

    if binding_kind == "page":
        page_parts, indexed = _consume_optional_indexed_suffix(
            tuple(parts[1:]),
            expected_part_count=1,
            error_message="Page placeholders must use page.key or page.key.indexed",
        )
        key = _normalize_segment(page_parts[0])
        if key not in {"index", "total"}:
            raise InvalidPlaceholderError("Page placeholders support page.index and page.total")
        suffix = ".indexed" if indexed else ""
        canonical = f"{{{{page.{key}{suffix}}}}}"
        return PlaceholderToken(
            binding_kind="page",
            namespace=None,
            key=key,
            canonical_symbol=canonical,
            indexed=indexed,
        )

    if binding_kind == "custom":
        custom_parts, indexed = _consume_optional_indexed_suffix(
            tuple(parts[1:]),
            expected_part_count=1,
            error_message="Custom placeholders must use custom.key or custom.key.indexed",
        )
        key = _normalize_segment(custom_parts[0])
        if key != "index":
            raise InvalidPlaceholderError("Custom placeholders currently support custom.index")
        suffix = ".indexed" if indexed else ""
        canonical = f"{{{{custom.{key}{suffix}}}}}"
        return PlaceholderToken(
            binding_kind="custom",
            namespace=None,
            key=key,
            canonical_symbol=canonical,
            indexed=indexed,
        )

    if binding_kind == "duplicate":
        duplicate_parts, indexed = _consume_optional_indexed_suffix(
            tuple(parts[1:]),
            expected_part_count=1,
            error_message="Duplicate placeholders must use duplicate.key or duplicate.key.indexed",
        )
        key = _normalize_segment(duplicate_parts[0])
        if key not in {"start", "end", "number"}:
            raise InvalidPlaceholderError(
                "Duplicate placeholders support duplicate.start, duplicate.end, and duplicate.number"
            )
        suffix = ".indexed" if indexed else ""
        canonical = f"{{{{duplicate.{key}{suffix}}}}}"
        return PlaceholderToken(
            binding_kind="duplicate",
            namespace=None,
            key=key,
            canonical_symbol=canonical,
            indexed=indexed,
        )

    raise InvalidPlaceholderError(f"Unsupported placeholder binding kind: {binding_kind}")


def base_symbol_for_indexed_placeholder(raw: str) -> str | None:
    token = parse_placeholder(raw)
    if not token.indexed:
        return None
    if token.binding_kind == "db" and token.namespace is not None:
        return f"{{{{db.{token.namespace}.{token.key}}}}}"
    if token.binding_kind == "manual":
        typed_suffix = (
            f"${token.manual_type}[{';'.join(token.manual_options)}]" if token.manual_type else ""
        )
        return f"{{{{manual.{token.key}{typed_suffix}}}}}"
    if token.binding_kind in {"current", "page", "custom", "duplicate"}:
        return f"{{{{{token.binding_kind}.{token.key}}}}}"
    return None


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
