# Driver app preview

Audience: an ambulance driver selecting a hospital and following a trip. This is an interactive prototype with simulated location and signal status, independent of the SUMO comparison.

Palette: canvas #FFFFFF, ink #171717, secondary #737373, map #EAEAEA, road #FFFFFF, borders #DEDEDE. Keep every control and map marker monochrome. Arial and system sans-serif provide familiar, legible mobile typography. Large instructions and a single black primary action carry the hierarchy.

Layout: a small page header above a centered iPhone-shaped device on an otherwise white canvas. The device has a restrained metallic edge, side buttons, rounded screen, status bar and Dynamic Island. Inside, road geometry fills the screen behind a destination sheet; active navigation replaces search with a large maneuver and compact trip controls.

`[page brand / interactive preview] -> [status / app header | road map | destination or trip sheet | home indicator] -> [demo speed / simulation disclosure]`

Review before implementation: avoid turning this into another marketing landing page. The phone is the focal point; omit hero claims, ornamental cards and accent colors. Use real local OSM road shapes to connect it to ZELVO, but clearly disclose that every destination uses an illustrative route. Keep phone controls at least 44px, support keyboard search, back, cancellation confirmation and an honest arrival state. On a narrow browser, retain the phone outline and allow the page to scroll rather than shrinking text.


Visual critique: the first overview compressed the road into a narrow strip and hid the destination behind the sheet. Home now focuses on the ambulance's neighborhood, while route preview fits between the top bar and the measured sheet position. Active navigation uses the same visible-map bounds. Secondary text was darkened to #737373, and destination search uses a 16px font. The maneuver distance follows the next signal location along the illustrative route rather than a fixed placeholder. End-trip confirmation traps keyboard focus, Escape restores it, and a new trip returns focus to search. Reduced-motion preferences disable transitions; essential location movement remains part of the user-started trip and can be paused.
