# Theme Builder Guide

ISRC Catalog Manager includes a full visual theme builder so the application can be tailored without requiring hand-written QSS for every change.

The goal is simple: most appearance work should be possible from the GUI, while Advanced QSS remains available for the final edge cases.

## What The Theme Builder Covers

The builder now exposes the full visible surface of the application, including:

- application typography
- window and workspace canvases
- panel and grouped-container surfaces
- media badge icons for stored audio and image BLOBs
- buttons and help buttons
- hover, pressed, checked, and disabled states
- inputs, placeholders, and focus styling
- tables, lists, headers, selections, and row hovers
- progress bars, scrollbars, and status chrome
- menus, toolbars, dock titles, headers, tab bars, tabs, and tab panes
- geometry settings such as font sizes, padding, radii, border width, help-button size, and scrollbar thickness

This is intended to give the user real visual control without turning every theme change into a stylesheet engineering task.

## Bundled Starter Themes

Every build ships with a starter library of professionally prepared presets:

- Apple Light
- Apple Dark
- High Visibility
- Aeon Emerald Gold
- Subconscious Cosmos
- VS Code Dark
- Pastel Studio

These presets are packaged with the application itself, so they are available in both source checkouts and packaged binaries. They can be loaded immediately, exported for sharing, and used as a foundation for custom presets.

Bundled starter themes are protected from deletion or in-place overwrite. If you want to customize one, load it and save a copy under a new name.

## Builder Structure

The visual builder is organized into focused sections:

### Typography

Control the overall tone and readability of the app through:

- application font family
- base font size
- dialog title size
- section heading size
- supporting text size

### Surfaces

This section controls the major planes and structural backgrounds of the UI, including:

- window background
- workspace canvas
- panel background
- compact grouped surfaces
- group-title text
- borders
- overlays
- tooltips
- supporting and hint text
- accent and selection surfaces

### Buttons

Theme normal buttons and round help buttons with full state coverage:

- default
- hover
- pressed
- checked
- disabled

### Blob Icons

The builder also includes a dedicated <strong>Blob Icons</strong> section for the small badges shown when records contain stored audio or image BLOB data.

This area is intentionally separate from theme presets because it controls the meaning of media indicators, not the surrounding chrome.

You can choose:

- a separate global icon for stored audio
- a separate global icon for stored images
- platform-native system icons supplied through Qt
- standardized emoji options
- custom imported images that are scaled down and compressed into the profile database

Custom `blob_audio` and `blob_image` columns can either inherit these global defaults or define their own field-specific icon from the same picker.

### Inputs

Control editor surfaces and state feedback such as:

- input background and text
- focus border
- disabled state
- placeholder text
- checkbox and radio indicators

### Data Views

This section handles the catalog’s heavy-use surfaces:

- table background
- table text
- alternate rows
- row hover
- selected rows
- headers
- scrollbars
- progress bars
- progress text and border

### Navigation

Style the surrounding application chrome, including:

- menu bar and popup menus
- toolbar and status bar
- dock and header surfaces
- tab buttons
- tab bar background
- tab pane background and border

### Advanced QSS

Advanced QSS remains available for precise selector work, but it now sits on top of a much deeper visual builder instead of compensating for missing basics.

## Live Preview

The builder includes a focused live preview system. Instead of showing every widget family at once, the preview adapts to the currently selected builder tab:

- typography previews show text hierarchy and text-bearing controls
- button previews show interaction states
- input previews show fields and indicators
- navigation previews show tabs, menus, headers, and chrome
- data view previews show lists, tables, scrollbars, and progress surfaces

This keeps the preview clear and makes it easier to judge the effect of each change.

An optional live mode can also apply the draft theme across the running application while you edit. Canceling the settings dialog restores the previous theme automatically.

## Automatic Versus Explicit Styling

Not every state has to be defined manually.

Many theme fields can remain empty and be derived automatically from anchor colors such as the accent, button background, or panel background. This keeps the builder flexible:

- beginners can set a few core colors and let the rest derive sensibly
- advanced users can override every visible state explicitly

The same principle applies to media badges:

- use global audio and image icon defaults for consistency
- override individual custom BLOB columns only when a field needs its own visual language

## Advanced QSS And Selector Reference

When a visual control still is not enough, the advanced editor provides:

- context-aware autocomplete
- selector completion
- pseudo-state and subcontrol completion
- safe object-name insertion
- rule-template insertion
- a live selector reference harvested from currently open windows and dialogs

This lets advanced users finish the last few percent of theme customization without guesswork.

## Design Philosophy

The theme builder is not meant to be a novelty panel. It is intended to make the application feel owned:

- closer to your brand
- easier to read
- more comfortable over long sessions
- more accessible for different visual needs

That is why the builder now covers the full application surface, starter themes ship with the app, media badge icons can be configured visually, and Advanced QSS is positioned as the final layer rather than the starting point.
