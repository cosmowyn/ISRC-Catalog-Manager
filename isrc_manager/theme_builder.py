"""Theme schema, normalization, and stylesheet generation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class ThemeColorFieldSpec:
    key: str
    page: str
    section: str
    label: str
    hint: str
    placeholder: str = "Auto"


@dataclass(frozen=True)
class ThemeMetricFieldSpec:
    key: str
    page: str
    section: str
    label: str
    hint: str
    minimum: int
    maximum: int
    default: int
    suffix: str = ""


THEME_PAGE_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "typography",
        "Typography",
        "Set the base type system used across dialogs, tables, captions, and section headers.",
    ),
    (
        "surfaces",
        "Surfaces",
        "Style the core app canvas, panel chrome, borders, headers, tooltips, and helper text.",
    ),
    (
        "buttons",
        "Buttons",
        "Configure normal, hover, pressed, checked, disabled, and help-button states.",
    ),
    (
        "inputs",
        "Inputs",
        "Customize editors, focus states, placeholders, and checkbox/radio indicators.",
    ),
    (
        "data_views",
        "Data Views",
        "Theme tables, lists, row hover states, selections, scrollbars, and progress bars.",
    ),
    (
        "navigation",
        "Navigation",
        "Control menu bars, menus, tabs, dock titles, headers, and related navigation chrome.",
    ),
    (
        "action_ribbon",
        "Action Ribbon",
        "Theme the action ribbon chrome separately from tabs and the rest of the toolbar stack. Ribbon buttons still use the shared button styling in this pass.",
    ),
    (
        "advanced",
        "Advanced QSS",
        "Use the live selector catalog and code editor only for the remaining edge cases.",
    ),
)


THEME_COLOR_FIELD_SPECS: tuple[ThemeColorFieldSpec, ...] = (
    ThemeColorFieldSpec(
        "window_bg",
        "surfaces",
        "Core Surfaces",
        "Window Background",
        "Base background for the main window, dialogs, menus, and open panels.",
        placeholder="Palette default",
    ),
    ThemeColorFieldSpec(
        "window_fg",
        "surfaces",
        "Core Surfaces",
        "Window Text",
        "Primary foreground used across labels, menus, dialogs, and content areas.",
        placeholder="Palette default",
    ),
    ThemeColorFieldSpec(
        "workspace_bg",
        "surfaces",
        "Core Surfaces",
        "Workspace Canvas",
        "Background used for tab pages, dock content canvases, scrollable form pages, and the empty main workspace area.",
    ),
    ThemeColorFieldSpec(
        "panel_bg",
        "surfaces",
        "Core Surfaces",
        "Panel Background",
        "Background for group boxes, dock content blocks, and cards. Leave empty to derive it from the window background.",
    ),
    ThemeColorFieldSpec(
        "panel_alt_bg",
        "surfaces",
        "Core Surfaces",
        "Panel Alternate Background",
        "Secondary panel shade used for subtle separation, inactive fills, and secondary surfaces.",
    ),
    ThemeColorFieldSpec(
        "border_color",
        "surfaces",
        "Core Surfaces",
        "Border Color",
        "Default border color for frames, groups, docks, and general separators.",
    ),
    ThemeColorFieldSpec(
        "group_title_fg",
        "surfaces",
        "Core Surfaces",
        "Group Title Text",
        "Foreground used for group box titles and other boxed section labels.",
    ),
    ThemeColorFieldSpec(
        "compact_group_bg",
        "surfaces",
        "Core Surfaces",
        "Compact Group Background",
        "Background used for compact grouped control clusters such as inline field frames.",
    ),
    ThemeColorFieldSpec(
        "compact_group_border",
        "surfaces",
        "Core Surfaces",
        "Compact Group Border",
        "Border color used for compact grouped control clusters.",
    ),
    ThemeColorFieldSpec(
        "accent",
        "surfaces",
        "Accent & Selection",
        "Accent",
        "Used for highlights, active emphasis, checked controls, and focus styling.",
        placeholder="Palette highlight",
    ),
    ThemeColorFieldSpec(
        "selection_bg",
        "surfaces",
        "Accent & Selection",
        "Selection Background",
        "Background used for selected rows, highlighted text, and active list items.",
        placeholder="Accent",
    ),
    ThemeColorFieldSpec(
        "selection_fg",
        "surfaces",
        "Accent & Selection",
        "Selection Text",
        "Foreground used on top of the selection background.",
        placeholder="Auto contrast",
    ),
    ThemeColorFieldSpec(
        "secondary_text",
        "surfaces",
        "Supporting Text",
        "Secondary Text",
        "Used for helper copy, metadata, captions, and secondary status text.",
    ),
    ThemeColorFieldSpec(
        "hint_text",
        "surfaces",
        "Supporting Text",
        "Hint Text",
        "Used for hints and instructional notes when you want a softer emphasis than primary content.",
    ),
    ThemeColorFieldSpec(
        "link_color",
        "surfaces",
        "Supporting Text",
        "Link Color",
        "Used for linked text and explicit hyperlink accents where supported.",
    ),
    ThemeColorFieldSpec(
        "tooltip_bg",
        "surfaces",
        "Special Surfaces",
        "Tooltip Background",
        "Background for tooltip popups.",
    ),
    ThemeColorFieldSpec(
        "tooltip_fg",
        "surfaces",
        "Special Surfaces",
        "Tooltip Text",
        "Foreground for tooltip content.",
    ),
    ThemeColorFieldSpec(
        "tooltip_border",
        "surfaces",
        "Special Surfaces",
        "Tooltip Border",
        "Border color for tooltip popups.",
    ),
    ThemeColorFieldSpec(
        "overlay_bg",
        "surfaces",
        "Special Surfaces",
        "Overlay Background",
        "Used for overlay hints and floating hint chips.",
    ),
    ThemeColorFieldSpec(
        "overlay_fg",
        "surfaces",
        "Special Surfaces",
        "Overlay Text",
        "Foreground used on overlay hint backgrounds.",
    ),
    ThemeColorFieldSpec(
        "button_bg",
        "buttons",
        "Normal State",
        "Button Background",
        "Default background for push buttons and standard tool buttons.",
        placeholder="Palette button",
    ),
    ThemeColorFieldSpec(
        "button_fg",
        "buttons",
        "Normal State",
        "Button Text",
        "Default text color for buttons.",
        placeholder="Palette button text",
    ),
    ThemeColorFieldSpec(
        "button_border",
        "buttons",
        "Normal State",
        "Button Border",
        "Default border color for buttons and button-like controls.",
    ),
    ThemeColorFieldSpec(
        "button_hover_bg",
        "buttons",
        "Interactive States",
        "Button Hover Background",
        "Background for buttons while hovered.",
    ),
    ThemeColorFieldSpec(
        "button_hover_fg",
        "buttons",
        "Interactive States",
        "Button Hover Text",
        "Foreground for hovered buttons.",
    ),
    ThemeColorFieldSpec(
        "button_hover_border",
        "buttons",
        "Interactive States",
        "Button Hover Border",
        "Border color for hovered buttons.",
    ),
    ThemeColorFieldSpec(
        "button_pressed_bg",
        "buttons",
        "Interactive States",
        "Button Pressed Background",
        "Background used while buttons are pressed or checked.",
    ),
    ThemeColorFieldSpec(
        "button_pressed_fg",
        "buttons",
        "Interactive States",
        "Button Pressed Text",
        "Foreground used while buttons are pressed or checked.",
    ),
    ThemeColorFieldSpec(
        "button_pressed_border",
        "buttons",
        "Interactive States",
        "Button Pressed Border",
        "Border color while buttons are pressed or checked.",
    ),
    ThemeColorFieldSpec(
        "button_disabled_bg",
        "buttons",
        "Disabled State",
        "Button Disabled Background",
        "Background used for disabled buttons.",
    ),
    ThemeColorFieldSpec(
        "button_disabled_fg",
        "buttons",
        "Disabled State",
        "Button Disabled Text",
        "Foreground used for disabled buttons.",
    ),
    ThemeColorFieldSpec(
        "button_disabled_border",
        "buttons",
        "Disabled State",
        "Button Disabled Border",
        "Border color used for disabled buttons.",
    ),
    ThemeColorFieldSpec(
        "help_button_bg",
        "buttons",
        "Round Help Button",
        "Help Button Background",
        "Default background for the round help buttons used across dialogs and docks.",
    ),
    ThemeColorFieldSpec(
        "help_button_fg",
        "buttons",
        "Round Help Button",
        "Help Button Text",
        "Foreground used for the round help button label.",
    ),
    ThemeColorFieldSpec(
        "help_button_border",
        "buttons",
        "Round Help Button",
        "Help Button Border",
        "Border color for the round help buttons.",
    ),
    ThemeColorFieldSpec(
        "help_button_hover_bg",
        "buttons",
        "Round Help Button",
        "Help Button Hover Background",
        "Hover background for the round help buttons.",
    ),
    ThemeColorFieldSpec(
        "help_button_hover_fg",
        "buttons",
        "Round Help Button",
        "Help Button Hover Text",
        "Hover foreground for the round help buttons.",
    ),
    ThemeColorFieldSpec(
        "help_button_hover_border",
        "buttons",
        "Round Help Button",
        "Help Button Hover Border",
        "Hover border for the round help buttons.",
    ),
    ThemeColorFieldSpec(
        "help_button_pressed_bg",
        "buttons",
        "Round Help Button",
        "Help Button Pressed Background",
        "Pressed background for the round help buttons.",
    ),
    ThemeColorFieldSpec(
        "help_button_pressed_fg",
        "buttons",
        "Round Help Button",
        "Help Button Pressed Text",
        "Pressed foreground for the round help buttons.",
    ),
    ThemeColorFieldSpec(
        "help_button_pressed_border",
        "buttons",
        "Round Help Button",
        "Help Button Pressed Border",
        "Pressed border for the round help buttons.",
    ),
    ThemeColorFieldSpec(
        "help_button_disabled_bg",
        "buttons",
        "Round Help Button",
        "Help Button Disabled Background",
        "Background used when a help button is disabled.",
    ),
    ThemeColorFieldSpec(
        "help_button_disabled_fg",
        "buttons",
        "Round Help Button",
        "Help Button Disabled Text",
        "Foreground used when a help button is disabled.",
    ),
    ThemeColorFieldSpec(
        "help_button_disabled_border",
        "buttons",
        "Round Help Button",
        "Help Button Disabled Border",
        "Border used when a help button is disabled.",
    ),
    ThemeColorFieldSpec(
        "input_bg",
        "inputs",
        "Editors",
        "Input Background",
        "Background for editable controls such as line edits, combo boxes, text edits, and spin boxes.",
        placeholder="Palette base",
    ),
    ThemeColorFieldSpec(
        "input_fg",
        "inputs",
        "Editors",
        "Input Text",
        "Foreground used inside editable controls.",
        placeholder="Palette text",
    ),
    ThemeColorFieldSpec(
        "input_border",
        "inputs",
        "Editors",
        "Input Border",
        "Border color for editable controls.",
    ),
    ThemeColorFieldSpec(
        "input_focus_bg",
        "inputs",
        "Editors",
        "Input Focus Background",
        "Background used while editable controls have focus.",
    ),
    ThemeColorFieldSpec(
        "input_focus_fg",
        "inputs",
        "Editors",
        "Input Focus Text",
        "Foreground used while editable controls have focus.",
    ),
    ThemeColorFieldSpec(
        "input_focus_border",
        "inputs",
        "Editors",
        "Input Focus Border",
        "Border color used while editable controls have focus.",
    ),
    ThemeColorFieldSpec(
        "input_disabled_bg",
        "inputs",
        "Editors",
        "Input Disabled Background",
        "Background used for disabled editors.",
    ),
    ThemeColorFieldSpec(
        "input_disabled_fg",
        "inputs",
        "Editors",
        "Input Disabled Text",
        "Foreground used for disabled editors.",
    ),
    ThemeColorFieldSpec(
        "input_disabled_border",
        "inputs",
        "Editors",
        "Input Disabled Border",
        "Border color used for disabled editors.",
    ),
    ThemeColorFieldSpec(
        "placeholder_fg",
        "inputs",
        "Editors",
        "Placeholder Text",
        "Foreground used for placeholder text inside editors.",
    ),
    ThemeColorFieldSpec(
        "indicator_bg",
        "inputs",
        "Indicators",
        "Indicator Background",
        "Default background for checkbox and radio indicators.",
    ),
    ThemeColorFieldSpec(
        "indicator_border",
        "inputs",
        "Indicators",
        "Indicator Border",
        "Default border for checkbox and radio indicators.",
    ),
    ThemeColorFieldSpec(
        "indicator_checked_bg",
        "inputs",
        "Indicators",
        "Indicator Checked Background",
        "Background for checked checkbox and radio indicators.",
    ),
    ThemeColorFieldSpec(
        "indicator_checked_border",
        "inputs",
        "Indicators",
        "Indicator Checked Border",
        "Border color for checked checkbox and radio indicators.",
    ),
    ThemeColorFieldSpec(
        "indicator_disabled_bg",
        "inputs",
        "Indicators",
        "Indicator Disabled Background",
        "Background used when checkbox and radio indicators are disabled.",
    ),
    ThemeColorFieldSpec(
        "indicator_disabled_border",
        "inputs",
        "Indicators",
        "Indicator Disabled Border",
        "Border used when checkbox and radio indicators are disabled.",
    ),
    ThemeColorFieldSpec(
        "table_bg",
        "data_views",
        "Tables & Lists",
        "Table Background",
        "Background used for tables, lists, browsers, and tree-like data views.",
        placeholder="Palette base",
    ),
    ThemeColorFieldSpec(
        "table_fg",
        "data_views",
        "Tables & Lists",
        "Table Text",
        "Foreground used for tables, lists, browsers, and tree-like data views.",
        placeholder="Palette text",
    ),
    ThemeColorFieldSpec(
        "table_alt_bg",
        "data_views",
        "Tables & Lists",
        "Alternate Row Background",
        "Alternate row color used when views show striped rows.",
    ),
    ThemeColorFieldSpec(
        "table_border",
        "data_views",
        "Tables & Lists",
        "Table Border",
        "Border color used around tables and list surfaces.",
    ),
    ThemeColorFieldSpec(
        "table_grid",
        "data_views",
        "Tables & Lists",
        "Table Grid",
        "Gridline color used inside tables.",
    ),
    ThemeColorFieldSpec(
        "table_hover_bg",
        "data_views",
        "Tables & Lists",
        "Row Hover Background",
        "Hover background used for table and list items.",
    ),
    ThemeColorFieldSpec(
        "scrollbar_bg",
        "data_views",
        "Scrollbars & Progress",
        "Scrollbar Background",
        "Track background for scrollbars.",
    ),
    ThemeColorFieldSpec(
        "scrollbar_handle_bg",
        "data_views",
        "Scrollbars & Progress",
        "Scrollbar Handle",
        "Default handle color for scrollbars.",
    ),
    ThemeColorFieldSpec(
        "scrollbar_handle_hover_bg",
        "data_views",
        "Scrollbars & Progress",
        "Scrollbar Handle Hover",
        "Hover color for scrollbar handles.",
    ),
    ThemeColorFieldSpec(
        "progress_bg",
        "data_views",
        "Scrollbars & Progress",
        "Progress Background",
        "Background track for progress bars.",
    ),
    ThemeColorFieldSpec(
        "progress_chunk_bg",
        "data_views",
        "Scrollbars & Progress",
        "Progress Fill",
        "Fill color for progress bars.",
    ),
    ThemeColorFieldSpec(
        "progress_fg",
        "data_views",
        "Scrollbars & Progress",
        "Progress Text",
        "Foreground used for progress bar labels and percentages.",
    ),
    ThemeColorFieldSpec(
        "progress_border",
        "data_views",
        "Scrollbars & Progress",
        "Progress Border",
        "Border color used around progress bars.",
    ),
    ThemeColorFieldSpec(
        "menu_bg",
        "navigation",
        "Menus",
        "Menu Background",
        "Background used for menus and dropdown popups.",
    ),
    ThemeColorFieldSpec(
        "menu_fg",
        "navigation",
        "Menus",
        "Menu Text",
        "Foreground used for menu items and popup entries.",
    ),
    ThemeColorFieldSpec(
        "menu_border",
        "navigation",
        "Menus",
        "Menu Border",
        "Border color for menu popups.",
    ),
    ThemeColorFieldSpec(
        "menu_selected_bg",
        "navigation",
        "Menus",
        "Menu Selected Background",
        "Background used for selected menu and menubar items.",
    ),
    ThemeColorFieldSpec(
        "menu_selected_fg",
        "navigation",
        "Menus",
        "Menu Selected Text",
        "Foreground used for selected menu and menubar items.",
    ),
    ThemeColorFieldSpec(
        "header_bg",
        "navigation",
        "Headers & Dock Titles",
        "Header Background",
        "Background used for dock titles, table headers, and header-like chrome.",
    ),
    ThemeColorFieldSpec(
        "header_fg",
        "navigation",
        "Headers & Dock Titles",
        "Header Text",
        "Foreground used for dock titles, table headers, and header-like chrome.",
    ),
    ThemeColorFieldSpec(
        "header_border",
        "navigation",
        "Headers & Dock Titles",
        "Header Border",
        "Border color used for dock titles, table headers, and header-like chrome.",
    ),
    ThemeColorFieldSpec(
        "toolbar_bg",
        "navigation",
        "Toolbars & Status",
        "Toolbar Background",
        "Background used for application toolbars and ribbons.",
    ),
    ThemeColorFieldSpec(
        "toolbar_fg",
        "navigation",
        "Toolbars & Status",
        "Toolbar Text",
        "Foreground used on toolbar controls and labels.",
    ),
    ThemeColorFieldSpec(
        "toolbar_border",
        "navigation",
        "Toolbars & Status",
        "Toolbar Border",
        "Border color used around toolbar chrome and separators.",
    ),
    ThemeColorFieldSpec(
        "action_ribbon_bg",
        "action_ribbon",
        "Ribbon Chrome",
        "Ribbon Background",
        "Background used specifically for the action ribbon toolbar.",
        placeholder="Toolbar background",
    ),
    ThemeColorFieldSpec(
        "action_ribbon_fg",
        "action_ribbon",
        "Ribbon Chrome",
        "Ribbon Text",
        "Foreground used on the action ribbon toolbar label and text.",
        placeholder="Toolbar text",
    ),
    ThemeColorFieldSpec(
        "action_ribbon_border",
        "action_ribbon",
        "Ribbon Chrome",
        "Ribbon Border",
        "Border and separator color used around the action ribbon toolbar.",
        placeholder="Toolbar border",
    ),
    ThemeColorFieldSpec(
        "statusbar_bg",
        "navigation",
        "Toolbars & Status",
        "Status Bar Background",
        "Background used for status bars and bottom status strips.",
    ),
    ThemeColorFieldSpec(
        "statusbar_fg",
        "navigation",
        "Toolbars & Status",
        "Status Bar Text",
        "Foreground used inside status bars and bottom status strips.",
    ),
    ThemeColorFieldSpec(
        "statusbar_border",
        "navigation",
        "Toolbars & Status",
        "Status Bar Border",
        "Border color used around status bars and their top edge.",
    ),
    ThemeColorFieldSpec(
        "tab_bg",
        "navigation",
        "Tabs",
        "Tab Background",
        "Background used for unselected tabs.",
    ),
    ThemeColorFieldSpec(
        "tab_fg",
        "navigation",
        "Tabs",
        "Tab Text",
        "Foreground used for unselected tabs.",
    ),
    ThemeColorFieldSpec(
        "tab_border",
        "navigation",
        "Tabs",
        "Tab Border",
        "Border color used for tabs.",
    ),
    ThemeColorFieldSpec(
        "tab_hover_bg",
        "navigation",
        "Tabs",
        "Tab Hover Background",
        "Background used while hovering tabs.",
    ),
    ThemeColorFieldSpec(
        "tab_hover_fg",
        "navigation",
        "Tabs",
        "Tab Hover Text",
        "Foreground used while hovering tabs.",
    ),
    ThemeColorFieldSpec(
        "tab_hover_border",
        "navigation",
        "Tabs",
        "Tab Hover Border",
        "Border color used while hovering tabs.",
    ),
    ThemeColorFieldSpec(
        "tab_selected_bg",
        "navigation",
        "Tabs",
        "Tab Selected Background",
        "Background used for selected tabs.",
    ),
    ThemeColorFieldSpec(
        "tab_selected_fg",
        "navigation",
        "Tabs",
        "Tab Selected Text",
        "Foreground used for selected tabs.",
    ),
    ThemeColorFieldSpec(
        "tab_selected_border",
        "navigation",
        "Tabs",
        "Tab Selected Border",
        "Border color used for selected tabs.",
    ),
    ThemeColorFieldSpec(
        "tab_bar_bg",
        "navigation",
        "Tabs",
        "Tab Bar Background",
        "Background used for the tab strip behind the individual tab buttons.",
    ),
    ThemeColorFieldSpec(
        "tab_pane_bg",
        "navigation",
        "Tabs",
        "Tab Pane Background",
        "Background used behind tab content panes.",
    ),
    ThemeColorFieldSpec(
        "tab_pane_border",
        "navigation",
        "Tabs",
        "Tab Pane Border",
        "Border color used around tab content panes.",
    ),
)


THEME_METRIC_FIELD_SPECS: tuple[ThemeMetricFieldSpec, ...] = (
    ThemeMetricFieldSpec(
        "font_size",
        "typography",
        "Application Type",
        "Base Font Size",
        "Default point size used across the application.",
        8,
        36,
        10,
        " pt",
    ),
    ThemeMetricFieldSpec(
        "dialog_title_font_size",
        "typography",
        "Application Type",
        "Dialog Title Size",
        "Point size used for standard dialog titles.",
        10,
        42,
        18,
        " pt",
    ),
    ThemeMetricFieldSpec(
        "section_title_font_size",
        "typography",
        "Application Type",
        "Section Title Size",
        "Point size used for section titles and prominent inline headings.",
        9,
        32,
        13,
        " pt",
    ),
    ThemeMetricFieldSpec(
        "secondary_text_font_size",
        "typography",
        "Application Type",
        "Secondary Text Size",
        "Point size used for dialog subtitles, metadata, and support text.",
        8,
        28,
        9,
        " pt",
    ),
    ThemeMetricFieldSpec(
        "border_width",
        "surfaces",
        "Geometry",
        "Border Width",
        "Default border width used by themed controls and panels.",
        1,
        6,
        1,
        " px",
    ),
    ThemeMetricFieldSpec(
        "panel_radius",
        "surfaces",
        "Geometry",
        "Panel Radius",
        "Corner radius used for groups, cards, and other panel surfaces.",
        0,
        28,
        8,
        " px",
    ),
    ThemeMetricFieldSpec(
        "button_radius",
        "buttons",
        "Geometry",
        "Button Radius",
        "Corner radius used for push buttons and tool buttons.",
        0,
        28,
        6,
        " px",
    ),
    ThemeMetricFieldSpec(
        "button_padding_v",
        "buttons",
        "Geometry",
        "Button Padding Vertical",
        "Vertical padding used inside buttons.",
        2,
        20,
        6,
        " px",
    ),
    ThemeMetricFieldSpec(
        "button_padding_h",
        "buttons",
        "Geometry",
        "Button Padding Horizontal",
        "Horizontal padding used inside buttons.",
        4,
        40,
        12,
        " px",
    ),
    ThemeMetricFieldSpec(
        "help_button_size",
        "buttons",
        "Geometry",
        "Help Button Size",
        "Width and height used for the round help buttons.",
        18,
        48,
        28,
        " px",
    ),
    ThemeMetricFieldSpec(
        "help_button_radius",
        "buttons",
        "Geometry",
        "Help Button Radius",
        "Corner radius used for the round help buttons.",
        0,
        24,
        14,
        " px",
    ),
    ThemeMetricFieldSpec(
        "input_radius",
        "inputs",
        "Geometry",
        "Input Radius",
        "Corner radius used for editors, combo boxes, and text widgets.",
        0,
        24,
        6,
        " px",
    ),
    ThemeMetricFieldSpec(
        "input_padding_v",
        "inputs",
        "Geometry",
        "Input Padding Vertical",
        "Vertical padding used inside editors and combo boxes.",
        2,
        20,
        4,
        " px",
    ),
    ThemeMetricFieldSpec(
        "input_padding_h",
        "inputs",
        "Geometry",
        "Input Padding Horizontal",
        "Horizontal padding used inside editors and combo boxes.",
        4,
        32,
        6,
        " px",
    ),
    ThemeMetricFieldSpec(
        "indicator_size",
        "inputs",
        "Geometry",
        "Indicator Size",
        "Width and height used for checkbox and radio indicators.",
        10,
        32,
        16,
        " px",
    ),
    ThemeMetricFieldSpec(
        "table_radius",
        "data_views",
        "Geometry",
        "Table Radius",
        "Corner radius used for tables, lists, and browser surfaces.",
        0,
        24,
        6,
        " px",
    ),
    ThemeMetricFieldSpec(
        "scrollbar_thickness",
        "data_views",
        "Geometry",
        "Scrollbar Thickness",
        "Width or height used for themed scrollbars.",
        8,
        28,
        14,
        " px",
    ),
    ThemeMetricFieldSpec(
        "scrollbar_radius",
        "data_views",
        "Geometry",
        "Scrollbar Radius",
        "Corner radius used for scrollbar handles.",
        0,
        18,
        6,
        " px",
    ),
    ThemeMetricFieldSpec(
        "scrollbar_handle_min",
        "data_views",
        "Geometry",
        "Scrollbar Handle Minimum",
        "Minimum length used for scrollbar handles.",
        16,
        80,
        26,
        " px",
    ),
    ThemeMetricFieldSpec(
        "progress_radius",
        "data_views",
        "Geometry",
        "Progress Radius",
        "Corner radius used for progress bars.",
        0,
        24,
        6,
        " px",
    ),
    ThemeMetricFieldSpec(
        "header_padding_v",
        "navigation",
        "Geometry",
        "Header Padding Vertical",
        "Vertical padding used in dock titles and view headers.",
        2,
        24,
        6,
        " px",
    ),
    ThemeMetricFieldSpec(
        "header_padding_h",
        "navigation",
        "Geometry",
        "Header Padding Horizontal",
        "Horizontal padding used in dock titles and view headers.",
        4,
        32,
        8,
        " px",
    ),
    ThemeMetricFieldSpec(
        "tab_radius",
        "navigation",
        "Geometry",
        "Tab Radius",
        "Corner radius used for tabs.",
        0,
        24,
        8,
        " px",
    ),
    ThemeMetricFieldSpec(
        "menu_radius",
        "navigation",
        "Geometry",
        "Menu Radius",
        "Corner radius used for menus and popup surfaces.",
        0,
        24,
        8,
        " px",
    ),
)


def _svg_data_uri(svg_markup: str) -> str:
    return f"data:image/svg+xml;utf8,{quote(svg_markup)}"


def _combo_arrow_data_uri(color: str) -> str:
    svg_markup = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'>"
        f"<path fill='{color}' d='M1.41.59 6 5.17 10.59.59 12 2l-6 6-6-6z'/>"
        "</svg>"
    )
    return _svg_data_uri(svg_markup)


THEME_COLOR_KEYS = tuple(spec.key for spec in THEME_COLOR_FIELD_SPECS)
THEME_METRIC_KEYS = tuple(spec.key for spec in THEME_METRIC_FIELD_SPECS)
THEME_METRIC_SPECS_BY_KEY = {spec.key: spec for spec in THEME_METRIC_FIELD_SPECS}


def _palette_and_font() -> tuple[QPalette, QFont]:
    app = QApplication.instance()
    palette = app.palette() if app is not None else QApplication.palette()
    font = app.font() if app is not None else QFont()
    return palette, font


def shift_color(color_value: str, factor: int) -> str:
    color = QColor(color_value)
    if not color.isValid():
        return color_value
    shifted = color.lighter(factor) if factor >= 100 else color.darker(max(1, 200 - factor))
    return shifted.name().upper()


def color_relative_luminance(color_value: str) -> float:
    color = QColor(color_value)
    if not color.isValid():
        return 0.0

    def _channel(value: float) -> float:
        if value <= 0.03928:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    red = _channel(color.redF())
    green = _channel(color.greenF())
    blue = _channel(color.blueF())
    return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)


def contrast_ratio(fg_value: str, bg_value: str) -> float:
    fg_l = color_relative_luminance(fg_value)
    bg_l = color_relative_luminance(bg_value)
    lighter = max(fg_l, bg_l)
    darker = min(fg_l, bg_l)
    return (lighter + 0.05) / (darker + 0.05)


def pick_contrasting_color(bg_value: str) -> str:
    black = "#111827"
    white = "#F9FAFB"
    if contrast_ratio(black, bg_value) >= contrast_ratio(white, bg_value):
        return black
    return white


def theme_setting_defaults() -> dict[str, object]:
    palette, font = _palette_and_font()
    base_font_size = max(8, int(font.pointSize() or 10))
    return {
        "font_family": font.family(),
        "font_size": base_font_size,
        "dialog_title_font_size": max(18, base_font_size + 8),
        "section_title_font_size": max(13, base_font_size + 3),
        "secondary_text_font_size": max(9, base_font_size - 1),
        "auto_contrast_enabled": True,
        "window_bg": palette.color(QPalette.Window).name().upper(),
        "window_fg": palette.color(QPalette.WindowText).name().upper(),
        "workspace_bg": "",
        "panel_bg": "",
        "panel_alt_bg": "",
        "border_color": "",
        "group_title_fg": "",
        "compact_group_bg": "",
        "compact_group_border": "",
        "accent": palette.color(QPalette.Highlight).name().upper(),
        "selection_bg": "",
        "selection_fg": "",
        "secondary_text": "",
        "hint_text": "",
        "link_color": "",
        "tooltip_bg": "",
        "tooltip_fg": "",
        "tooltip_border": "",
        "overlay_bg": "",
        "overlay_fg": "",
        "button_bg": palette.color(QPalette.Button).name().upper(),
        "button_fg": palette.color(QPalette.ButtonText).name().upper(),
        "button_border": "",
        "button_hover_bg": "",
        "button_hover_fg": "",
        "button_hover_border": "",
        "button_pressed_bg": "",
        "button_pressed_fg": "",
        "button_pressed_border": "",
        "button_disabled_bg": "",
        "button_disabled_fg": "",
        "button_disabled_border": "",
        "help_button_bg": "",
        "help_button_fg": "",
        "help_button_border": "",
        "help_button_hover_bg": "",
        "help_button_hover_fg": "",
        "help_button_hover_border": "",
        "help_button_pressed_bg": "",
        "help_button_pressed_fg": "",
        "help_button_pressed_border": "",
        "help_button_disabled_bg": "",
        "help_button_disabled_fg": "",
        "help_button_disabled_border": "",
        "input_bg": palette.color(QPalette.Base).name().upper(),
        "input_fg": palette.color(QPalette.Text).name().upper(),
        "input_border": "",
        "input_focus_bg": "",
        "input_focus_fg": "",
        "input_focus_border": "",
        "input_disabled_bg": "",
        "input_disabled_fg": "",
        "input_disabled_border": "",
        "placeholder_fg": "",
        "indicator_bg": "",
        "indicator_border": "",
        "indicator_checked_bg": "",
        "indicator_checked_border": "",
        "indicator_disabled_bg": "",
        "indicator_disabled_border": "",
        "table_bg": palette.color(QPalette.Base).name().upper(),
        "table_fg": palette.color(QPalette.Text).name().upper(),
        "table_alt_bg": "",
        "table_border": "",
        "table_grid": "",
        "table_hover_bg": "",
        "scrollbar_bg": "",
        "scrollbar_handle_bg": "",
        "scrollbar_handle_hover_bg": "",
        "progress_bg": "",
        "progress_chunk_bg": "",
        "progress_fg": "",
        "progress_border": "",
        "menu_bg": "",
        "menu_fg": "",
        "menu_border": "",
        "menu_selected_bg": "",
        "menu_selected_fg": "",
        "header_bg": "",
        "header_fg": "",
        "header_border": "",
        "toolbar_bg": "",
        "toolbar_fg": "",
        "toolbar_border": "",
        "action_ribbon_bg": "",
        "action_ribbon_fg": "",
        "action_ribbon_border": "",
        "statusbar_bg": "",
        "statusbar_fg": "",
        "statusbar_border": "",
        "tab_bg": "",
        "tab_fg": "",
        "tab_border": "",
        "tab_hover_bg": "",
        "tab_hover_fg": "",
        "tab_hover_border": "",
        "tab_selected_bg": "",
        "tab_selected_fg": "",
        "tab_selected_border": "",
        "tab_bar_bg": "",
        "tab_pane_bg": "",
        "tab_pane_border": "",
        "border_width": 1,
        "panel_radius": 8,
        "button_radius": 6,
        "button_padding_v": 6,
        "button_padding_h": 12,
        "help_button_size": 28,
        "help_button_radius": 14,
        "input_radius": 6,
        "input_padding_v": 4,
        "input_padding_h": 6,
        "indicator_size": 16,
        "table_radius": 6,
        "scrollbar_thickness": 14,
        "scrollbar_radius": 6,
        "scrollbar_handle_min": 26,
        "progress_radius": 6,
        "header_padding_v": 6,
        "header_padding_h": 8,
        "tab_radius": 8,
        "menu_radius": 8,
        "selected_name": "",
        "custom_qss": "",
    }


def theme_setting_keys() -> tuple[str, ...]:
    return tuple(theme_setting_defaults().keys())


def normalize_theme_string(value) -> str:
    return str(value or "").strip()


def normalize_theme_font_family(value, fallback) -> str:
    text = normalize_theme_string(value)
    if text in {"-apple-system", "BlinkMacSystemFont", "system-ui"}:
        return str(fallback)
    return text or str(fallback)


def normalize_theme_color(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    color = QColor(text)
    if not color.isValid():
        return ""
    return color.name().upper()


def normalize_theme_settings(values: dict[str, object] | None) -> dict[str, object]:
    defaults = theme_setting_defaults()
    source = dict(values or {})
    normalized: dict[str, object] = {}
    for key, default in defaults.items():
        value = source.get(key, default)
        if key == "font_family":
            normalized[key] = normalize_theme_font_family(value, default)
        elif key == "custom_qss":
            normalized[key] = str(value or "")
        elif key == "selected_name":
            normalized[key] = normalize_theme_string(value)
        elif key == "auto_contrast_enabled":
            normalized[key] = bool(value)
        elif key in THEME_METRIC_SPECS_BY_KEY:
            spec = THEME_METRIC_SPECS_BY_KEY[key]
            try:
                number = int(value)
            except Exception:
                number = spec.default
            normalized[key] = max(spec.minimum, min(spec.maximum, number))
        elif key in THEME_COLOR_KEYS:
            normalized[key] = normalize_theme_color(value)
        else:
            normalized[key] = value
    return normalized


def _resolve_theme_color(
    normalized: dict[str, object],
    defaults: dict[str, object],
    key: str,
    fallback: str,
) -> str:
    value = str(normalized.get(key) or "").strip()
    if value:
        return value
    default = str(defaults.get(key) or "").strip()
    return default or fallback


def effective_theme_settings(raw_values: dict[str, object] | None = None) -> dict[str, object]:
    defaults = theme_setting_defaults()
    normalized = normalize_theme_settings(raw_values or defaults)
    effective: dict[str, object] = dict(normalized)

    window_bg = _resolve_theme_color(normalized, defaults, "window_bg", str(defaults["window_bg"]))
    window_fg = _resolve_theme_color(normalized, defaults, "window_fg", str(defaults["window_fg"]))
    workspace_bg = _resolve_theme_color(normalized, defaults, "workspace_bg", window_bg)
    accent = _resolve_theme_color(normalized, defaults, "accent", str(defaults["accent"]))
    selection_bg = _resolve_theme_color(normalized, defaults, "selection_bg", accent)
    selection_fg = _resolve_theme_color(
        normalized,
        defaults,
        "selection_fg",
        pick_contrasting_color(selection_bg),
    )
    panel_bg = _resolve_theme_color(
        normalized,
        defaults,
        "panel_bg",
        shift_color(window_bg, 104 if QColor(window_bg).lightnessF() < 0.5 else 98),
    )
    panel_alt_bg = _resolve_theme_color(
        normalized,
        defaults,
        "panel_alt_bg",
        shift_color(window_bg, 108 if QColor(window_bg).lightnessF() < 0.5 else 94),
    )
    border_color = _resolve_theme_color(
        normalized,
        defaults,
        "border_color",
        shift_color(window_bg, 88 if QColor(window_bg).lightnessF() >= 0.5 else 118),
    )
    group_title_fg = _resolve_theme_color(normalized, defaults, "group_title_fg", window_fg)
    compact_group_bg = _resolve_theme_color(normalized, defaults, "compact_group_bg", panel_bg)
    compact_group_border = _resolve_theme_color(
        normalized, defaults, "compact_group_border", border_color
    )
    secondary_text = _resolve_theme_color(
        normalized,
        defaults,
        "secondary_text",
        shift_color(window_fg, 140 if QColor(window_fg).lightnessF() < 0.5 else 72),
    )
    hint_text = _resolve_theme_color(normalized, defaults, "hint_text", secondary_text)
    link_color = _resolve_theme_color(normalized, defaults, "link_color", accent)
    tooltip_bg = _resolve_theme_color(normalized, defaults, "tooltip_bg", panel_bg)
    tooltip_fg = _resolve_theme_color(normalized, defaults, "tooltip_fg", window_fg)
    tooltip_border = _resolve_theme_color(normalized, defaults, "tooltip_border", border_color)
    overlay_bg = _resolve_theme_color(
        normalized,
        defaults,
        "overlay_bg",
        shift_color(window_bg, 70 if QColor(window_bg).lightnessF() >= 0.5 else 135),
    )
    overlay_fg = _resolve_theme_color(
        normalized,
        defaults,
        "overlay_fg",
        pick_contrasting_color(overlay_bg),
    )

    button_bg = _resolve_theme_color(normalized, defaults, "button_bg", str(defaults["button_bg"]))
    button_fg = _resolve_theme_color(normalized, defaults, "button_fg", str(defaults["button_fg"]))
    button_border = _resolve_theme_color(
        normalized,
        defaults,
        "button_border",
        shift_color(button_bg, 86 if QColor(button_bg).lightnessF() >= 0.5 else 118),
    )
    button_hover_bg = _resolve_theme_color(
        normalized,
        defaults,
        "button_hover_bg",
        shift_color(button_bg, 108 if QColor(button_bg).lightnessF() < 0.5 else 94),
    )
    button_hover_fg = _resolve_theme_color(normalized, defaults, "button_hover_fg", button_fg)
    button_hover_border = _resolve_theme_color(
        normalized,
        defaults,
        "button_hover_border",
        accent,
    )
    button_pressed_bg = _resolve_theme_color(normalized, defaults, "button_pressed_bg", accent)
    button_pressed_fg = _resolve_theme_color(
        normalized,
        defaults,
        "button_pressed_fg",
        pick_contrasting_color(button_pressed_bg),
    )
    button_pressed_border = _resolve_theme_color(
        normalized,
        defaults,
        "button_pressed_border",
        shift_color(accent, 88 if QColor(accent).lightnessF() >= 0.5 else 118),
    )
    button_disabled_bg = _resolve_theme_color(
        normalized, defaults, "button_disabled_bg", panel_alt_bg
    )
    button_disabled_fg = _resolve_theme_color(
        normalized, defaults, "button_disabled_fg", secondary_text
    )
    button_disabled_border = _resolve_theme_color(
        normalized, defaults, "button_disabled_border", border_color
    )

    help_button_bg = _resolve_theme_color(normalized, defaults, "help_button_bg", accent)
    help_button_fg = _resolve_theme_color(
        normalized,
        defaults,
        "help_button_fg",
        pick_contrasting_color(help_button_bg),
    )
    help_button_border = _resolve_theme_color(
        normalized,
        defaults,
        "help_button_border",
        button_border,
    )
    help_button_hover_bg = _resolve_theme_color(
        normalized,
        defaults,
        "help_button_hover_bg",
        shift_color(help_button_bg, 108 if QColor(help_button_bg).lightnessF() < 0.5 else 94),
    )
    help_button_hover_fg = _resolve_theme_color(
        normalized, defaults, "help_button_hover_fg", help_button_fg
    )
    help_button_hover_border = _resolve_theme_color(
        normalized, defaults, "help_button_hover_border", accent
    )
    help_button_pressed_bg = _resolve_theme_color(
        normalized,
        defaults,
        "help_button_pressed_bg",
        shift_color(help_button_bg, 84 if QColor(help_button_bg).lightnessF() >= 0.5 else 118),
    )
    help_button_pressed_fg = _resolve_theme_color(
        normalized, defaults, "help_button_pressed_fg", help_button_fg
    )
    help_button_pressed_border = _resolve_theme_color(
        normalized, defaults, "help_button_pressed_border", button_pressed_border
    )
    help_button_disabled_bg = _resolve_theme_color(
        normalized, defaults, "help_button_disabled_bg", button_disabled_bg
    )
    help_button_disabled_fg = _resolve_theme_color(
        normalized, defaults, "help_button_disabled_fg", button_disabled_fg
    )
    help_button_disabled_border = _resolve_theme_color(
        normalized, defaults, "help_button_disabled_border", button_disabled_border
    )

    input_bg = _resolve_theme_color(normalized, defaults, "input_bg", str(defaults["input_bg"]))
    input_fg = _resolve_theme_color(normalized, defaults, "input_fg", str(defaults["input_fg"]))
    input_border = _resolve_theme_color(
        normalized,
        defaults,
        "input_border",
        shift_color(input_bg, 86 if QColor(input_bg).lightnessF() >= 0.5 else 118),
    )
    input_focus_bg = _resolve_theme_color(normalized, defaults, "input_focus_bg", input_bg)
    input_focus_fg = _resolve_theme_color(normalized, defaults, "input_focus_fg", input_fg)
    input_focus_border = _resolve_theme_color(normalized, defaults, "input_focus_border", accent)
    input_disabled_bg = _resolve_theme_color(normalized, defaults, "input_disabled_bg", panel_bg)
    input_disabled_fg = _resolve_theme_color(
        normalized, defaults, "input_disabled_fg", secondary_text
    )
    input_disabled_border = _resolve_theme_color(
        normalized, defaults, "input_disabled_border", border_color
    )
    placeholder_fg = _resolve_theme_color(normalized, defaults, "placeholder_fg", secondary_text)
    indicator_bg = _resolve_theme_color(normalized, defaults, "indicator_bg", input_bg)
    indicator_border = _resolve_theme_color(normalized, defaults, "indicator_border", input_border)
    indicator_checked_bg = _resolve_theme_color(
        normalized, defaults, "indicator_checked_bg", accent
    )
    indicator_checked_border = _resolve_theme_color(
        normalized, defaults, "indicator_checked_border", accent
    )
    indicator_disabled_bg = _resolve_theme_color(
        normalized, defaults, "indicator_disabled_bg", input_disabled_bg
    )
    indicator_disabled_border = _resolve_theme_color(
        normalized, defaults, "indicator_disabled_border", input_disabled_border
    )

    table_bg = _resolve_theme_color(normalized, defaults, "table_bg", str(defaults["table_bg"]))
    table_fg = _resolve_theme_color(normalized, defaults, "table_fg", str(defaults["table_fg"]))
    table_alt_bg = _resolve_theme_color(
        normalized,
        defaults,
        "table_alt_bg",
        shift_color(table_bg, 104 if QColor(table_bg).lightnessF() < 0.5 else 97),
    )
    table_border = _resolve_theme_color(normalized, defaults, "table_border", border_color)
    table_grid = _resolve_theme_color(normalized, defaults, "table_grid", border_color)
    table_hover_bg = _resolve_theme_color(
        normalized,
        defaults,
        "table_hover_bg",
        shift_color(selection_bg, 116 if QColor(selection_bg).lightnessF() < 0.5 else 92),
    )
    scrollbar_bg = _resolve_theme_color(normalized, defaults, "scrollbar_bg", panel_alt_bg)
    scrollbar_handle_bg = _resolve_theme_color(
        normalized, defaults, "scrollbar_handle_bg", button_bg
    )
    scrollbar_handle_hover_bg = _resolve_theme_color(
        normalized, defaults, "scrollbar_handle_hover_bg", button_hover_bg
    )
    progress_bg = _resolve_theme_color(normalized, defaults, "progress_bg", panel_alt_bg)
    progress_chunk_bg = _resolve_theme_color(normalized, defaults, "progress_chunk_bg", accent)
    progress_fg = _resolve_theme_color(
        normalized,
        defaults,
        "progress_fg",
        pick_contrasting_color(progress_bg),
    )
    progress_border = _resolve_theme_color(normalized, defaults, "progress_border", border_color)

    menu_bg = _resolve_theme_color(normalized, defaults, "menu_bg", panel_bg)
    menu_fg = _resolve_theme_color(normalized, defaults, "menu_fg", window_fg)
    menu_border = _resolve_theme_color(normalized, defaults, "menu_border", border_color)
    menu_selected_bg = _resolve_theme_color(normalized, defaults, "menu_selected_bg", accent)
    menu_selected_fg = _resolve_theme_color(
        normalized,
        defaults,
        "menu_selected_fg",
        pick_contrasting_color(menu_selected_bg),
    )
    header_bg = _resolve_theme_color(
        normalized,
        defaults,
        "header_bg",
        shift_color(window_bg, 108 if QColor(window_bg).lightnessF() < 0.5 else 92),
    )
    header_fg = _resolve_theme_color(normalized, defaults, "header_fg", window_fg)
    header_border = _resolve_theme_color(normalized, defaults, "header_border", border_color)
    toolbar_bg = _resolve_theme_color(normalized, defaults, "toolbar_bg", panel_bg)
    toolbar_fg = _resolve_theme_color(normalized, defaults, "toolbar_fg", window_fg)
    toolbar_border = _resolve_theme_color(normalized, defaults, "toolbar_border", border_color)
    action_ribbon_bg = _resolve_theme_color(
        normalized, defaults, "action_ribbon_bg", toolbar_bg
    )
    action_ribbon_fg = _resolve_theme_color(
        normalized, defaults, "action_ribbon_fg", toolbar_fg
    )
    action_ribbon_border = _resolve_theme_color(
        normalized, defaults, "action_ribbon_border", toolbar_border
    )
    statusbar_bg = _resolve_theme_color(normalized, defaults, "statusbar_bg", panel_bg)
    statusbar_fg = _resolve_theme_color(normalized, defaults, "statusbar_fg", window_fg)
    statusbar_border = _resolve_theme_color(normalized, defaults, "statusbar_border", border_color)
    tab_bg = _resolve_theme_color(normalized, defaults, "tab_bg", panel_bg)
    tab_fg = _resolve_theme_color(normalized, defaults, "tab_fg", window_fg)
    tab_border = _resolve_theme_color(normalized, defaults, "tab_border", border_color)
    tab_hover_bg = _resolve_theme_color(
        normalized,
        defaults,
        "tab_hover_bg",
        shift_color(tab_bg, 108 if QColor(tab_bg).lightnessF() < 0.5 else 94),
    )
    tab_hover_fg = _resolve_theme_color(normalized, defaults, "tab_hover_fg", tab_fg)
    tab_hover_border = _resolve_theme_color(normalized, defaults, "tab_hover_border", accent)
    tab_selected_bg = _resolve_theme_color(normalized, defaults, "tab_selected_bg", accent)
    tab_selected_fg = _resolve_theme_color(
        normalized,
        defaults,
        "tab_selected_fg",
        pick_contrasting_color(tab_selected_bg),
    )
    tab_selected_border = _resolve_theme_color(
        normalized, defaults, "tab_selected_border", button_pressed_border
    )
    tab_bar_bg = _resolve_theme_color(normalized, defaults, "tab_bar_bg", workspace_bg)
    tab_pane_bg = _resolve_theme_color(normalized, defaults, "tab_pane_bg", panel_bg)
    tab_pane_border = _resolve_theme_color(normalized, defaults, "tab_pane_border", border_color)

    effective.update(
        {
            "window_bg": window_bg,
            "window_fg": window_fg,
            "workspace_bg": workspace_bg,
            "panel_bg": panel_bg,
            "panel_alt_bg": panel_alt_bg,
            "border_color": border_color,
            "group_title_fg": group_title_fg,
            "compact_group_bg": compact_group_bg,
            "compact_group_border": compact_group_border,
            "accent": accent,
            "selection_bg": selection_bg,
            "selection_fg": selection_fg,
            "secondary_text": secondary_text,
            "hint_text": hint_text,
            "link_color": link_color,
            "tooltip_bg": tooltip_bg,
            "tooltip_fg": tooltip_fg,
            "tooltip_border": tooltip_border,
            "overlay_bg": overlay_bg,
            "overlay_fg": overlay_fg,
            "button_bg": button_bg,
            "button_fg": button_fg,
            "button_border": button_border,
            "button_hover_bg": button_hover_bg,
            "button_hover_fg": button_hover_fg,
            "button_hover_border": button_hover_border,
            "button_pressed_bg": button_pressed_bg,
            "button_pressed_fg": button_pressed_fg,
            "button_pressed_border": button_pressed_border,
            "button_disabled_bg": button_disabled_bg,
            "button_disabled_fg": button_disabled_fg,
            "button_disabled_border": button_disabled_border,
            "help_button_bg": help_button_bg,
            "help_button_fg": help_button_fg,
            "help_button_border": help_button_border,
            "help_button_hover_bg": help_button_hover_bg,
            "help_button_hover_fg": help_button_hover_fg,
            "help_button_hover_border": help_button_hover_border,
            "help_button_pressed_bg": help_button_pressed_bg,
            "help_button_pressed_fg": help_button_pressed_fg,
            "help_button_pressed_border": help_button_pressed_border,
            "help_button_disabled_bg": help_button_disabled_bg,
            "help_button_disabled_fg": help_button_disabled_fg,
            "help_button_disabled_border": help_button_disabled_border,
            "input_bg": input_bg,
            "input_fg": input_fg,
            "input_border": input_border,
            "input_focus_bg": input_focus_bg,
            "input_focus_fg": input_focus_fg,
            "input_focus_border": input_focus_border,
            "input_disabled_bg": input_disabled_bg,
            "input_disabled_fg": input_disabled_fg,
            "input_disabled_border": input_disabled_border,
            "placeholder_fg": placeholder_fg,
            "indicator_bg": indicator_bg,
            "indicator_border": indicator_border,
            "indicator_checked_bg": indicator_checked_bg,
            "indicator_checked_border": indicator_checked_border,
            "indicator_disabled_bg": indicator_disabled_bg,
            "indicator_disabled_border": indicator_disabled_border,
            "table_bg": table_bg,
            "table_fg": table_fg,
            "table_alt_bg": table_alt_bg,
            "table_border": table_border,
            "table_grid": table_grid,
            "table_hover_bg": table_hover_bg,
            "scrollbar_bg": scrollbar_bg,
            "scrollbar_handle_bg": scrollbar_handle_bg,
            "scrollbar_handle_hover_bg": scrollbar_handle_hover_bg,
            "progress_bg": progress_bg,
            "progress_chunk_bg": progress_chunk_bg,
            "progress_fg": progress_fg,
            "progress_border": progress_border,
            "menu_bg": menu_bg,
            "menu_fg": menu_fg,
            "menu_border": menu_border,
            "menu_selected_bg": menu_selected_bg,
            "menu_selected_fg": menu_selected_fg,
            "header_bg": header_bg,
            "header_fg": header_fg,
            "header_border": header_border,
            "toolbar_bg": toolbar_bg,
            "toolbar_fg": toolbar_fg,
            "toolbar_border": toolbar_border,
            "action_ribbon_bg": action_ribbon_bg,
            "action_ribbon_fg": action_ribbon_fg,
            "action_ribbon_border": action_ribbon_border,
            "statusbar_bg": statusbar_bg,
            "statusbar_fg": statusbar_fg,
            "statusbar_border": statusbar_border,
            "tab_bg": tab_bg,
            "tab_fg": tab_fg,
            "tab_border": tab_border,
            "tab_hover_bg": tab_hover_bg,
            "tab_hover_fg": tab_hover_fg,
            "tab_hover_border": tab_hover_border,
            "tab_selected_bg": tab_selected_bg,
            "tab_selected_fg": tab_selected_fg,
            "tab_selected_border": tab_selected_border,
            "tab_bar_bg": tab_bar_bg,
            "tab_pane_bg": tab_pane_bg,
            "tab_pane_border": tab_pane_border,
        }
    )

    if effective.get("auto_contrast_enabled", True):
        for bg_key, fg_key in (
            ("window_bg", "window_fg"),
            ("workspace_bg", "window_fg"),
            ("selection_bg", "selection_fg"),
            ("button_bg", "button_fg"),
            ("button_hover_bg", "button_hover_fg"),
            ("button_pressed_bg", "button_pressed_fg"),
            ("button_disabled_bg", "button_disabled_fg"),
            ("help_button_bg", "help_button_fg"),
            ("help_button_hover_bg", "help_button_hover_fg"),
            ("help_button_pressed_bg", "help_button_pressed_fg"),
            ("help_button_disabled_bg", "help_button_disabled_fg"),
            ("input_bg", "input_fg"),
            ("input_focus_bg", "input_focus_fg"),
            ("input_disabled_bg", "input_disabled_fg"),
            ("table_bg", "table_fg"),
            ("menu_bg", "menu_fg"),
            ("menu_selected_bg", "menu_selected_fg"),
            ("header_bg", "header_fg"),
            ("toolbar_bg", "toolbar_fg"),
            ("action_ribbon_bg", "action_ribbon_fg"),
            ("statusbar_bg", "statusbar_fg"),
            ("tab_bg", "tab_fg"),
            ("tab_hover_bg", "tab_hover_fg"),
            ("tab_selected_bg", "tab_selected_fg"),
            ("progress_bg", "progress_fg"),
            ("tooltip_bg", "tooltip_fg"),
            ("overlay_bg", "overlay_fg"),
        ):
            background = str(effective[bg_key])
            foreground = str(effective[fg_key])
            if contrast_ratio(foreground, background) < 4.5:
                effective[fg_key] = pick_contrasting_color(background)
        if contrast_ratio(str(effective["group_title_fg"]), str(effective["panel_bg"])) < 4.5:
            effective["group_title_fg"] = pick_contrasting_color(str(effective["panel_bg"]))

    return effective


def build_theme_palette(raw_values: dict[str, object] | None = None) -> QPalette:
    theme = effective_theme_settings(raw_values)
    palette = QPalette()
    window_bg = QColor(str(theme["window_bg"]))
    window_fg = QColor(str(theme["window_fg"]))
    panel_bg = QColor(str(theme["panel_bg"]))
    table_bg = QColor(str(theme["table_bg"]))
    button_bg = QColor(str(theme["button_bg"]))
    button_fg = QColor(str(theme["button_fg"]))
    selection_bg = QColor(str(theme["selection_bg"]))
    selection_fg = QColor(str(theme["selection_fg"]))
    tooltip_bg = QColor(str(theme["tooltip_bg"]))
    tooltip_fg = QColor(str(theme["tooltip_fg"]))
    placeholder_fg = QColor(str(theme["placeholder_fg"]))
    disabled_fg = QColor(str(theme["button_disabled_fg"]))
    disabled_bg = QColor(str(theme["input_disabled_bg"]))
    link_fg = QColor(str(theme["link_color"]))

    palette.setColor(QPalette.Window, window_bg)
    palette.setColor(QPalette.WindowText, window_fg)
    palette.setColor(QPalette.Base, table_bg)
    palette.setColor(QPalette.AlternateBase, panel_bg)
    palette.setColor(QPalette.Text, QColor(str(theme["table_fg"])))
    palette.setColor(QPalette.Button, button_bg)
    palette.setColor(QPalette.ButtonText, button_fg)
    palette.setColor(QPalette.Highlight, selection_bg)
    palette.setColor(QPalette.HighlightedText, selection_fg)
    palette.setColor(QPalette.ToolTipBase, tooltip_bg)
    palette.setColor(QPalette.ToolTipText, tooltip_fg)
    palette.setColor(QPalette.PlaceholderText, placeholder_fg)
    palette.setColor(QPalette.Link, link_fg)
    palette.setColor(QPalette.Mid, QColor(str(theme["border_color"])))
    palette.setColor(QPalette.Midlight, QColor(str(theme["panel_alt_bg"])))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, disabled_fg)
    palette.setColor(QPalette.Disabled, QPalette.Text, disabled_fg)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, disabled_fg)
    palette.setColor(QPalette.Disabled, QPalette.Button, disabled_bg)
    palette.setColor(QPalette.Disabled, QPalette.Base, disabled_bg)
    return palette


def build_theme_stylesheet(raw_values: dict[str, object] | None = None) -> str:
    theme = effective_theme_settings(raw_values)
    custom_qss = str(theme.get("custom_qss") or "").strip()
    font_family_css = str(theme["font_family"]).replace('"', '\\"')

    stylesheet = f"""
    QWidget {{
        color: {theme["window_fg"]};
        font-family: "{font_family_css}";
        font-size: {int(theme["font_size"])}pt;
        selection-background-color: {theme["selection_bg"]};
        selection-color: {theme["selection_fg"]};
    }}
    QWidget:disabled {{
        color: {theme["secondary_text"]};
    }}
    QMainWindow,
    QDialog,
    QWidget#dockPlaceholder,
    QWidget[role="panel"],
    QScrollArea,
    QStatusBar {{
        background-color: {theme["window_bg"]};
        color: {theme["window_fg"]};
    }}
    QDockWidget,
    QDockWidget > QWidget {{
        background-color: {theme["window_bg"]};
        color: {theme["window_fg"]};
    }}
    QWidget[role="workspaceCanvas"] {{
        background-color: {theme["workspace_bg"]};
        color: {theme["window_fg"]};
    }}
    QDockWidget QWidget[role="workspaceCanvas"],
    QDockWidget QScrollArea,
    QDockWidget QAbstractScrollArea,
    QDockWidget QAbstractScrollArea::viewport {{
        background-color: {theme["workspace_bg"]};
        color: {theme["window_fg"]};
    }}
    QWidget[role="tabPaneCanvas"] {{
        background-color: {theme["tab_pane_bg"]};
        color: {theme["window_fg"]};
    }}
    QToolTip {{
        background-color: {theme["tooltip_bg"]};
        color: {theme["tooltip_fg"]};
        border: {int(theme["border_width"])}px solid {theme["tooltip_border"]};
        border-radius: {int(theme["menu_radius"])}px;
        padding: 4px 6px;
    }}
    QLabel {{
        color: {theme["window_fg"]};
    }}
    QLabel[role="dialogTitle"] {{
        font-size: {int(theme["dialog_title_font_size"])}pt;
        font-weight: 700;
        color: {theme["window_fg"]};
    }}
    QLabel[role="dialogSubtitle"],
    QLabel[role="sectionDescription"],
    QLabel[role="supportingText"],
    QLabel[role="secondary"],
    QLabel[role="meta"],
    QLabel[role="statusText"] {{
        color: {theme["secondary_text"]};
        font-size: {int(theme["secondary_text_font_size"])}pt;
    }}
    QLabel[role="hint"],
    QLabel[role="sectionHelp"],
    QLabel[role="themeNote"] {{
        color: {theme["hint_text"]};
        font-size: {int(theme["secondary_text_font_size"])}pt;
    }}
    QLabel[role="sectionTitle"] {{
        color: {theme["window_fg"]};
        font-size: {int(theme["section_title_font_size"])}pt;
        font-weight: 700;
    }}
    QLabel[role="overlayHint"] {{
        background-color: {theme["overlay_bg"]};
        color: {theme["overlay_fg"]};
        padding: 4px 8px;
        border-radius: {int(theme["panel_radius"])}px;
        font-size: {int(theme["secondary_text_font_size"])}pt;
    }}
    QTextBrowser, QLabel[openExternalLinks="true"] {{
        color: {theme["link_color"]};
    }}
    QGroupBox {{
        border: {int(theme["border_width"])}px solid {theme["border_color"]};
        border-radius: {int(theme["panel_radius"])}px;
        margin-top: 12px;
        padding-top: 10px;
        background-color: {theme["panel_bg"]};
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: {theme["group_title_fg"]};
    }}
    QFrame[role="compactControlGroup"],
    QWidget[role="compactControlGroup"] {{
        border: {int(theme["border_width"])}px solid {theme["compact_group_border"]};
        border-radius: {int(theme["panel_radius"])}px;
        background-color: {theme["compact_group_bg"]};
    }}
    QDockWidget {{
        border: {int(theme["border_width"])}px solid {theme["border_color"]};
    }}
    QDockWidget::title,
    QHeaderView::section {{
        background-color: {theme["header_bg"]};
        color: {theme["header_fg"]};
        padding: {int(theme["header_padding_v"])}px {int(theme["header_padding_h"])}px;
        border: {int(theme["border_width"])}px solid {theme["header_border"]};
    }}
    QHeaderView {{
        background-color: {theme["header_bg"]};
        color: {theme["header_fg"]};
        border: {int(theme["border_width"])}px solid {theme["header_border"]};
    }}
    QTableCornerButton::section,
    QTableView QTableCornerButton::section {{
        background-color: {theme["header_bg"]};
        border: {int(theme["border_width"])}px solid {theme["header_border"]};
    }}
    QMenuBar {{
        background-color: {theme["toolbar_bg"]};
        color: {theme["menu_fg"]};
        border-bottom: {int(theme["border_width"])}px solid {theme["toolbar_border"]};
    }}
    QToolBar {{
        background-color: {theme["toolbar_bg"]};
        color: {theme["toolbar_fg"]};
        border-bottom: {int(theme["border_width"])}px solid {theme["toolbar_border"]};
    }}
    QToolBar#profilesToolbar {{
        border-bottom: 5px solid {theme["toolbar_border"]};
    }}
    QToolBar#actionRibbonToolbar,
    QToolBar[role="actionRibbonToolbar"] {{
        background-color: {theme["action_ribbon_bg"]};
        color: {theme["action_ribbon_fg"]};
        border-bottom: {int(theme["border_width"])}px solid {theme["action_ribbon_border"]};
    }}
    QToolBar QLabel {{
        color: {theme["toolbar_fg"]};
    }}
    QToolBar#actionRibbonToolbar QLabel,
    QToolBar[role="actionRibbonToolbar"] QLabel {{
        color: {theme["action_ribbon_fg"]};
    }}
    QToolBar::separator {{
        background: {theme["toolbar_border"]};
        width: {max(1, int(theme["border_width"]))}px;
        margin: 4px 6px;
    }}
    QToolBar#actionRibbonToolbar::separator,
    QToolBar[role="actionRibbonToolbar"]::separator {{
        background: {theme["action_ribbon_border"]};
    }}
    QStatusBar {{
        background-color: {theme["statusbar_bg"]};
        color: {theme["statusbar_fg"]};
        border-top: {int(theme["border_width"])}px solid {theme["statusbar_border"]};
    }}
    QStatusBar QLabel {{
        color: {theme["statusbar_fg"]};
    }}
    QMenuBar::item,
    QMenu::item {{
        background: transparent;
        color: {theme["menu_fg"]};
        padding: 6px 10px;
        border-radius: {int(theme["menu_radius"])}px;
    }}
    QMenuBar::item:selected,
    QMenuBar::item:pressed,
    QMenu::item:selected {{
        background-color: {theme["menu_selected_bg"]};
        color: {theme["menu_selected_fg"]};
    }}
    QMenu {{
        background-color: {theme["menu_bg"]};
        color: {theme["menu_fg"]};
        border: {int(theme["border_width"])}px solid {theme["menu_border"]};
        border-radius: {int(theme["menu_radius"])}px;
        padding: 6px;
    }}
    QTabWidget {{
        background-color: {theme["tab_bar_bg"]};
    }}
    QTabWidget::tab-bar {{
        background-color: {theme["tab_bar_bg"]};
        left: 0px;
    }}
    QTabWidget::pane {{
        border: {int(theme["border_width"])}px solid {theme["tab_pane_border"]};
        background: {theme["tab_pane_bg"]};
        border-radius: {int(theme["panel_radius"])}px;
        top: -1px;
    }}
    QTabBar {{
        background-color: {theme["tab_bar_bg"]};
        qproperty-drawBase: 0;
    }}
    QTabBar::tab {{
        background-color: {theme["tab_bg"]};
        color: {theme["tab_fg"]};
        border: {int(theme["border_width"])}px solid {theme["tab_border"]};
        border-bottom-color: {theme["tab_border"]};
        border-top-left-radius: {int(theme["tab_radius"])}px;
        border-top-right-radius: {int(theme["tab_radius"])}px;
        padding: 6px 12px;
        margin-right: 2px;
    }}
    QTabBar::tab:hover {{
        background-color: {theme["tab_hover_bg"]};
        color: {theme["tab_hover_fg"]};
        border-color: {theme["tab_hover_border"]};
    }}
    QTabBar::tab:selected {{
        background-color: {theme["tab_selected_bg"]};
        color: {theme["tab_selected_fg"]};
        border-color: {theme["tab_selected_border"]};
    }}
    QPushButton,
    QToolButton,
    QDialogButtonBox QPushButton {{
        background-color: {theme["button_bg"]};
        color: {theme["button_fg"]};
        border: {int(theme["border_width"])}px solid {theme["button_border"]};
        border-radius: {int(theme["button_radius"])}px;
        padding: {int(theme["button_padding_v"])}px {int(theme["button_padding_h"])}px;
    }}
    QPushButton:hover,
    QToolButton:hover,
    QDialogButtonBox QPushButton:hover {{
        background-color: {theme["button_hover_bg"]};
        color: {theme["button_hover_fg"]};
        border-color: {theme["button_hover_border"]};
    }}
    QPushButton:pressed,
    QToolButton:pressed,
    QToolButton:checked,
    QPushButton:checked,
    QDialogButtonBox QPushButton:pressed {{
        background-color: {theme["button_pressed_bg"]};
        color: {theme["button_pressed_fg"]};
        border-color: {theme["button_pressed_border"]};
    }}
    QPushButton:disabled,
    QToolButton:disabled,
    QDialogButtonBox QPushButton:disabled {{
        background-color: {theme["button_disabled_bg"]};
        color: {theme["button_disabled_fg"]};
        border-color: {theme["button_disabled_border"]};
    }}
    QToolButton[role="helpButton"] {{
        min-width: {int(theme["help_button_size"])}px;
        max-width: {int(theme["help_button_size"])}px;
        min-height: {int(theme["help_button_size"])}px;
        max-height: {int(theme["help_button_size"])}px;
        border-radius: {int(theme["help_button_radius"])}px;
        padding: 0;
        font-weight: 700;
        background-color: {theme["help_button_bg"]};
        color: {theme["help_button_fg"]};
        border: {int(theme["border_width"])}px solid {theme["help_button_border"]};
    }}
    QToolButton[role="helpButton"]:hover {{
        background-color: {theme["help_button_hover_bg"]};
        color: {theme["help_button_hover_fg"]};
        border-color: {theme["help_button_hover_border"]};
    }}
    QToolButton[role="helpButton"]:pressed {{
        background-color: {theme["help_button_pressed_bg"]};
        color: {theme["help_button_pressed_fg"]};
        border-color: {theme["help_button_pressed_border"]};
    }}
    QToolButton[role="helpButton"]:disabled {{
        background-color: {theme["help_button_disabled_bg"]};
        color: {theme["help_button_disabled_fg"]};
        border-color: {theme["help_button_disabled_border"]};
    }}
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QTextBrowser,
    QComboBox,
    QSpinBox,
    QFontComboBox,
    QCalendarWidget,
    QListWidget,
    QListView,
    QTableWidget,
    QTableView,
    QTreeView,
    QAbstractSpinBox {{
        background-color: {theme["input_bg"]};
        color: {theme["input_fg"]};
        border: {int(theme["border_width"])}px solid {theme["input_border"]};
        border-radius: {int(theme["input_radius"])}px;
        padding: {int(theme["input_padding_v"])}px {int(theme["input_padding_h"])}px;
    }}
    QLineEdit:focus,
    QPlainTextEdit:focus,
    QTextEdit:focus,
    QTextBrowser:focus,
    QComboBox:focus,
    QSpinBox:focus,
    QFontComboBox:focus,
    QAbstractSpinBox:focus {{
        background-color: {theme["input_focus_bg"]};
        color: {theme["input_focus_fg"]};
        border-color: {theme["input_focus_border"]};
    }}
    QLineEdit:disabled,
    QPlainTextEdit:disabled,
    QTextEdit:disabled,
    QTextBrowser:disabled,
    QComboBox:disabled,
    QSpinBox:disabled,
    QFontComboBox:disabled,
    QAbstractSpinBox:disabled {{
        background-color: {theme["input_disabled_bg"]};
        color: {theme["input_disabled_fg"]};
        border-color: {theme["input_disabled_border"]};
    }}
    QLineEdit,
    QPlainTextEdit,
    QTextEdit {{
        placeholder-text-color: {theme["placeholder_fg"]};
    }}
    QComboBox::drop-down,
    QFontComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 28px;
        border-left: {int(theme["border_width"])}px solid {theme["input_border"]};
        border-top-right-radius: {int(theme["input_radius"])}px;
        border-bottom-right-radius: {int(theme["input_radius"])}px;
        background-color: {theme["panel_alt_bg"]};
    }}
    QComboBox::down-arrow,
    QFontComboBox::down-arrow {{
        image: url("{_combo_arrow_data_uri(theme["input_fg"])}");
        width: 12px;
        height: 8px;
    }}
    QComboBox:focus::drop-down,
    QFontComboBox:focus::drop-down {{
        border-left-color: {theme["input_focus_border"]};
        background-color: {theme["input_focus_bg"]};
    }}
    QComboBox:disabled::drop-down,
    QFontComboBox:disabled::drop-down {{
        border-left-color: {theme["input_disabled_border"]};
        background-color: {theme["input_disabled_bg"]};
    }}
    QComboBox:disabled::down-arrow,
    QFontComboBox:disabled::down-arrow {{
        image: url("{_combo_arrow_data_uri(theme["input_disabled_fg"])}");
    }}
    QComboBox QAbstractItemView,
    QFontComboBox QAbstractItemView {{
        background-color: {theme["menu_bg"]};
        color: {theme["menu_fg"]};
        border: {int(theme["border_width"])}px solid {theme["menu_border"]};
        selection-background-color: {theme["menu_selected_bg"]};
        selection-color: {theme["menu_selected_fg"]};
    }}
    QComboBox QAbstractItemView::item,
    QFontComboBox QAbstractItemView::item {{
        padding: 4px 8px;
    }}
    QCheckBox,
    QRadioButton {{
        spacing: 8px;
    }}
    QCheckBox::indicator,
    QRadioButton::indicator {{
        width: {int(theme["indicator_size"])}px;
        height: {int(theme["indicator_size"])}px;
        background-color: {theme["indicator_bg"]};
        border: {int(theme["border_width"])}px solid {theme["indicator_border"]};
        border-radius: {max(2, int(theme["indicator_size"]) // 4)}px;
    }}
    QRadioButton::indicator {{
        border-radius: {max(6, int(theme["indicator_size"]) // 2)}px;
    }}
    QCheckBox::indicator:checked,
    QRadioButton::indicator:checked {{
        background-color: {theme["indicator_checked_bg"]};
        border-color: {theme["indicator_checked_border"]};
    }}
    QCheckBox::indicator:disabled,
    QRadioButton::indicator:disabled {{
        background-color: {theme["indicator_disabled_bg"]};
        border-color: {theme["indicator_disabled_border"]};
    }}
    QTableWidget,
    QTableView,
    QListWidget,
    QListView,
    QTreeView {{
        background-color: {theme["table_bg"]};
        color: {theme["table_fg"]};
        border: {int(theme["border_width"])}px solid {theme["table_border"]};
        border-radius: {int(theme["table_radius"])}px;
        alternate-background-color: {theme["table_alt_bg"]};
        gridline-color: {theme["table_grid"]};
    }}
    QAbstractItemView {{
        selection-background-color: {theme["selection_bg"]};
        selection-color: {theme["selection_fg"]};
        alternate-background-color: {theme["table_alt_bg"]};
    }}
    QTableWidget::item:hover,
    QTableView::item:hover,
    QListWidget::item:hover,
    QListView::item:hover,
    QTreeView::item:hover {{
        background-color: {theme["table_hover_bg"]};
    }}
    QScrollBar:vertical,
    QScrollBar:horizontal {{
        background: {theme["scrollbar_bg"]};
        border: 0;
        margin: 0;
        border-radius: {int(theme["scrollbar_radius"])}px;
    }}
    QScrollBar:vertical {{
        width: {int(theme["scrollbar_thickness"])}px;
    }}
    QScrollBar:horizontal {{
        height: {int(theme["scrollbar_thickness"])}px;
    }}
    QScrollBar::handle:vertical,
    QScrollBar::handle:horizontal {{
        background: {theme["scrollbar_handle_bg"]};
        border-radius: {int(theme["scrollbar_radius"])}px;
    }}
    QScrollBar::handle:vertical {{
        min-height: {int(theme["scrollbar_handle_min"])}px;
    }}
    QScrollBar::handle:horizontal {{
        min-width: {int(theme["scrollbar_handle_min"])}px;
    }}
    QScrollBar::handle:hover:vertical,
    QScrollBar::handle:hover:horizontal {{
        background: {theme["scrollbar_handle_hover_bg"]};
    }}
    QScrollBar::add-line,
    QScrollBar::sub-line,
    QScrollBar::add-page,
    QScrollBar::sub-page {{
        background: transparent;
        border: none;
    }}
    QProgressBar {{
        background-color: {theme["progress_bg"]};
        color: {theme["progress_fg"]};
        border: {int(theme["border_width"])}px solid {theme["progress_border"]};
        border-radius: {int(theme["progress_radius"])}px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {theme["progress_chunk_bg"]};
        border-radius: {int(theme["progress_radius"])}px;
    }}
    """
    if custom_qss:
        stylesheet = f"{stylesheet}\n\n/* Advanced QSS */\n{custom_qss}\n"
    return stylesheet
