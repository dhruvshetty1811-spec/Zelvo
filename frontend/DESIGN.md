# ZELVO visual direction

## Brief

Replace the rejected navy/mint direction and rounded geometric type with a more distinctive identity. The interface explains predictive emergency mobility and lets evaluators run a matched SUMO comparison.

## System

White #FFFFFF, ink #202020, map grey #EEEFEB, and rule grey #E3E3DF. The entire interface is monochrome. Signal states use explicit G/Y/R characters with contrasting fills rather than color alone.

Arial/Helvetica grotesk typography replaces Outfit and DM Sans. Large, tightly spaced display type provides the opening gesture. Supporting type uses normal spacing and restrained weights. No remote fonts are required.

## Composition

The opening is a single oversized Make way. headline, followed by a two-column introduction and a looping recorded SUMO replay. The preview is an actual observed ZELVO run on the local Bengaluru network, sampled at 0.4 seconds with interpolation, running at 3x speed. It is labeled recorded, has pause/restart controls, pauses offscreen, and respects reduced motion. The source replay is 160 KB and starts without allocating simulation workers.

Evidence bars deliberately use white and mid-grey against the dark section; lengths retain the actual 144.2s and 76.6s relationship.

Measured outcomes sit beneath the map. The technology section pairs a three-state interactive corridor illustration with expandable explanations. A dark evidence section compares measured journey durations; conditions and ordinary-traffic impact remain inspectable. The invitation opens the actual experiment.

The demo first presents traffic density, seed, and optional settings. Run comparison starts two actual workers and automatically opens an edge-to-edge, full-viewport pair of maps. Browser fullscreen is requested on launch where supported; the viewport view works when fullscreen is unavailable. Every map canvas fills its half of the entire screen. Headers, playback, metrics and the measured result float above the maps. On phones the maps divide the full screen vertically. Stop cancels active work and returns focus to the setup heading. The top Change settings action is removed. Playback occupies its own overlay lane above both map headings, with no overlap.

Roads, routes, signals and vehicle markers use stronger strokes. Black ambulance markers have a white cross. Metrics and controls have larger, heavier type. The baseline route stays grey; ZELVO priority is black. No permanent result or header row reduces the map canvas.

## Critique and corrections

The previous iteration changed the palette while retaining a common split-hero composition, floating labels, and rounded product cards. This version replaces the composition and stylesheet rather than accumulating overrides. The only major display gesture is the large opening headline. The map is flat, without perspective, glow, glass or decorative orbits.

Desktop and mobile screenshots are reviewed. The mobile map keeps both dispatch and hospital within the illustration. The comparison remains stacked on narrow screens. Keyboard focus is visible, the skip link is visually hidden until focused, and reduced-motion settings disable transitions.

## Integrity

46.9% is a curated simulation result, not a citywide estimate or a clinical claim. Source conditions, safety observations, ordinary-traffic cost, and downloadable evidence remain available. No fabricated customers or live telemetry. Backend behavior and observed vehicle interpolation remain intact.

## Landing-page story

The copy begins with the person waiting to reach care, then states the problem: a siren and a green light cannot create space in a blocked queue. A dedicated problem/solution section explains how preparing signals ahead gives traffic time to move. Three plain-language steps explain observation, preparation and coordination. Measured simulation results follow the explanation, with ordinary-traffic costs and limits retained in the expandable evidence disclosure. The final invitation asks visitors to choose traffic density and watch two journeys side by side.

## Signal colors and problem statement

Signal markers now use red (#DC2626), amber (#F59E0B) and green (#16A34A) in the shared canvas renderer, covering the landing replay and both live comparison maps. G/Y/R letters remain visible; unavailable states are neutral. The rest of the interface retains its black-and-white palette.

The problem section emphasizes the 2-in-10 ambulance-patient mortality figure with visible attribution to RADHEE's Give Way to Ambulance page (https://radhee.com/projects/give-way-to-ambulance/). The page identifies it as a historical finding from research cited as 2013, rather than a current national estimate or a mortality rate caused exclusively by traffic. The solution is described directly as preparing a green window before arrival, with queue clearance, downstream space and enforced signal transitions explained underneath.

## Persistent home navigation

Back to home is now a persistent top-left overlay in the side-by-side demo. It is independent of measured arrivals, audit completion and replay position. On narrow screens the baseline heading sits below that navigation lane. Returning home exits native fullscreen and restores page scrolling; the live hook cancels any unfinished session on unmount. Browser checks cover completed and pre-arrival states at desktop and phone sizes.

## Expanded journey and camera

Preserve Arial, white #FFFFFF, ink #202020, muted #707070, map ground #E9E9E9, and borders #D4D4D4. Signal colors retain their meaning. The maps remain the full viewport; each gets compact camera controls at its edge and a small route overview. Default to following each ambulance at the same geographic scale. Overview shows the complete route; zoom and drag let the viewer inspect junctions. Both worlds still use one simulation clock.

Layout: `[home / playback / fullscreen]` above `[baseline map | ZELVO map]`, with camera tools beside each map and metrics below. On mobile the maps stack and camera tools sit beside the heading. Keep controls left aligned and keyboard operable. The defining interaction is watching each ambulance traverse a real longer corridor, with its place on the full journey visible in the inset.

Review: merely fitting a six-kilometre route into the previous map would make vehicles and junctions smaller. Follow mode addresses that problem; the inset preserves context. No decorative panels or new palette. The original reference result remains tied to its original scenario; the expanded route has independent measurements.


## Curated rush-hour default

Default to the independently replayed 2.44 km / 10-controller preset. Preserve the 6.15 km exploration and original reference choices. Density counts come from selected network metadata, so the interface reflects actual scheduled demand. State the simulated hospital destination before launch; use its name on both maps. Display measured live savings, without a forced percentage or modified presentation clock. The landing's original 46.9% reference remains explicitly tied to its own evidence.
