"""Context-aware QSS parsing, completion, and editor integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel, QTextCursor
from PySide6.QtWidgets import QCompleter, QPlainTextEdit

from .qss_reference import QssReferenceEntry

COMMON_QSS_PROPERTIES: tuple[str, ...] = (
    "background",
    "background-color",
    "border",
    "border-radius",
    "color",
    "font-size",
    "font-weight",
    "image",
    "margin",
    "margin-left",
    "margin-right",
    "margin-top",
    "margin-bottom",
    "max-height",
    "max-width",
    "min-height",
    "min-width",
    "outline",
    "padding",
    "padding-left",
    "padding-right",
    "padding-top",
    "padding-bottom",
    "selection-background-color",
    "selection-color",
    "spacing",
)

WIDGET_QSS_METADATA: dict[str, dict[str, object]] = {
    "QWidget": {
        "pseudo_states": ("disabled", "focus", "hover"),
        "properties": (
            "background-color",
            "color",
            "border",
            "border-radius",
            "padding",
            "margin",
        ),
        "template_properties": ("background-color", "color"),
    },
    "QMainWindow": {
        "properties": ("background-color", "color"),
        "template_properties": ("background-color", "color"),
    },
    "QDialog": {
        "properties": ("background-color", "color"),
        "template_properties": ("background-color", "color"),
    },
    "QLabel": {
        "pseudo_states": ("disabled",),
        "properties": ("color", "font-size", "font-weight", "padding"),
        "template_properties": ("color", "font-weight"),
    },
    "QPushButton": {
        "pseudo_states": ("default", "disabled", "flat", "hover", "pressed", "checked"),
        "properties": (
            "background-color",
            "color",
            "border",
            "border-radius",
            "padding",
            "min-height",
            "min-width",
            "font-weight",
        ),
        "template_properties": ("background-color", "color", "border-radius"),
    },
    "QToolButton": {
        "pseudo_states": ("disabled", "hover", "pressed", "checked"),
        "properties": (
            "background-color",
            "color",
            "border",
            "border-radius",
            "padding",
        ),
        "template_properties": ("background-color", "color"),
    },
    "QLineEdit": {
        "pseudo_states": ("disabled", "focus", "hover"),
        "properties": (
            "background-color",
            "color",
            "border",
            "border-radius",
            "padding",
            "selection-background-color",
            "selection-color",
        ),
        "template_properties": ("background-color", "color", "border"),
    },
    "QPlainTextEdit": {
        "pseudo_states": ("disabled", "focus"),
        "properties": (
            "background-color",
            "color",
            "border",
            "padding",
            "selection-background-color",
            "selection-color",
        ),
        "template_properties": ("background-color", "color"),
    },
    "QComboBox": {
        "pseudo_states": ("disabled", "editable", "hover", "on"),
        "subcontrols": ("drop-down", "down-arrow"),
        "properties": (
            "background-color",
            "color",
            "border",
            "border-radius",
            "padding",
            "min-width",
        ),
        "template_properties": ("background-color", "color", "border"),
    },
    "QCheckBox": {
        "pseudo_states": ("checked", "disabled", "hover"),
        "subcontrols": ("indicator",),
        "properties": ("color", "spacing", "padding"),
        "template_properties": ("color", "spacing"),
    },
    "QRadioButton": {
        "pseudo_states": ("checked", "disabled", "hover"),
        "subcontrols": ("indicator",),
        "properties": ("color", "spacing", "padding"),
        "template_properties": ("color", "spacing"),
    },
    "QTableWidget": {
        "pseudo_states": ("disabled",),
        "properties": (
            "background-color",
            "color",
            "gridline-color",
            "selection-background-color",
            "selection-color",
        ),
        "template_properties": ("background-color", "color", "gridline-color"),
    },
    "QTableView": {
        "pseudo_states": ("disabled",),
        "properties": (
            "background-color",
            "color",
            "gridline-color",
            "selection-background-color",
            "selection-color",
        ),
        "template_properties": ("background-color", "color", "gridline-color"),
    },
    "QHeaderView": {
        "subcontrols": ("section",),
        "properties": ("background-color", "color", "padding", "border"),
        "template_properties": ("background-color", "color"),
    },
    "QTabWidget": {
        "subcontrols": ("pane", "tab-bar"),
        "properties": ("background-color", "color"),
        "template_properties": ("background-color", "color"),
    },
    "QTabBar": {
        "subcontrols": ("tab",),
        "pseudo_states": ("disabled", "hover", "selected"),
        "properties": ("background-color", "color", "padding", "margin"),
        "template_properties": ("background-color", "color", "padding"),
    },
    "QScrollArea": {
        "properties": ("background-color", "border"),
        "template_properties": ("background-color", "border"),
    },
    "QScrollBar": {
        "pseudo_states": ("disabled", "horizontal", "vertical"),
        "subcontrols": ("add-line", "sub-line", "add-page", "sub-page", "handle"),
        "properties": ("background-color", "border", "margin", "width", "height"),
        "template_properties": ("background-color", "width"),
    },
    "QMenuBar": {
        "pseudo_states": ("disabled",),
        "subcontrols": ("item",),
        "properties": ("background-color", "color", "padding"),
        "template_properties": ("background-color", "color"),
    },
    "QMenu": {
        "subcontrols": ("item", "separator", "icon", "scroller"),
        "pseudo_states": ("disabled", "selected"),
        "properties": ("background-color", "color", "padding", "border"),
        "template_properties": ("background-color", "color", "padding"),
    },
    "QGroupBox": {
        "subcontrols": ("title",),
        "properties": ("background-color", "color", "border", "margin-top", "padding-top"),
        "template_properties": ("border", "margin-top"),
    },
    "QDockWidget": {
        "subcontrols": ("title",),
        "properties": ("background-color", "color", "border"),
        "template_properties": ("background-color", "color"),
    },
    "QToolBar": {
        "properties": ("background-color", "spacing", "padding", "border"),
        "template_properties": ("background-color", "spacing"),
    },
    "QListWidget": {
        "properties": (
            "background-color",
            "color",
            "selection-background-color",
            "selection-color",
        ),
        "template_properties": ("background-color", "color"),
    },
}

SUBCONTROL_PSEUDO_STATES: dict[tuple[str, str], tuple[str, ...]] = {
    ("QScrollBar", "handle"): ("horizontal", "vertical", "hover", "pressed", "disabled"),
    ("QScrollBar", "add-line"): ("horizontal", "vertical", "hover", "pressed"),
    ("QScrollBar", "sub-line"): ("horizontal", "vertical", "hover", "pressed"),
    ("QTabBar", "tab"): ("disabled", "hover", "selected"),
    ("QComboBox", "drop-down"): ("disabled", "hover", "on"),
    ("QComboBox", "down-arrow"): ("disabled", "hover"),
    ("QCheckBox", "indicator"): ("checked", "disabled", "hover"),
    ("QRadioButton", "indicator"): ("checked", "disabled", "hover"),
}

PROPERTY_VALUE_SUGGESTIONS: dict[str, tuple[str, ...]] = {
    "background": ("transparent", "palette(window)", "#RRGGBB"),
    "background-color": ("transparent", "palette(window)", "palette(button)", "#RRGGBB"),
    "border": ("1px solid #RRGGBB", "none"),
    "border-radius": ("4px", "8px", "0px"),
    "color": ("palette(window-text)", "palette(button-text)", "#RRGGBB"),
    "font-size": ("10pt", "12pt", "14pt"),
    "font-weight": ("400", "500", "600", "bold"),
    "height": ("18px", "24px", "32px"),
    "image": ("url(path/to/image.png)", "none"),
    "margin": ("0px", "4px", "8px"),
    "margin-top": ("0px", "4px", "8px"),
    "min-height": ("18px", "24px", "32px"),
    "min-width": ("80px", "120px", "180px"),
    "padding": ("4px", "6px 10px", "8px"),
    "padding-left": ("4px", "8px", "12px"),
    "padding-right": ("4px", "8px", "12px"),
    "selection-background-color": ("palette(highlight)", "#RRGGBB"),
    "selection-color": ("palette(highlighted-text)", "#RRGGBB"),
    "spacing": ("4px", "6px", "8px"),
    "width": ("12px", "18px", "24px"),
}

PROPERTY_TEMPLATES: dict[str, str] = {
    "background": "background: ;",
    "background-color": "background-color: ;",
    "border": "border: 1px solid #RRGGBB;",
    "border-radius": "border-radius: 6px;",
    "color": "color: ;",
    "font-size": "font-size: 10pt;",
    "font-weight": "font-weight: 600;",
    "height": "height: 24px;",
    "image": "image: url(path/to/image.png);",
    "margin": "margin: 0px;",
    "margin-top": "margin-top: 0px;",
    "min-height": "min-height: 24px;",
    "min-width": "min-width: 120px;",
    "padding": "padding: 6px 10px;",
    "padding-left": "padding-left: 8px;",
    "padding-right": "padding-right: 8px;",
    "selection-background-color": "selection-background-color: ;",
    "selection-color": "selection-color: ;",
    "spacing": "spacing: 6px;",
    "width": "width: 18px;",
}

PLACEHOLDER_VALUE_PROPERTIES = {
    "background",
    "background-color",
    "color",
    "selection-background-color",
    "selection-color",
}
IDENTIFIER_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
SELECTOR_DELIMITERS = " \t\r\n,{>+~"


@dataclass(frozen=True, slots=True)
class QssCompletionEdit:
    replace_start: int
    replace_end: int
    text: str
    cursor_offset: int | None = None


@dataclass(frozen=True, slots=True)
class QssCompoundSelector:
    raw_text: str
    widget_class: str = ""
    object_name: str = ""
    subcontrol: str = ""
    pseudo_states: tuple[str, ...] = ()
    valid: bool = True
    pending_part: str = ""


@dataclass(frozen=True, slots=True)
class QssContext:
    mode: str
    cursor_position: int
    fragment_start: int
    fragment_end: int
    fragment_text: str
    selector_start: int
    selector_end: int
    selector_text: str
    compound_start: int
    compound_end: int
    compound_text: str
    compound_parts: QssCompoundSelector
    active_widget_class: str | None = None
    active_selector_text: str = ""
    current_property_name: str = ""
    indent: str = ""


@dataclass(frozen=True, slots=True)
class QssCompletionItem:
    label: str
    detail: str
    preview: str
    kind: str
    insertion_mode: str
    value: str
    widget_class: str | None = None
    object_name: str | None = None
    subcontrol: str | None = None
    pseudo_state: str | None = None
    property_name: str | None = None
    sort_priority: int = 100


@dataclass(slots=True)
class QssTargetIndex:
    widget_types: tuple[str, ...] = ()
    object_names_by_widget: dict[str, tuple[str, ...]] = field(default_factory=dict)
    typed_object_selectors: tuple[str, ...] = ()
    role_selectors: tuple[str, ...] = ()
    example_selectors: tuple[str, ...] = ()


def _is_identifier_char(char: str) -> bool:
    return char in IDENTIFIER_CHARS


def _scan_to_cursor(text: str, cursor_position: int) -> tuple[bool, list[tuple[int, str]], int]:
    in_comment = False
    in_quote = ""
    last_close = -1
    block_stack: list[tuple[int, str]] = []
    index = 0
    while index < cursor_position:
        char = text[index]
        pair = text[index : index + 2]
        if in_comment:
            if pair == "*/":
                in_comment = False
                index += 2
                continue
            index += 1
            continue
        if in_quote:
            if char == "\\":
                index += 2
                continue
            if char == in_quote:
                in_quote = ""
            index += 1
            continue
        if pair == "/*":
            in_comment = True
            index += 2
            continue
        if char in {"'", '"'}:
            in_quote = char
            index += 1
            continue
        if char == "{":
            start = text.rfind("}", 0, index) + 1
            selector_text = text[start:index].strip()
            block_stack.append((index, selector_text))
        elif char == "}":
            if block_stack:
                block_stack.pop()
            last_close = index
        index += 1
    return in_comment, block_stack, last_close


def _parse_compound_selector(text: str) -> QssCompoundSelector:
    raw = "".join(text.split())
    if not raw:
        return QssCompoundSelector(raw_text=text, valid=True)

    index = 0
    widget_class = ""
    object_name = ""
    subcontrol = ""
    pseudo_states: list[str] = []
    pending_part = ""

    if raw[index] == "#":
        pending_part = "object_name"
    elif raw[index] == "[":
        return QssCompoundSelector(raw_text=text, valid=False)
    else:
        start = index
        if raw[index].isalpha() or raw[index] == "*":
            index += 1
            while index < len(raw) and _is_identifier_char(raw[index]):
                index += 1
            widget_class = raw[start:index]
        else:
            return QssCompoundSelector(raw_text=text, valid=False)

    if index < len(raw) and raw[index] == "#":
        start = index
        index += 1
        while index < len(raw) and _is_identifier_char(raw[index]):
            index += 1
        object_name = raw[start:index]
        if object_name == "#" and index == len(raw):
            pending_part = "object_name"

    if raw[index : index + 2] == "::":
        index += 2
        start = index
        while index < len(raw) and _is_identifier_char(raw[index]):
            index += 1
        subcontrol = raw[start:index]
        if not subcontrol and index == len(raw):
            pending_part = "subcontrol"

    while index < len(raw):
        if raw[index : index + 2] == "::":
            return QssCompoundSelector(raw_text=text, valid=False)
        if raw[index] != ":":
            return QssCompoundSelector(raw_text=text, valid=False)
        index += 1
        start = index
        while index < len(raw) and _is_identifier_char(raw[index]):
            index += 1
        state = raw[start:index]
        if not state and index == len(raw):
            pending_part = "pseudo_state"
            break
        if not state:
            return QssCompoundSelector(raw_text=text, valid=False)
        pseudo_states.append(state)

    return QssCompoundSelector(
        raw_text=text,
        widget_class=widget_class,
        object_name=object_name,
        subcontrol=subcontrol,
        pseudo_states=tuple(pseudo_states),
        valid=True,
        pending_part=pending_part,
    )


def _compose_compound_selector(parts: QssCompoundSelector) -> str:
    return (
        f"{parts.widget_class}{parts.object_name}"
        f"{f'::{parts.subcontrol}' if parts.subcontrol else ''}"
        f"{''.join(f':{state}' for state in parts.pseudo_states)}"
    )


def _last_compound_widget(selector_text: str) -> str:
    selector = (selector_text or "").strip()
    if not selector:
        return ""
    candidate = selector.split(",")[-1].strip()
    for delimiter in (">", "+", "~"):
        candidate = candidate.split(delimiter)[-1].strip()
    candidate = candidate.split()[-1] if candidate.split() else candidate
    return _parse_compound_selector(candidate).widget_class


def _fragment_range(
    text: str,
    cursor_position: int,
    *,
    delimiters: str,
) -> tuple[int, int]:
    start = cursor_position
    while start > 0 and text[start - 1] not in delimiters:
        start -= 1
    end = cursor_position
    while end < len(text) and text[end] not in delimiters:
        end += 1
    return start, end


def parse_qss_context(text: str, cursor_position: int) -> QssContext:
    """Return the current QSS editing context at the cursor position."""
    in_comment, block_stack, last_close = _scan_to_cursor(text, cursor_position)
    if in_comment:
        return QssContext(
            mode="comment",
            cursor_position=cursor_position,
            fragment_start=cursor_position,
            fragment_end=cursor_position,
            fragment_text="",
            selector_start=cursor_position,
            selector_end=cursor_position,
            selector_text="",
            compound_start=cursor_position,
            compound_end=cursor_position,
            compound_text="",
            compound_parts=QssCompoundSelector(raw_text=""),
        )

    if block_stack:
        brace_index, selector_text = block_stack[-1]
        body_start = brace_index + 1
        statement_start = max(
            body_start,
            text.rfind("{", body_start, cursor_position) + 1,
            text.rfind(";", body_start, cursor_position) + 1,
        )
        line_start = max(
            statement_start,
            text.rfind("\n", statement_start, cursor_position) + 1,
            text.rfind("\r", statement_start, cursor_position) + 1,
        )
        statement_text = text[line_start:cursor_position]
        indent = statement_text[: len(statement_text) - len(statement_text.lstrip(" \t"))]
        if ":" in statement_text:
            colon_offset = statement_text.rfind(":")
            property_name = statement_text[:colon_offset].strip()
            fragment_start, fragment_end = _fragment_range(
                text,
                cursor_position,
                delimiters=" \t\r\n:;{},()",
            )
            return QssContext(
                mode="property_value",
                cursor_position=cursor_position,
                fragment_start=fragment_start,
                fragment_end=fragment_end,
                fragment_text=text[fragment_start:cursor_position],
                selector_start=body_start,
                selector_end=cursor_position,
                selector_text=selector_text,
                compound_start=fragment_start,
                compound_end=fragment_end,
                compound_text=text[fragment_start:fragment_end],
                compound_parts=QssCompoundSelector(raw_text=""),
                active_widget_class=_last_compound_widget(selector_text) or None,
                active_selector_text=selector_text,
                current_property_name=property_name,
                indent=indent,
            )

        fragment_start, fragment_end = _fragment_range(
            text,
            cursor_position,
            delimiters=" \t\r\n;{}",
        )
        return QssContext(
            mode="property_name",
            cursor_position=cursor_position,
            fragment_start=fragment_start,
            fragment_end=fragment_end,
            fragment_text=text[fragment_start:cursor_position],
            selector_start=body_start,
            selector_end=cursor_position,
            selector_text=selector_text,
            compound_start=fragment_start,
            compound_end=fragment_end,
            compound_text=text[fragment_start:fragment_end],
            compound_parts=QssCompoundSelector(raw_text=""),
            active_widget_class=_last_compound_widget(selector_text) or None,
            active_selector_text=selector_text,
            indent=indent,
        )

    selector_start = last_close + 1
    fragment_start, fragment_end = _fragment_range(
        text,
        cursor_position,
        delimiters=SELECTOR_DELIMITERS,
    )
    selector_text = text[selector_start:cursor_position]
    compound_text = text[fragment_start:fragment_end]
    compound_parts = _parse_compound_selector(compound_text or text[fragment_start:cursor_position])
    return QssContext(
        mode="selector",
        cursor_position=cursor_position,
        fragment_start=fragment_start,
        fragment_end=fragment_end,
        fragment_text=text[fragment_start:cursor_position],
        selector_start=selector_start,
        selector_end=cursor_position,
        selector_text=selector_text,
        compound_start=fragment_start,
        compound_end=fragment_end,
        compound_text=compound_text,
        compound_parts=compound_parts,
        active_widget_class=compound_parts.widget_class or None,
    )


def build_qss_target_index(entries: Iterable[QssReferenceEntry]) -> QssTargetIndex:
    """Build a cached lookup structure for widget-specific selector suggestions."""
    widget_types: set[str] = set()
    object_names_by_widget: dict[str, set[str]] = {}
    typed_object_selectors: set[str] = set()
    role_selectors: set[str] = set()
    example_selectors: set[str] = set()

    for entry in entries:
        if entry.widget_class:
            widget_types.add(entry.widget_class)
        if entry.selector_kind == "object_name" and entry.widget_class:
            object_names_by_widget.setdefault(entry.widget_class, set()).add(entry.selector)
        elif entry.selector_kind == "typed_object":
            typed_object_selectors.add(entry.selector)
        elif entry.selector_kind in {"role_property", "typed_role"}:
            role_selectors.add(entry.selector)
        elif entry.selector_kind == "example":
            example_selectors.add(entry.selector)

    return QssTargetIndex(
        widget_types=tuple(sorted(widget_types)),
        object_names_by_widget={
            widget_class: tuple(sorted(values))
            for widget_class, values in sorted(object_names_by_widget.items())
        },
        typed_object_selectors=tuple(sorted(typed_object_selectors)),
        role_selectors=tuple(sorted(role_selectors)),
        example_selectors=tuple(sorted(example_selectors)),
    )


def _matching_candidates(values: Iterable[str], prefix: str) -> list[str]:
    clean_prefix = (prefix or "").strip().lower()
    matches = []
    for value in values:
        lowered = value.lower()
        if not clean_prefix or lowered.startswith(clean_prefix) or clean_prefix in lowered:
            matches.append(value)
    return sorted(matches, key=str.lower)


def _known_widget_class(widget_class: str) -> bool:
    return widget_class in WIDGET_QSS_METADATA


def _known_object_name(widget_class: str, object_name: str, index: QssTargetIndex) -> bool:
    return object_name in index.object_names_by_widget.get(widget_class, ())


def _known_subcontrol(widget_class: str, subcontrol: str) -> bool:
    return subcontrol in _available_subcontrols(widget_class)


def _known_pseudo_states(widget_class: str, subcontrol: str, pseudo_states: Iterable[str]) -> bool:
    available = set(_available_pseudo_states(widget_class, subcontrol))
    return all(state in available for state in pseudo_states)


def _widget_metadata(widget_class: str | None) -> dict[str, object]:
    return WIDGET_QSS_METADATA.get(widget_class or "", WIDGET_QSS_METADATA.get("QWidget", {}))


def _available_pseudo_states(widget_class: str | None, subcontrol: str = "") -> tuple[str, ...]:
    if widget_class and subcontrol:
        states = SUBCONTROL_PSEUDO_STATES.get((widget_class, subcontrol))
        if states:
            return states
    metadata = _widget_metadata(widget_class)
    return tuple(metadata.get("pseudo_states", ()))


def _available_subcontrols(widget_class: str | None) -> tuple[str, ...]:
    metadata = _widget_metadata(widget_class)
    return tuple(metadata.get("subcontrols", ()))


def _available_properties(widget_class: str | None, subcontrol: str = "") -> tuple[str, ...]:
    metadata = _widget_metadata(widget_class)
    properties = set(COMMON_QSS_PROPERTIES)
    properties.update(metadata.get("properties", ()))
    if subcontrol:
        properties.update({"background-color", "border", "border-radius", "padding"})
        if subcontrol == "handle":
            properties.update({"min-height", "min-width"})
    return tuple(sorted(properties))


def _template_properties(widget_class: str | None, subcontrol: str = "") -> tuple[str, ...]:
    metadata = _widget_metadata(widget_class)
    properties = tuple(metadata.get("template_properties", ("background-color",)))
    if subcontrol == "handle":
        return ("min-height", "background-color", "border-radius")
    return properties or ("background-color",)


def _property_template(property_name: str) -> tuple[str, int]:
    text = PROPERTY_TEMPLATES.get(property_name, f"{property_name}: ;")
    cursor_offset = text.find(";")
    if property_name in PLACEHOLDER_VALUE_PROPERTIES:
        cursor_offset = text.find(":") + 2
    if cursor_offset < 0:
        cursor_offset = len(text)
    return text, cursor_offset


def _rule_template(
    selector_text: str, widget_class: str | None, subcontrol: str = ""
) -> tuple[str, int]:
    lines = [selector_text + " {"]
    current_offset = len(lines[0]) + 1
    target_offset = current_offset
    template_properties = _template_properties(widget_class, subcontrol)
    for index, property_name in enumerate(template_properties[:2]):
        property_line, value_offset = _property_template(property_name)
        indented = f"    {property_line}"
        if index == 0:
            target_offset = current_offset + 4 + value_offset
        lines.append(indented)
        current_offset += len(indented) + 1
    lines.append("}")
    return "\n".join(lines), target_offset


def _replace_range(
    text: str, start: int, end: int, replacement: str, cursor_offset: int | None
) -> QssCompletionEdit:
    return QssCompletionEdit(
        replace_start=start,
        replace_end=end,
        text=replacement,
        cursor_offset=cursor_offset if cursor_offset is not None else len(replacement),
    )


def _selector_lead_text(context: QssContext) -> str:
    offset = max(0, context.compound_start - context.selector_start)
    return context.selector_text[:offset]


def _unique_items(items: Iterable[QssCompletionItem]) -> list[QssCompletionItem]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[QssCompletionItem] = []
    for item in sorted(
        items, key=lambda entry: (entry.sort_priority, entry.label.lower(), entry.preview.lower())
    ):
        key = (item.kind, item.label, item.preview)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


class QssCompletionEngine:
    """Generate syntax-aware QSS completion items and safe insertion edits."""

    def __init__(self):
        self._reference_entries: list[QssReferenceEntry] = []
        self._target_index = QssTargetIndex()

    def set_reference_entries(self, entries: Iterable[QssReferenceEntry]) -> None:
        self._reference_entries = list(entries)
        self._target_index = build_qss_target_index(self._reference_entries)

    def context(self, text: str, cursor_position: int) -> QssContext:
        return parse_qss_context(text, cursor_position)

    def completion_items(self, text: str, cursor_position: int) -> list[QssCompletionItem]:
        context = self.context(text, cursor_position)
        if context.mode == "comment":
            return []
        if context.mode == "selector":
            return self._selector_completion_items(context)
        if context.mode == "property_name":
            return self._property_completion_items(context)
        if context.mode == "property_value":
            return self._property_value_completion_items(context)
        return []

    def completion_edit(
        self,
        text: str,
        cursor_position: int,
        item: QssCompletionItem,
    ) -> QssCompletionEdit | None:
        context = self.context(text, cursor_position)
        if context.mode == "comment":
            return None
        if item.insertion_mode == "replace_fragment":
            return _replace_range(
                text,
                context.fragment_start,
                context.fragment_end,
                item.value,
                len(item.value),
            )
        if item.insertion_mode == "insert_property":
            property_line, cursor_offset = _property_template(item.property_name or item.value)
            return _replace_range(
                text,
                context.fragment_start,
                context.fragment_end,
                property_line,
                cursor_offset,
            )
        if item.insertion_mode == "replace_value":
            return _replace_range(
                text,
                context.fragment_start,
                context.fragment_end,
                item.value,
                len(item.value),
            )
        if item.insertion_mode == "compose_selector":
            return self._selector_composition_edit(context, item)
        if item.insertion_mode == "insert_rule_template":
            selector_text = item.value
            template_text, cursor_offset = _rule_template(
                selector_text,
                item.widget_class,
                item.subcontrol or "",
            )
            return _replace_range(
                text,
                context.compound_start,
                context.compound_end,
                template_text,
                cursor_offset,
            )
        return None

    def _selector_completion_items(self, context: QssContext) -> list[QssCompletionItem]:
        items: list[QssCompletionItem] = []
        fragment = (context.fragment_text or "").strip()
        parts = context.compound_parts
        active_widget = parts.widget_class or context.active_widget_class or ""
        selector_lead = _selector_lead_text(context)
        object_known = bool(
            active_widget
            and parts.object_name
            and _known_object_name(active_widget, parts.object_name, self._target_index)
        )
        subcontrol_known = bool(
            active_widget
            and parts.subcontrol
            and _known_subcontrol(active_widget, parts.subcontrol)
        )
        pseudo_known = bool(
            active_widget
            and parts.pseudo_states
            and _known_pseudo_states(active_widget, parts.subcontrol, parts.pseudo_states)
        )

        editing_widget = bool(
            not active_widget
            or (
                fragment
                and "#" not in fragment
                and "::" not in fragment
                and ":" not in fragment
                and not fragment.startswith("[")
                and not (
                    parts.widget_class
                    and _known_widget_class(parts.widget_class)
                    and context.compound_text.strip() == parts.widget_class
                )
            )
        )
        editing_object = bool(
            parts.pending_part == "object_name"
            or ("#" in fragment and not fragment.endswith("}") and not object_known)
        )
        editing_subcontrol = bool(
            parts.pending_part == "subcontrol" or ("::" in fragment and not subcontrol_known)
        )
        editing_pseudo = bool(
            parts.pending_part == "pseudo_state"
            or (":" in fragment and "::" not in fragment and not pseudo_known)
            or (parts.pseudo_states and not pseudo_known)
        )

        if editing_widget:
            for widget_class in _matching_candidates(self._target_index.widget_types, fragment):
                items.append(
                    QssCompletionItem(
                        label=f"{widget_class} [selector]",
                        detail=f"Target all visible {widget_class} widgets.",
                        preview=widget_class,
                        kind="widget_selector",
                        insertion_mode="replace_fragment",
                        value=widget_class,
                        widget_class=widget_class,
                        sort_priority=10,
                    )
                )
                items.append(
                    QssCompletionItem(
                        label=f"{widget_class} {{ … }} [template]",
                        detail="Insert a full rule block for this widget type.",
                        preview=f"{widget_class} {{ … }}",
                        kind="rule_template",
                        insertion_mode="insert_rule_template",
                        value=widget_class,
                        widget_class=widget_class,
                        sort_priority=30,
                    )
                )

        if active_widget:
            if editing_object or not any((editing_widget, editing_subcontrol, editing_pseudo)):
                object_prefix = fragment if editing_object else ""
                for selector in _matching_candidates(
                    self._target_index.object_names_by_widget.get(active_widget, ()),
                    object_prefix,
                ):
                    items.append(
                        QssCompletionItem(
                            label=f"{selector} [append object reference]",
                            detail=f"Append this {active_widget} object name without rewriting the selector.",
                            preview=selector,
                            kind="object_name",
                            insertion_mode="compose_selector",
                            value=selector,
                            widget_class=active_widget,
                            object_name=selector,
                            sort_priority=15,
                        )
                    )
            if editing_subcontrol or (
                not any((editing_widget, editing_object, editing_pseudo)) and not parts.subcontrol
            ):
                subcontrol_prefix = fragment.split("::", 1)[-1] if editing_subcontrol else ""
                for subcontrol in _matching_candidates(
                    _available_subcontrols(active_widget),
                    subcontrol_prefix,
                ):
                    composed = _compose_compound_selector(
                        QssCompoundSelector(
                            raw_text=context.compound_text,
                            widget_class=active_widget,
                            object_name=parts.object_name,
                            subcontrol=subcontrol,
                            pseudo_states=parts.pseudo_states,
                        )
                    )
                    full_selector = f"{selector_lead}{composed}".strip()
                    items.append(
                        QssCompletionItem(
                            label=f"::{subcontrol} [subcontrol]",
                            detail=f"Append the {subcontrol} subcontrol for {active_widget}.",
                            preview=composed,
                            kind="subcontrol",
                            insertion_mode="compose_selector",
                            value=subcontrol,
                            widget_class=active_widget,
                            subcontrol=subcontrol,
                            sort_priority=20,
                        )
                    )
                    items.append(
                        QssCompletionItem(
                            label=f"{full_selector} {{ … }} [template]",
                            detail="Insert a full rule block for this subcontrol.",
                            preview=f"{full_selector} {{ … }}",
                            kind="rule_template",
                            insertion_mode="insert_rule_template",
                            value=full_selector,
                            widget_class=active_widget,
                            subcontrol=subcontrol,
                            sort_priority=40,
                        )
                    )

            if editing_pseudo or not any((editing_widget, editing_object, editing_subcontrol)):
                state_prefix = fragment.rsplit(":", 1)[-1] if editing_pseudo else ""
                for pseudo_state in _matching_candidates(
                    _available_pseudo_states(active_widget, parts.subcontrol),
                    state_prefix,
                ):
                    if pseudo_state in parts.pseudo_states:
                        continue
                    composed_parts = QssCompoundSelector(
                        raw_text=context.compound_text,
                        widget_class=active_widget,
                        object_name=parts.object_name,
                        subcontrol=parts.subcontrol,
                        pseudo_states=(*parts.pseudo_states, pseudo_state),
                    )
                    composed = _compose_compound_selector(composed_parts)
                    full_selector = f"{selector_lead}{composed}".strip()
                    items.append(
                        QssCompletionItem(
                            label=f":{pseudo_state} [append pseudo-state]",
                            detail=f"Append the :{pseudo_state} pseudo-state to the current selector.",
                            preview=composed,
                            kind="pseudo_state",
                            insertion_mode="compose_selector",
                            value=pseudo_state,
                            widget_class=active_widget,
                            pseudo_state=pseudo_state,
                            sort_priority=25,
                        )
                    )
                    items.append(
                        QssCompletionItem(
                            label=f"{full_selector} {{ … }} [template]",
                            detail="Insert a full rule block for this selector variant.",
                            preview=f"{full_selector} {{ … }}",
                            kind="rule_template",
                            insertion_mode="insert_rule_template",
                            value=full_selector,
                            widget_class=active_widget,
                            subcontrol=parts.subcontrol,
                            sort_priority=45,
                        )
                    )

            if active_widget and not any(
                (editing_widget, editing_object, editing_subcontrol, editing_pseudo)
            ):
                current_selector = _compose_compound_selector(parts) or active_widget
                full_selector = f"{selector_lead}{current_selector}".strip()
                items.append(
                    QssCompletionItem(
                        label=f"{full_selector} {{ … }} [template]",
                        detail="Insert a full rule block for the current selector.",
                        preview=f"{full_selector} {{ … }}",
                        kind="rule_template",
                        insertion_mode="insert_rule_template",
                        value=full_selector,
                        widget_class=active_widget,
                        subcontrol=parts.subcontrol,
                        sort_priority=35,
                    )
                )
        else:
            object_prefix = fragment if fragment.startswith("#") else ""
            for selector in _matching_candidates(
                self._target_index.typed_object_selectors, fragment
            ):
                items.append(
                    QssCompletionItem(
                        label=f"{selector} [typed object selector]",
                        detail="Target this named widget directly.",
                        preview=selector,
                        kind="typed_object_selector",
                        insertion_mode="replace_fragment",
                        value=selector,
                        sort_priority=50,
                    )
                )
                items.append(
                    QssCompletionItem(
                        label=f"{selector} {{ … }} [template]",
                        detail="Insert a full rule block for this named widget.",
                        preview=f"{selector} {{ … }}",
                        kind="rule_template",
                        insertion_mode="insert_rule_template",
                        value=selector,
                        widget_class=selector.split("#", 1)[0],
                        sort_priority=60,
                    )
                )
            if object_prefix:
                for widget_class, selectors in self._target_index.object_names_by_widget.items():
                    for selector in _matching_candidates(selectors, object_prefix):
                        items.append(
                            QssCompletionItem(
                                label=f"{selector} [object reference]",
                                detail=f"Object-name reference for {widget_class}.",
                                preview=selector,
                                kind="object_name",
                                insertion_mode="replace_fragment",
                                value=selector,
                                widget_class=widget_class,
                                object_name=selector,
                                sort_priority=55,
                            )
                        )
            for selector in _matching_candidates(self._target_index.role_selectors, fragment):
                items.append(
                    QssCompletionItem(
                        label=f"{selector} [role selector]",
                        detail="Target widgets exposed through an app-defined role property.",
                        preview=selector,
                        kind="role_selector",
                        insertion_mode="replace_fragment",
                        value=selector,
                        sort_priority=70,
                    )
                )
            for selector in _matching_candidates(self._target_index.example_selectors, fragment):
                items.append(
                    QssCompletionItem(
                        label=f"{selector} [example]",
                        detail="Reference selector harvested from the current app surface.",
                        preview=selector,
                        kind="example_selector",
                        insertion_mode="replace_fragment",
                        value=selector,
                        sort_priority=80,
                    )
                )

        return _unique_items(items)

    def _property_completion_items(self, context: QssContext) -> list[QssCompletionItem]:
        active_widget = context.active_widget_class
        prefix = (context.fragment_text or "").strip()
        items = []
        for property_name in _matching_candidates(
            _available_properties(active_widget),
            prefix,
        ):
            line_preview, _cursor_offset = _property_template(property_name)
            items.append(
                QssCompletionItem(
                    label=f"{line_preview} [property]",
                    detail="Insert a complete property line with a value placeholder.",
                    preview=line_preview,
                    kind="property_name",
                    insertion_mode="insert_property",
                    value=property_name,
                    property_name=property_name,
                    widget_class=active_widget,
                    sort_priority=10,
                )
            )
        return _unique_items(items)

    def _property_value_completion_items(self, context: QssContext) -> list[QssCompletionItem]:
        property_name = context.current_property_name
        prefix = (context.fragment_text or "").strip()
        values = PROPERTY_VALUE_SUGGESTIONS.get(property_name, ())
        items = [
            QssCompletionItem(
                label=f"{value} [value]",
                detail=f"Value suggestion for {property_name}.",
                preview=value,
                kind="property_value",
                insertion_mode="replace_value",
                value=value,
                property_name=property_name,
                sort_priority=10,
            )
            for value in _matching_candidates(values, prefix)
        ]
        return _unique_items(items)

    def _selector_composition_edit(
        self,
        context: QssContext,
        item: QssCompletionItem,
    ) -> QssCompletionEdit | None:
        parts = context.compound_parts
        if not parts.valid:
            return _replace_range(
                "",
                context.fragment_start,
                context.fragment_end,
                item.value,
                len(item.value),
            )

        widget_class = parts.widget_class
        object_name = parts.object_name
        subcontrol = parts.subcontrol
        pseudo_states = list(parts.pseudo_states)

        if item.kind == "object_name":
            object_name = item.object_name or item.value
        elif item.kind == "pseudo_state":
            pseudo_state = item.pseudo_state or item.value
            if pseudo_state not in pseudo_states:
                pseudo_states.append(pseudo_state)
        elif item.kind == "subcontrol":
            if not widget_class:
                return None
            subcontrol = item.subcontrol or item.value
        elif item.kind == "widget_selector":
            widget_class = item.widget_class or item.value

        composed = _compose_compound_selector(
            QssCompoundSelector(
                raw_text=context.compound_text,
                widget_class=widget_class,
                object_name=object_name,
                subcontrol=subcontrol,
                pseudo_states=tuple(pseudo_states),
            )
        )
        if not composed:
            return None
        return _replace_range(
            "",
            context.compound_start,
            context.compound_end,
            composed,
            len(composed),
        )


class QssCodeEditor(QPlainTextEdit):
    """QSS editor with syntax-aware selector and property autocomplete."""

    COMPLETION_ROLE = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = QssCompletionEngine()
        self._completion_items: list[QssCompletionItem] = []
        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setWidget(self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self._completer.activated.connect(self._apply_completion_from_index)

    def set_reference_entries(self, entries: Iterable[QssReferenceEntry]) -> None:
        self._engine.set_reference_entries(entries)

    def set_completion_tokens(self, tokens: Iterable[str]) -> None:
        from .qss_reference import QssReferenceEntry

        self.set_reference_entries(
            [
                QssReferenceEntry(
                    category="Compatibility",
                    selector=token,
                    details="Compatibility token.",
                    selector_kind="example",
                )
                for token in tokens
            ]
        )

    def current_context(self) -> QssContext:
        return self._engine.context(self.toPlainText(), self.textCursor().position())

    def current_completion_items(self) -> list[QssCompletionItem]:
        return list(self._completion_items)

    def apply_completion_item(self, item: QssCompletionItem) -> None:
        edit = self._engine.completion_edit(self.toPlainText(), self.textCursor().position(), item)
        if edit is None:
            return
        cursor = self.textCursor()
        cursor.setPosition(edit.replace_start)
        cursor.setPosition(edit.replace_end, QTextCursor.KeepAnchor)
        cursor.insertText(edit.text)
        cursor.setPosition(edit.replace_start + (edit.cursor_offset or len(edit.text)))
        self.setTextCursor(cursor)

    def _apply_completion_from_index(self, index) -> None:
        if isinstance(index, str):
            for row in range(self._model.rowCount()):
                model_index = self._model.index(row, 0)
                item = model_index.data(self.COMPLETION_ROLE)
                if isinstance(item, QssCompletionItem) and item.label == index:
                    self.apply_completion_item(item)
                    return
            return
        if not hasattr(index, "isValid") or not index.isValid():
            return
        item = index.data(self.COMPLETION_ROLE)
        if isinstance(item, QssCompletionItem):
            self.apply_completion_item(item)

    def _refresh_completion_items(self) -> list[QssCompletionItem]:
        self._completion_items = self._engine.completion_items(
            self.toPlainText(),
            self.textCursor().position(),
        )
        self._model.clear()
        for item in self._completion_items:
            model_item = QStandardItem(item.label)
            model_item.setData(item, self.COMPLETION_ROLE)
            model_item.setToolTip(f"{item.detail}\n\nResult:\n{item.preview}")
            self._model.appendRow(model_item)
        return self._completion_items

    def _show_completion_popup(self, *, require_items: bool = True) -> None:
        items = self._refresh_completion_items()
        if require_items and not items:
            self._completer.popup().hide()
            return
        popup = self._completer.popup()
        popup.setCurrentIndex(self._model.index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(max(420, popup.sizeHintForColumn(0) + 28))
        self._completer.complete(rect)

    def _should_autoshow(self, context: QssContext, typed_text: str) -> bool:
        if not typed_text.strip():
            return False
        if context.mode == "selector":
            return len(context.fragment_text.strip()) >= 2 or context.fragment_text.endswith(
                ("#", ":", "::")
            )
        if context.mode == "property_name":
            return len(context.fragment_text.strip()) >= 2
        if context.mode == "property_value":
            return True
        return False

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        popup = self._completer.popup()
        if popup.isVisible() and event.key() in (
            Qt.Key_Enter,
            Qt.Key_Return,
            Qt.Key_Escape,
            Qt.Key_Tab,
            Qt.Key_Backtab,
        ):
            event.ignore()
            return

        ctrl_space = bool(event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Space)
        super().keyPressEvent(event)

        context = self.current_context()
        if ctrl_space:
            self._show_completion_popup(require_items=False)
            return
        if self._should_autoshow(context, event.text()):
            self._show_completion_popup()
        elif popup.isVisible():
            popup.hide()
