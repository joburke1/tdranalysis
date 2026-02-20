# UI/UX Review: `map.html` / `generate_map.py`
*Reviewed: 2026-02-20*

## Audience
Policy analysts and housing advocates reviewing residential development capacity in Arlington neighborhoods. They are not GIS experts. They need to quickly answer: *"Which parcels have unused capacity, how much, and what is it worth?"* They may present these maps to colleagues or decision-makers.

---

## Top 5 Issues (fix first)

**1. Red means opportunity — semantic inversion (`generate_map.py` lines 403–405)**
The darkest red (`#67000d`) marks parcels with the *highest development potential*. Red universally signals danger/stop/negative. For a policy analyst advocating for TDR, these parcels are the *most desirable targets* — they should be the most visually appealing, not alarming. This is the most critical issue because it actively misleads anyone who reads maps intuitively.

**2. Dollar totals are unformatted millions (`generate_map.py` line 330, sidebar HTML ~lines 247–255)**
`fmtD()` formats as `$145,678,234`. In the "Assessment Values" stat boxes, aggregate land and improvement values are neighborhood-scale numbers ($50M–$500M range). These overflow their small containers and are hard to parse. There is no abbreviation function — `$145.7M` reads instantly; `$145,678,234` requires counting digits.

**3. No click-to-lock tooltip (`generate_map.py` lines 480–495)**
Parcel detail is hover-only. The tooltip disappears the moment the cursor leaves the parcel. A user comparing two parcels, writing a report, or taking a screenshot has no way to hold a parcel's data visible. This is a fundamental usability gap for the core workflow.

**4. Sections ordered by data availability, not user priority (sidebar HTML ~lines 222–298)**
Section order: Overview → Assessment Values → Unused Development Potential → Neighborhood Calibration → Zoning → Status → Confidence → Legend. The most policy-relevant section — *aggregate value of unused rights* — is third. Assessment values (the total value of all property) comes before unused potential, which buries the headline finding.

**5. "not_applicable" and "fallback" are pipeline jargon exposed to users (`generate_map.py` lines 350, confidence breakdown JS)**
The confidence breakdown shows `not_applicable` as a raw enum value. The neighborhood rate shows `$185/SF (fallback)` when the sample is insufficient. These terms are meaningful to developers but confusing to the policy audience.

---

## Full Audit

### 2.1 Information Hierarchy — NEEDS WORK

| Check | Finding |
|-------|---------|
| Primary message | No single hero stat. The page communicates everything equally. |
| Visual weight | Stat values (18px bold) compete with the h1 neighborhood name (also 18px). |
| Grouping | Sections are well-separated with h2 borders. Good. |
| Progressive disclosure | All data dumped in sidebar. Tooltip provides appropriate detail-on-hover. |
| Labels | Most are clear. "Underdeveloped + Vacant" is awkward; "not_applicable" is technical. |
| Title | "TDR Analysis: Alcova Heights" — "TDR" is unexplained acronym for non-specialists. |

### 2.2 Color — FAIL

| Check | Finding |
|-------|---------|
| Semantic consistency | **FAIL.** Dark red = high opportunity. Red = danger in universal convention. Inverted. |
| Sequential scale | Single red gradient for underdeveloped parcels: technically sequential, but wrong hue. |
| Diverging data | Not applicable — no single midpoint in this data. |
| Categorical distinction | Near-capacity (`#4292c6`) and overdeveloped (`#08519c`) are both blue, distinguished only by lightness. Marginal. |
| Contrast ratios | Sidebar: `#e0e0e0` on `#1a1a2e` ≈ 13.4:1 PASS. Labels `#999` on `#16213e` ≈ 5.9:1 PASS. Tooltip highlight `#c1121f` on white ≈ 5.1:1 PASS (barely). |
| Colorblind safety | **FAIL.** Red (underdeveloped) and green (vacant) are adjacent categories. ~8% of men cannot distinguish these. No redundant encoding compensates. |
| Harmony | Dark sidebar + light map works. Swatch colors in legend look coherent. |

### 2.3 Typography & Spacing — NEEDS WORK

| Check | Finding |
|-------|---------|
| Font stack | System font stack. Excellent. |
| Size hierarchy | h1=18px, h2=14px, body=13px, label=11px, stat-value=18px. h1 and stat values are the same size — no title dominance. |
| Body text size | 13px sidebar body is slightly small for comfortable reading of dense stats. |
| Line height | 1.5 on sidebar — good. 1.4 on tooltip — acceptable. |
| Whitespace | Tight. stat-box padding is 10px; section margins are 16px. The sidebar is noticeably dense. |
| Alignment | Consistent left-alignment. Grid layout is appropriate. |

### 2.4 Data Presentation — FAIL (dollar formatting)

