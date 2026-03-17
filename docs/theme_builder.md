# Theme Builder

The application now ships with a full visual theme builder in `Settings > Application Settings > Theme`.

## Starter Themes

The packaged theme library now includes seven starter presets so every build starts with useful options before you touch Advanced QSS:

- `Apple Light`
- `Apple Dark`
- `High Visibility`
- `Aeon Emerald Gold`
- `Subconscious Cosmos`
- `VS Code Dark`
- `Pastel Studio`

These starter themes are bundled with the app itself, so they are available in packaged binaries as well as source checkouts. They can be loaded and exported like any other preset, but they are protected from delete/overwrite inside the theme library. If you want to customize one, load it and save a copy under a new name.

## What It Covers

The GUI builder now exposes styling controls for the full app surface, including:

- typography
- panels, surfaces, and workspace canvases
- borders, group titles, and compact grouped frames
- buttons and round help buttons
- hover, pressed, checked, and disabled states
- inputs and focus styling
- placeholder text
- checkbox and radio indicators
- tables, lists, row hover states, and selection colors
- menus, tab strips, tabs, tab panes, dock titles, toolbar/status chrome, and header chrome
- scrollbars, progress bars, progress text, and related borders
- geometry values such as font sizes, radii, border width, padding, help-button size, and scrollbar thickness

## Builder Structure

The Theme page is split into:

- `Saved Themes`
  - load, save, delete, import, export, and reset theme drafts
  - includes packaged starter themes plus your own saved copies
  - optional real-time live preview across the running app
- `Typography`
  - application font
  - base font size
  - dialog title size
  - section title size
  - secondary text size
- `Surfaces`
  - window, workspace canvas, panel, group-title, compact-group, border, accent, selection, tooltip, overlay, and helper-text colors
- `Buttons`
  - normal, hover, pressed/checked, disabled, and round help-button states
- `Inputs`
  - default, focus, disabled, placeholder, and indicator styling
- `Data Views`
  - tables, lists, selection, hover, scrollbars, and progress bars including progress text and borders
- `Navigation`
  - menubar, toolbars, status bars, headers, dock titles, tab strips, tabs, and tab panes
- `Advanced QSS`
  - for the remaining cases that are better handled with handwritten selectors

## Live Preview

The Theme page includes dedicated preview panes with real controls. The preview automatically follows the active builder section so you only see the relevant control family instead of one crowded all-in-one sample. You can:

- hover and click buttons
- focus fields
- inspect disabled controls
- switch tabs
- inspect tables, lists, scrollbars, and progress bars

If you enable `Preview changes across the app while editing`, the running application updates in real time while the dialog is open. Canceling the settings dialog restores the original theme automatically.

## Automatic vs Explicit Values

Many state fields accept an empty value. When left empty, the theme engine derives a sensible value from the primary palette. Examples:

- `Button Hover Background` can derive from `Button Background`
- `Help Button Background` can derive from `Accent`
- `Input Focus Border` can derive from `Accent`
- `Menu Selected Background` can derive from `Accent`

This keeps the builder flexible: users can fully define every state, or set only the important anchor colors and let the rest derive automatically.

## Advanced QSS

Advanced QSS is still available, but it is now positioned as the last layer, not the primary workflow.

The editor includes:

- syntax-aware autocomplete
- full selector and rule-template insertion
- pseudo-state and subcontrol completion
- safe object-name reference insertion
- a live selector catalog harvested from open windows and dialogs

Recommended workflow:

1. Use the visual builder first.
2. Open the window or dialog you want to target.
3. Refresh the selector catalog.
4. Add only the remaining custom selectors in Advanced QSS.

## Preset Portability

Theme drafts can be exported as JSON and imported into another installation. The export format stores:

- the theme schema version
- the preset name
- the full theme payload

This makes it practical to share themes across machines without editing raw QSS.
