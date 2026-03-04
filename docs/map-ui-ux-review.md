# UI/UX Review: `index.html` / `map.html`
*Original review: 2026-02-20 | Updated: 2026-03-04*

## Audience
Policy analysts and housing advocates reviewing residential development capacity in Arlington neighborhoods. They are not GIS experts. They need to quickly answer: *"Which parcels have unused capacity, how much, and what is it worth?"* They may present these maps to colleagues or decision-makers.

---

## What Is Working Well

- **Color palette** — Wong colorblind-safe set (#009E73 / #56B4E9 / #F0E442 / #E69F00 / #D55E00) is correctly implemented and distinguishable under protanopia and deuteranopia.
- **Click-to-select parcel panel** — persistent sidebar panel with dismiss button and gold highlight is well-implemented for the core workflow.
- **Index page hover panel** — showing neighborhood detail on hover and restoring aggregate summary on mouse-leave is the right interaction model for an overview map.
- **URL parcel deep-linking** (`?parcel=23026006`) — allows sharing a direct link to a specific parcel.
- **SRI hashes** on CDN assets — good security practice.
- **Disclaimer** — present on both pages, styled distinctly with a left red border, correctly worded.
- **Neighborhood navigation dropdown** — sensible jump-to pattern without cluttering the sidebar.

---

## Issues (ordered by impact)

### High Priority

**1. Legend quintile labels are ambiguous (`generate_homepage.py`)**
Labels read "Top quintile available GFA" without explaining whether "top" is desirable. A non-specialist cannot tell if the darkest color is good or bad.
- Fix: "Most unused capacity (top 20%)" / "Least unused capacity (bottom 20%)" with a caption: "Color shows total unused floor area capacity (among analyzed neighborhoods)"

**2. Value range split across two stat boxes (`generate_map.py`)**
"Aggregate Value (Low)" and "Aggregate Value (High)" appear as separate boxes. They represent a single estimate range and should read as a unit.
- Fix: Combine into a single "Est. Value of Unused Rights" box displaying "$69.1M – $94.2M"

**3. Total GFA formatted as raw integer (`generate_map.py`)**
"1,081,246 SF" in an 18px stat box requires counting digits. Use an abbreviated formatter.
- Fix: `fmtGfa()` function abbreviating to "1.1M SF"; apply to total and median per-parcel stats

**4. Jargon in user-facing labels (both files)**
Labels like "Improvement $/SF", "Available GFA", "Underdeveloped", and "not_applicable" are pipeline terminology not meaningful to the policy audience.
- Proposed replacements:
  - "Available GFA" → "Unused floor area"
  - "Improvement $/SF" → "Avg. construction cost ($/SF)"
  - "Underdeveloped" → "Parcels below zoning max"
  - "Near capacity" → "Parcels near zoning max"
  - "Vacant buildable" → "Vacant buildable lots"
  - "not_applicable" in confidence breakdown → "No unused capacity"
  - "Development Potential" (tooltip heading) → "Development Capacity"

### Medium Priority

**5. Calibration filter hint text too small and unclear (`generate_map.py`)**
"click to filter" is rendered at 10px gray — effectively invisible. The word "filter" doesn't describe what happens on the map.
- Fix: 11px; text → "click to highlight on map" / "click to clear"

**6. Nav dropdown placeholder ambiguous (`generate_map.py`)**
Placeholder shows the current neighborhood name, making it look like a selectable item rather than a navigation control.
- Fix: Placeholder text → "Jump to another neighborhood..."

**7. Back link unclear (`generate_map.py`)**
"← Arlington" at 12px is ambiguous (city? a section?).
- Fix: "← All neighborhoods" at 13px bold

**8. Sidebar section order (`generate_map.py`)**
Status breakdown is separated from the legend. Zoning Districts is high in the sidebar despite being low-priority context.
- Fix: Move Status breakdown adjacent to Legend; move Zoning Districts toward the bottom.

**9. Stat box label font size (both files)**
`.stat-box .label` at 11px uppercase is at the lower edge of comfortable reading.
- Fix: 11px → 12px

**10. "N/A homes" display bug (`generate_map.py`)**
When sample count is null, renders as "N/A homes" — the unit suffix should be suppressed.
- Fix: Only append "homes" when value is non-null.

### Accessibility (Lower Priority)

**11. Neighborhood list rows not keyboard accessible (`generate_homepage.py`)**
`div.nb-row` elements are click-only. Keyboard users cannot tab to or activate them.
- Fix: Add `tabindex="0"`, `role="button"`, `aria-label`, `keydown` Enter/Space handler; set inner `<a>` to `tabindex="-1"` to avoid duplicate tab stop.

**12. Calibration filter heading not keyboard accessible (`generate_map.py`)**
The filterable heading has no keyboard affordance.
- Fix: Add `tabindex="0"`, `role="button"`, `aria-pressed`, `keydown` handler.

**13. Map div missing ARIA (`generate_map.py`)**
`<div id="map">` has no ARIA role or label.
- Fix: Add `role="application"` and `aria-label="Parcel map"`.

---

## Out of Scope / Future

- Responsive/mobile layout — 380px fixed sidebar breaks below ~800px; requires structural changes
- Leaflet keyboard parcel navigation — requires a plugin
- `prefers-reduced-motion` support
- CDN offline dependency — `unpkg.com` means pages fail offline; architectural constraint

---

## Status

| # | Issue | Status |
|---|-------|--------|
| 1 | Legend quintile label clarity | Open |
| 2 | Value range as single box | Open |
| 3 | GFA abbreviated formatter | Open |
| 4 | Jargon in user-facing labels | Open |
| 5 | Calibration hint text | Open |
| 6 | Nav dropdown placeholder | Open |
| 7 | Back link text | Open |
| 8 | Sidebar section order | Open |
| 9 | Stat box label font size | Open |
| 10 | "N/A homes" bug | Open |
| 11 | Neighborhood rows keyboard accessible | Open |
| 12 | Calibration filter keyboard accessible | Open |
| 13 | Map div ARIA | Open |