| Check | Finding |
|-------|---------|
| Number formatting | **FAIL.** `fmtD()` shows full integers. `$145,678,234` in a 14px box is unreadable at a glance. No M/K abbreviation exists. |
| N/A handling | `fmtD(null)` returns `'N/A'` — consistent. PASS. |
| Sort order | Breakdowns sorted by count descending. Good. |
| Units | Available GFA shown as "123,456 SF" — units present. PASS. |
| Precision | `toFixed(1)` for percentages — appropriate. PASS. |
| Raw enum values | `not_applicable` and `(fallback)` exposed to users. |

### 2.5 Interactivity — NEEDS WORK

| Check | Finding |
|-------|---------|
| Affordances | No visual cue that parcels are hoverable (no cursor change). |
| Feedback | Hover highlight (weight:3, fillOpacity:0.85) is good. |
| Persistent detail | **No click-to-lock.** Hover-only — detail disappears immediately. |
| Navigation | Fits to bounds on load. No reset-view button. |
| Defaults | 20px fitBounds padding is tight — minor. |

### 2.6 Responsiveness — NEEDS WORK

| Check | Finding |
|-------|---------|
| Viewport flexibility | Sidebar hardcoded at 380px. At 1024px, map gets 644px — workable but tight. |
| Small screens | No `@media` queries. Below ~800px the layout breaks. |
| Long string overflow | No truncation on tooltip addresses — low risk. |

### 2.7 Accessibility — FAIL

| Check | Finding |
|-------|---------|
| Keyboard navigation | No keyboard access to parcel features. Leaflet limitation. |
| Color-only encoding | Status categories have no redundant encoding for colorblind users. |
| ARIA | `<div id="map">` has no `aria-label`. Legend swatches are purely visual. |
| Text scaling | 11px labels will be marginal at 200% browser zoom. |

### 2.8 Performance — NEEDS WORK

| Check | Finding |
|-------|---------|
| Asset size | GeoJSON embedded inline. Fine for small neighborhoods; could exceed 5MB for 500+ parcels. |
| CDN dependency | Leaflet loaded from `unpkg.com`. Described as "self-contained" but requires internet access. |
| Render blocking | Leaflet `<script>` in `<head>` without `defer`. Minor. |

---

## Recommended Changes (ordered by impact)

### 1. Fix color semantics — replace red gradient with blue/teal for opportunity
*`generate_map.py` lines 379–405 (`getColor` function)*

Replace the red gradient with a blue/teal scale. Keep green for vacant, grey for excluded.
- Low potential → light blue (`#c6dbef`)
- Moderate potential → medium blue (`#4292c6`)
- High potential → dark blue (`#084594`)
- Overdeveloped → amber/orange (`#d94801`) to signal "over limit" as a warning

This also resolves the red-green colorblind failure since blue and green are distinguishable under deuteranopia.

### 2. Add dollar abbreviation formatter
*`generate_map.py` line 330 (after existing `fmtD`)*

```javascript
function fmtM(n) {
    if (n == null) return 'N/A';
    if (Math.abs(n) >= 1e9) return '$' + (n/1e9).toFixed(1) + 'B';
    if (Math.abs(n) >= 1e6) return '$' + (n/1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return '$' + (n/1e3).toFixed(0) + 'K';
    return '$' + n.toFixed(0);
}
```
Use `fmtM` for the four aggregate dollar stats in the sidebar; keep `fmtD` for per-parcel tooltip values.

### 3. Add click-to-lock parcel detail panel
*`generate_map.py` lines 480–495 (`onEachFeature`)*

Add a click handler that populates a pinned `#selected-parcel` div at the top of the sidebar. When a parcel is clicked, inject its detail there and add a visible "selected" ring around it. Keep visible until another parcel is clicked or dismissed.

### 4. Reorder sidebar sections by policy priority
*`generate_map.py` lines 258–298 (sidebar HTML)*

New order:
1. Overview
2. Unused Development Potential ← move up
3. Aggregate Value (est_value_low / est_value_high) ← promote as headline
4. Neighborhood Calibration
5. Assessment Values ← demote (context, not finding)
6. Zoning Districts
7. Development Status
8. Valuation Confidence
9. Legend
10. Disclaimer

### 5. Fix jargon in user-facing text
*`generate_map.py` lines 304 (subtitle), 350 (rate display), confidence JS*

- Subtitle: spell out "Transfer of Development Rights (TDR) Analysis"
- Fallback rate: `'$185/SF (fallback)'` → `'$185/SF (estimated — limited local data)'`
- Confidence breakdown: map `not_applicable` → `"No unused capacity"` in JS before rendering

### 6. Increase body text size and h1 prominence
*`generate_map.py` lines 19, 21*

- `#sidebar` font-size: `13px` → `14px`
- `#sidebar h1` font-size: `18px` → `22px`
- `.stat-box` padding: `10px` → `12px`

### 7. Expand fitBounds padding
*`generate_map.py` line 499*

`{ padding: [20, 20] }` → `{ padding: [40, 40] }` — more spatial context around neighborhood on initial load.
