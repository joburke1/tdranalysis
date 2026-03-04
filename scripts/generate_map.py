"""
Map Generator for TDR Analysis Results
=======================================

Generates a self-contained HTML file with an interactive Leaflet map
showing parcel-level development potential analysis results.

The GeoJSON data is embedded inline so the HTML can be opened directly
from the filesystem — no web server required.

Usage
-----
# Generate map for a specific neighborhood:
    python scripts/generate_map.py --neighborhood "Alcova Heights"

# Generate from a specific GeoJSON file:
    python scripts/generate_map.py --geojson data/results/alcova_heights/alcova_heights_analysis.geojson
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
import textwrap
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("generate_map")


# Exclusion reasons that mean the parcel is not in an in-scope residential zone.
# These are NOT counted toward the "total zoned residential" denominator.
_ZONING_EXCLUSION_REASONS = {
    "Non-residential zoning",
    "Zoning district out of scope (not R-5/R-6/R-8/R-10/R-20)",
}


def _load_valuation_params() -> dict:
    """Load valuation_params.json from config directory. Returns defaults if not found."""
    config_path = _PROJECT_ROOT / "config" / "valuation_params.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("Could not load valuation_params.json; using built-in defaults")
        return {}


def _find_analyzed_neighborhoods(results_dir: Path) -> list[dict]:
    """
    Scan results_dir for analyzed neighborhoods.

    A directory is considered analyzed if it contains a ``*_analysis.geojson``
    file.  Returns a list of ``{name, slug}`` dicts sorted by name.
    """
    neighborhoods = []
    if not results_dir.exists():
        return neighborhoods
    for subdir in sorted(results_dir.iterdir()):
        if not subdir.is_dir():
            continue
        geojson_files = list(subdir.glob("*_analysis.geojson"))
        if not geojson_files:
            continue
        try:
            with open(geojson_files[0], "r", encoding="utf-8") as f:
                data = json.load(f)
            features = data.get("features", [])
            if features:
                name = features[0]["properties"].get("neighborhood", subdir.name)
            else:
                name = subdir.name.replace("_", " ").title()
        except Exception:
            name = subdir.name.replace("_", " ").title()
        neighborhoods.append({"name": name, "slug": subdir.name})
    return sorted(neighborhoods, key=lambda x: x["name"])


def _compute_summary(geojson_data: dict, excluded_data: dict | None = None, valuation_params: dict | None = None) -> dict:
    """Compute summary statistics from GeoJSON features."""
    features = geojson_data.get("features", [])
    total = len(features)

    # Aggregate values
    total_land_value = 0
    total_improvement_value = 0
    total_available_gfa = 0
    total_est_low = 0
    total_est_high = 0
    parcels_with_value = 0
    zoning_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    available_gfa_values: list[float] = []
    vacant_count = 0
    underdeveloped_count = 0
    near_capacity_count = 0
    overdeveloped_count = 0

    # Neighborhood rate (same for all parcels)
    neighborhood_rate_median = None
    neighborhood_rate_low = None
    neighborhood_rate_high = None
    neighborhood_rate_sample = None
    neighborhood_name = None

    for f in features:
        p = f.get("properties", {})

        if neighborhood_name is None:
            neighborhood_name = p.get("neighborhood", "Unknown")
            neighborhood_rate_median = p.get("neighborhood_imp_rate_median")
            neighborhood_rate_low = p.get("neighborhood_imp_rate_low")
            neighborhood_rate_high = p.get("neighborhood_imp_rate_high")
            neighborhood_rate_sample = p.get("neighborhood_imp_rate_sample")

        # Zoning
        zd = p.get("zoning_district", "Unknown")
        zoning_counts[zd] = zoning_counts.get(zd, 0) + 1

        # Status
        status = p.get("development_status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "vacant":
            vacant_count += 1
        elif status == "underdeveloped":
            underdeveloped_count += 1
        elif status == "near-capacity":
            near_capacity_count += 1
        elif status == "overdeveloped":
            overdeveloped_count += 1

        # Values
        lv = p.get("land_value")
        if lv is not None:
            total_land_value += lv
        iv = p.get("improvement_value")
        if iv is not None:
            total_improvement_value += iv

        avail = p.get("available_gfa_sf")
        if avail is not None and avail > 0:
            total_available_gfa += avail
            available_gfa_values.append(avail)

        el = p.get("est_value_low")
        eh = p.get("est_value_high")
        if el is not None and eh is not None:
            total_est_low += el
            total_est_high += eh
            parcels_with_value += 1

    median_avail_gfa = 0
    if available_gfa_values:
        s = sorted(available_gfa_values)
        median_avail_gfa = s[len(s) // 2]

    # Count in-scope excluded parcels (those in a qualifying residential zone but
    # filtered out for data or eligibility reasons, not zoning-out-of-scope).
    in_scope_excluded = 0
    excluded_count = 0
    if excluded_data:
        for f in excluded_data.get("features", []):
            excluded_count += 1
            reason = f.get("properties", {}).get("exclusion_reason", "")
            if reason not in _ZONING_EXCLUSION_REASONS:
                in_scope_excluded += 1

    total_residential_eligible = total + in_scope_excluded
    pct_included = round(total / total_residential_eligible * 100, 1) if total_residential_eligible > 0 else 0

    # Identify parcels used for neighborhood calibration.
    # Mirrors the criteria in estimate_neighborhood_improvement_rate().
    # Thresholds are loaded from config/valuation_params.json with safe defaults.
    if valuation_params is None:
        valuation_params = _load_valuation_params()
    _cal = valuation_params.get("neighborhood_rate_calibration", {})
    _lookback = _cal.get("lookback_years", 10)
    _CALIBRATION_YEAR_CUTOFF = datetime.date.today().year - _lookback
    _CALIBRATION_IMP_THRESHOLD = float(_cal.get("min_improvement_value", 5_000.0))
    _fallback_rate = valuation_params.get("residential_improvement_value_per_sf", {}).get("fallback_value", 185)
    calibration_parcel_ids = [
        f["properties"]["parcel_id"]
        for f in features
        if (
            f["properties"].get("year_built") is not None
            and f["properties"]["year_built"] >= _CALIBRATION_YEAR_CUTOFF
            and f["properties"].get("improvement_value") is not None
            and f["properties"]["improvement_value"] > _CALIBRATION_IMP_THRESHOLD
        )
    ]

    return {
        "neighborhood": neighborhood_name,
        "total_parcels": total,
        "total_residential_eligible": total_residential_eligible,
        "excluded_count": excluded_count,
        "in_scope_excluded": in_scope_excluded,
        "pct_included": pct_included,
        "zoning_counts": zoning_counts,
        "status_counts": status_counts,
        "vacant_count": vacant_count,
        "underdeveloped_count": underdeveloped_count,
        "near_capacity_count": near_capacity_count,
        "overdeveloped_count": overdeveloped_count,
        "total_land_value": total_land_value,
        "total_improvement_value": total_improvement_value,
        "total_assessed_value": total_land_value + total_improvement_value,
        "total_available_gfa": total_available_gfa,
        "parcels_with_capacity": len(available_gfa_values),
        "median_available_gfa": median_avail_gfa,
        "total_est_low": total_est_low,
        "total_est_high": total_est_high,
        "parcels_with_value": parcels_with_value,
        "neighborhood_rate_median": neighborhood_rate_median,
        "neighborhood_rate_low": neighborhood_rate_low,
        "neighborhood_rate_high": neighborhood_rate_high,
        "neighborhood_rate_sample": neighborhood_rate_sample,
        "calibration_parcel_ids": calibration_parcel_ids,
        "fallback_improvement_rate": _fallback_rate,
    }


def generate_map_html(
    geojson_data: dict,
    excluded_data: dict | None = None,
    results_dir: Path | None = None,
    current_slug: str | None = None,
) -> str:
    """Generate a self-contained HTML string with embedded map."""
    valuation_params = _load_valuation_params()
    summary = _compute_summary(geojson_data, excluded_data, valuation_params=valuation_params)
    geojson_str = json.dumps(geojson_data)
    excluded_str = json.dumps(excluded_data) if excluded_data else "null"
    summary_str = json.dumps(summary)

    # Build navigation dropdown options
    if results_dir is not None:
        analyzed = _find_analyzed_neighborhoods(results_dir)
        current_name = summary.get("neighborhood", "")
        # First option shows current neighborhood as a non-navigating placeholder
        nav_options = f'<option value="" disabled selected>{current_name}</option>\n'
        for nb in analyzed:
            if nb["slug"] != current_slug:
                nav_options += f'        <option value="{nb["slug"]}">{nb["name"]}</option>\n'
    else:
        nav_options = '<option value="">Jump to neighborhood\u2026</option>'

    html = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Transfer of Development Rights (TDR) Analysis: NEIGHBORHOOD_NAME</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
          crossorigin="">
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
            crossorigin=""></script>
    <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; height: 100vh; }

    #sidebar {
        width: 380px; min-width: 380px; background: #1a1a2e; color: #e0e0e0;
        overflow-y: auto; padding: 20px; font-size: 14px; line-height: 1.5;
    }
    #sidebar h1 { font-size: 22px; color: #fff; margin-bottom: 4px; }
    #sidebar h2 { font-size: 14px; color: #8ecae6; margin: 16px 0 8px; border-bottom: 1px solid #333; padding-bottom: 4px; }
    #sidebar .subtitle { color: #999; font-size: 12px; margin-bottom: 16px; }

    .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
    .stat-box { background: #16213e; border-radius: 6px; padding: 12px; }
    .stat-box .label { font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 0.5px; }
    .stat-box .value { font-size: 18px; font-weight: 700; color: #fff; margin-top: 2px; }
    .stat-box .value.small { font-size: 14px; }
    .stat-box.wide { grid-column: 1 / -1; }

    .breakdown { margin: 8px 0; }
    .breakdown-row { display: flex; justify-content: space-between; padding: 3px 0; border-bottom: 1px solid #222; }
    .breakdown-row .bk-label { color: #ccc; }
    .breakdown-row .bk-value { color: #fff; font-weight: 600; }

    .legend { margin-top: 12px; }
    .legend-item { display: flex; align-items: center; gap: 8px; margin: 4px 0; font-size: 12px; }
    .legend-swatch { width: 20px; height: 14px; border-radius: 2px; border: 1px solid #555; flex-shrink: 0; }

    #selected-parcel {
        background: #16213e; border: 1px solid #8ecae6; border-radius: 6px;
        padding: 12px; margin-bottom: 12px; display: none; position: relative;
    }
    #selected-parcel .sp-dismiss {
        position: absolute; top: 6px; right: 8px; cursor: pointer;
        color: #999; font-size: 16px; line-height: 1; background: none; border: none;
    }
    #selected-parcel .sp-dismiss:hover { color: #fff; }
    #selected-parcel .sp-header { font-weight: 700; font-size: 14px; color: #fff; margin-bottom: 6px; padding-right: 20px; }
    #selected-parcel .sp-row { display: flex; justify-content: space-between; gap: 8px; padding: 2px 0; }
    #selected-parcel .sp-label { color: #999; font-size: 12px; }
    #selected-parcel .sp-value { color: #fff; font-weight: 600; font-size: 12px; }
    #selected-parcel .sp-highlight { color: #8ecae6; font-weight: 700; }

    .disclaimer { margin-top: 16px; padding: 10px; background: #2a1a1a; border-left: 3px solid #e63946; border-radius: 4px; font-size: 11px; color: #ccc; }

    #sidebar h2.filterable { cursor: pointer; user-select: none; }
    #sidebar h2.filterable:hover { color: #ffd700; }
    #sidebar h2.filterable .filter-hint { font-size: 10px; color: #666; font-weight: 400; margin-left: 6px; text-transform: none; letter-spacing: 0; }
    #sidebar h2.filterable.filter-active { color: #ffd700; border-bottom-color: #ffd700; }
    #sidebar h2.filterable.filter-active .filter-hint { color: #ffd700; }

    #map { flex: 1; }

    .parcel-tooltip {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 12px; line-height: 1.4; max-width: 320px;
    }
    .parcel-tooltip .tt-header { font-weight: 700; font-size: 13px; margin-bottom: 6px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
    .parcel-tooltip .tt-section { margin-top: 6px; }
    .parcel-tooltip .tt-section-title { font-weight: 600; color: #555; font-size: 11px; text-transform: uppercase; margin-bottom: 2px; }
    .parcel-tooltip .tt-row { display: flex; justify-content: space-between; gap: 12px; }
    .parcel-tooltip .tt-label { color: #666; }
    .parcel-tooltip .tt-value { font-weight: 600; text-align: right; }
    .parcel-tooltip .tt-highlight { color: #084594; font-weight: 700; }
    </style>
    </head>
    <body>
    <div id="sidebar">
        <div id="nav-bar" style="display:flex; align-items:center; gap:8px; margin-bottom:12px; padding-bottom:12px; border-bottom:1px solid #333;">
          <a href="../index.html" style="color:#8ecae6; text-decoration:none; font-size:12px; white-space:nowrap;">&#8592; Arlington</a>
          <select id="neighborhood-selector"
                  onchange="if(this.value) window.location.href='../'+this.value+'/map.html'"
                  style="flex:1; background:#16213e; color:#e0e0e0; border:1px solid #444; border-radius:4px; padding:4px; font-size:12px;">
            NAV_OPTIONS_PLACEHOLDER
          </select>
        </div>
        <h1 id="neighborhood-name"></h1>
        <div class="subtitle">Transfer of Development Rights Analysis</div>

        <div id="selected-parcel"></div>

        <h2>Overview</h2>
        <div class="stat-grid">
            <div class="stat-box">
                <div class="label">Parcels Analyzed</div>
                <div class="value" id="s-total"></div>
            </div>
            <div class="stat-box">
                <div class="label">With Unused Capacity</div>
                <div class="value" id="s-with-capacity"></div>
            </div>
            <div class="stat-box">
                <div class="label">Zoned Residential</div>
                <div class="value" id="s-residential-total"></div>
            </div>
            <div class="stat-box">
                <div class="label">Included in Analysis</div>
                <div class="value" id="s-pct-included"></div>
            </div>
            <div class="stat-box">
                <div class="label">Vacant Buildable</div>
                <div class="value" id="s-vacant"></div>
            </div>
        </div>

        <h2>Unused Development Potential</h2>
        <div class="stat-grid">
            <div class="stat-box wide">
                <div class="label">Total Available GFA</div>
                <div class="value" id="s-avail-gfa"></div>
            </div>
            <div class="stat-box">
                <div class="label">Median per Parcel</div>
                <div class="value small" id="s-median-gfa"></div>
            </div>
            <div class="stat-box">
                <div class="label">Parcels Valued</div>
                <div class="value" id="s-valued"></div>
            </div>
            <div class="stat-box">
                <div class="label">Aggregate Value (Low)</div>
                <div class="value small" id="s-val-low"></div>
            </div>
            <div class="stat-box">
                <div class="label">Aggregate Value (High)</div>
                <div class="value small" id="s-val-high"></div>
            </div>
        </div>

        <h2>Legend</h2>
        <div class="legend">
            <div class="legend-item"><div class="legend-swatch" style="background:#009E73"></div> High development potential</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#56B4E9"></div> Moderate potential</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#F0E442"></div> Low potential</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#E69F00"></div> Near capacity</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#D55E00"></div> Exceeds max GFA</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#888"></div> Excluded / no data</div>
        </div>

        <h2 class="filterable" id="calibration-header" onclick="toggleCalibrationFilter()" title="Click to highlight calibration homes on the map">Neighborhood Calibration<span class="filter-hint" id="calibration-filter-hint">click to filter</span></h2>
        <div class="stat-grid">
            <div class="stat-box">
                <div class="label">Improvement $/SF</div>
                <div class="value small" id="s-rate"></div>
            </div>
            <div class="stat-box">
                <div class="label">Sample Size</div>
                <div class="value" id="s-rate-sample"></div>
            </div>
        </div>

        <h2>Assessment Values</h2>
        <div class="stat-grid">
            <div class="stat-box">
                <div class="label">Total Land Value</div>
                <div class="value small" id="s-land"></div>
            </div>
            <div class="stat-box">
                <div class="label">Total Improvement Value</div>
                <div class="value small" id="s-improvement"></div>
            </div>
            <div class="stat-box wide">
                <div class="label">Total Assessed Value</div>
                <div class="value" id="s-assessed"></div>
            </div>
        </div>

        <h2>Zoning Districts</h2>
        <div class="breakdown" id="zoning-breakdown"></div>

        <h2>Development Status</h2>
        <div class="breakdown" id="status-breakdown"></div>

        <div class="disclaimer">
            <strong>Disclaimer:</strong> Valuation estimates are for TDR policy analysis only,
            not property appraisals. Improvement $/SF derived from recent construction in this
            neighborhood. All values should be independently verified before use in policy decisions.
        </div>
        <div style="margin-top:16px;padding-top:12px;border-top:1px solid #333;font-size:11px;color:#666;line-height:1.5;">
            <a href="https://github.com/joburke1/tdranalysis" style="color:#8ecae6;">Arlington Transfer of Development Rights Analysis</a>
            by <a href="https://www.linkedin.com/in/john-burke-arlingtonva/" style="color:#8ecae6;">John Burke</a>
            is marked <a href="https://creativecommons.org/publicdomain/zero/1.0/" style="color:#8ecae6;">CC0 1.0</a><img src="https://mirrors.creativecommons.org/presskit/icons/cc.svg" alt="Creative Commons" style="max-width:1em;max-height:1em;margin-left:.2em;vertical-align:middle;"><img src="https://mirrors.creativecommons.org/presskit/icons/zero.svg" alt="CC0 1.0 Universal Public Domain" style="max-width:1em;max-height:1em;margin-left:.2em;vertical-align:middle;">
        </div>
    </div>

    <div id="map"></div>

    <script>
    // --- Embedded data ---
    const geojsonData = GEOJSON_DATA_PLACEHOLDER;
    const excludedData = EXCLUDED_DATA_PLACEHOLDER;
    const summary = SUMMARY_DATA_PLACEHOLDER;

    // --- Helpers ---
    function fmt(n) { return n == null ? 'N/A' : n.toLocaleString('en-US', {maximumFractionDigits: 0}); }
    function fmtD(n) { return n == null ? 'N/A' : '$' + n.toLocaleString('en-US', {maximumFractionDigits: 0}); }
    function fmtM(n) {
        if (n == null) return 'N/A';
        if (Math.abs(n) >= 1e9) return '$' + (n/1e9).toFixed(1) + 'B';
        if (Math.abs(n) >= 1e6) return '$' + (n/1e6).toFixed(1) + 'M';
        if (Math.abs(n) >= 1e3) return '$' + (n/1e3).toFixed(0) + 'K';
        return '$' + n.toFixed(0);
    }
    function fmtPct(n) { return n == null ? 'N/A' : n.toFixed(1) + '%'; }

    // --- Populate sidebar ---
    document.getElementById('neighborhood-name').textContent = summary.neighborhood || 'Unknown';
    document.title = 'Transfer of Development Rights (TDR) Analysis: ' + (summary.neighborhood || 'Unknown');
    document.getElementById('s-total').textContent = fmt(summary.total_parcels);
    document.getElementById('s-with-capacity').textContent = fmt(summary.parcels_with_capacity);
    document.getElementById('s-residential-total').textContent = fmt(summary.total_residential_eligible);
    document.getElementById('s-pct-included').textContent = fmtPct(summary.pct_included);
    document.getElementById('s-vacant').textContent = fmt(summary.vacant_count);
    document.getElementById('s-land').textContent = fmtM(summary.total_land_value);
    document.getElementById('s-improvement').textContent = fmtM(summary.total_improvement_value);
    document.getElementById('s-assessed').textContent = fmtM(summary.total_assessed_value);
    document.getElementById('s-avail-gfa').textContent = fmt(summary.total_available_gfa) + ' SF';
    document.getElementById('s-median-gfa').textContent = fmt(summary.median_available_gfa) + ' SF';
    document.getElementById('s-valued').textContent = fmt(summary.parcels_with_value);
    document.getElementById('s-val-low').textContent = fmtM(summary.total_est_low);
    document.getElementById('s-val-high').textContent = fmtM(summary.total_est_high);
    document.getElementById('s-rate').textContent = summary.neighborhood_rate_median != null
        ? fmtD(summary.neighborhood_rate_median) + '/SF'
        : '$' + summary.fallback_improvement_rate + '/SF (estimated \u2014 limited local data)';
    document.getElementById('s-rate-sample').textContent = fmt(summary.neighborhood_rate_sample) + ' homes';

    const STATUS_LABELS = {
        'overdeveloped': 'Exceeds max GFA',
        'near-capacity': 'Near capacity',
        'underdeveloped': 'Underdeveloped',
        'vacant': 'High development potential',
    };
    function statusLabel(s) { return STATUS_LABELS[s] || s; }

    function fillBreakdown(id, obj) {
        const el = document.getElementById(id);
        const sorted = Object.entries(obj).sort((a, b) => b[1] - a[1]);
        el.innerHTML = sorted.map(([k, v]) =>
            '<div class="breakdown-row"><span class="bk-label">' + statusLabel(k) + '</span><span class="bk-value">' + fmt(v) + '</span></div>'
        ).join('');
    }
    fillBreakdown('zoning-breakdown', summary.zoning_counts);
    fillBreakdown('status-breakdown', summary.status_counts);
    // Map jargon labels to user-friendly text
    // --- Map ---
    const map = L.map('map', { zoomControl: true });
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
        maxZoom: 20
    }).addTo(map);

    // --- Color scale ---
    // Max available GFA for scaling (use 95th percentile to avoid outlier skew)
    const gfaValues = geojsonData.features
        .map(f => f.properties.available_gfa_sf)
        .filter(v => v != null && v > 0)
        .sort((a, b) => a - b);
    const maxGfa = gfaValues.length > 0 ? gfaValues[Math.floor(gfaValues.length * 0.95)] : 5000;

    function getColor(props) {
        const status = props.development_status;
        const avail = props.available_gfa_sf;
        const spotCheck = props.spot_check_result;

        // Grey for excluded
        if (spotCheck === 'excluded') return '#888';

        // Vacant = high potential (teal)
        if (status === 'vacant') return '#009E73';

        // Exceeds max GFA = orange-red
        if (status === 'overdeveloped') return '#D55E00';

        // Near-capacity = amber
        if (status === 'near-capacity') return '#E69F00';

        // No data
        if (avail == null) return '#888';

        // Gradient for underdeveloped (more potential = teal)
        if (avail <= 0) return '#E69F00';
        const t = Math.min(avail / maxGfa, 1);
        if (t < 0.33) return '#F0E442';
        if (t < 0.66) return '#56B4E9';
        return '#009E73';
    }

    function getWeight(props) {
        return 1;
    }

    function getBorderColor(props) {
        return '#444';
    }

    // --- Tooltip ---
    function makeTooltip(props) {
        const addr = props.street_address || 'No address';
        const pid = props.parcel_id || '';
        const zoning = props.zoning_district || '';
        const status = props.development_status || 'unknown';

        let html = '<div class="parcel-tooltip">';
        html += '<div class="tt-header">' + addr + '</div>';
        html += '<div class="tt-row"><span class="tt-label">Parcel ID</span><span class="tt-value">' + pid + '</span></div>';
        html += '<div class="tt-row"><span class="tt-label">Zoning</span><span class="tt-value">' + zoning + '</span></div>';
        html += '<div class="tt-row"><span class="tt-label">Status</span><span class="tt-value">' + statusLabel(status) + '</span></div>';

        html += '<div class="tt-section"><div class="tt-section-title">Current Building</div>';
        html += '<div class="tt-row"><span class="tt-label">Year Built</span><span class="tt-value">' + (props.year_built ? Math.round(props.year_built) : 'N/A') + '</span></div>';
        html += '<div class="tt-row"><span class="tt-label">Current GFA</span><span class="tt-value">' + (props.current_gfa_sf != null ? fmt(Math.round(props.current_gfa_sf)) + ' SF' : 'N/A') + '</span></div>';
        html += '<div class="tt-row"><span class="tt-label">Stories</span><span class="tt-value">' + (props.current_stories || 'N/A') + '</span></div>';
        html += '</div>';

        html += '<div class="tt-section"><div class="tt-section-title">Assessment</div>';
        html += '<div class="tt-row"><span class="tt-label">Land</span><span class="tt-value">' + fmtD(props.land_value) + '</span></div>';
        html += '<div class="tt-row"><span class="tt-label">Improvement</span><span class="tt-value">' + fmtD(props.improvement_value) + '</span></div>';
        html += '</div>';

        html += '<div class="tt-section"><div class="tt-section-title">Development Potential</div>';
        html += '<div class="tt-row"><span class="tt-label">Max GFA</span><span class="tt-value">' + (props.max_gfa_sf != null ? fmt(Math.round(props.max_gfa_sf)) + ' SF' : 'N/A') + '</span></div>';
        html += '<div class="tt-row"><span class="tt-label">Available GFA</span><span class="tt-value tt-highlight">' + (props.available_gfa_sf != null ? fmt(Math.round(props.available_gfa_sf)) + ' SF' : 'N/A') + '</span></div>';
        html += '<div class="tt-row"><span class="tt-label">Utilization</span><span class="tt-value">' + (props.gfa_utilization_pct != null ? props.gfa_utilization_pct.toFixed(1) + '%' : 'N/A') + '</span></div>';
        html += '</div>';

        if (props.est_value_low != null) {
            html += '<div class="tt-section"><div class="tt-section-title">Estimated Value of Unused Rights</div>';
            html += '<div class="tt-row"><span class="tt-label">Range</span><span class="tt-value tt-highlight">' + fmtD(props.est_value_low) + ' &ndash; ' + fmtD(props.est_value_high) + '</span></div>';
            html += '</div>';
        }

        if (props.spot_check_result) {
            html += '<div class="tt-section"><div class="tt-section-title">Spot Check</div>';
            html += '<div class="tt-row"><span class="tt-label">Result</span><span class="tt-value">' + props.spot_check_result + '</span></div>';
            if (props.spot_check_notes) {
                html += '<div style="font-size:11px;color:#666;margin-top:2px">' + props.spot_check_notes + '</div>';
            }
            html += '</div>';
        }

        html += '</div>';
        return html;
    }

    // --- Selected parcel panel ---
    let selectedLayer = null;
    function selectParcel(props, layer) {
        // Reset previous selection
        if (selectedLayer) geojsonLayer.resetStyle(selectedLayer);
        selectedLayer = layer;
        layer.setStyle({ weight: 3, color: '#ffd700', fillOpacity: 0.9 });
        layer.bringToFront();

        const el = document.getElementById('selected-parcel');
        const addr = props.street_address || 'No address';
        let html = '<button class="sp-dismiss" onclick="dismissSelection()">&times;</button>';
        html += '<div class="sp-header">' + addr + '</div>';
        html += '<div class="sp-row"><span class="sp-label">Parcel ID</span><span class="sp-value">' + (props.parcel_id || '') + '</span></div>';
        html += '<div class="sp-row"><span class="sp-label">Zoning</span><span class="sp-value">' + (props.zoning_district || '') + '</span></div>';
        html += '<div class="sp-row"><span class="sp-label">Status</span><span class="sp-value">' + statusLabel(props.development_status || '') + '</span></div>';
        if (props.available_gfa_sf != null) {
            html += '<div class="sp-row"><span class="sp-label">Available GFA</span><span class="sp-value sp-highlight">' + fmt(Math.round(props.available_gfa_sf)) + ' SF</span></div>';
        }
        if (props.est_value_low != null) {
            html += '<div class="sp-row"><span class="sp-label">Est. Value</span><span class="sp-value sp-highlight">' + fmtD(props.est_value_low) + ' \u2013 ' + fmtD(props.est_value_high) + '</span></div>';
        }
        el.innerHTML = html;
        el.style.display = 'block';
    }
    function dismissSelection() {
        if (selectedLayer) geojsonLayer.resetStyle(selectedLayer);
        selectedLayer = null;
        const el = document.getElementById('selected-parcel');
        el.style.display = 'none';
        el.innerHTML = '';
    }

    // --- Calibration filter ---
    const calibrationIds = new Set(summary.calibration_parcel_ids || []);
    let calibrationFilterActive = false;

    function toggleCalibrationFilter() {
        calibrationFilterActive = !calibrationFilterActive;
        const header = document.getElementById('calibration-header');
        const hint = document.getElementById('calibration-filter-hint');
        if (calibrationFilterActive) {
            header.classList.add('filter-active');
            hint.textContent = 'click to clear';
        } else {
            header.classList.remove('filter-active');
            hint.textContent = 'click to filter';
        }
        geojsonLayer.eachLayer(function(layer) {
            const pid = layer.feature && layer.feature.properties && layer.feature.properties.parcel_id;
            if (calibrationFilterActive) {
                if (calibrationIds.has(pid)) {
                    layer.setStyle({ fillColor: '#ffd700', fillOpacity: 0.9, color: '#b8860b', weight: 2.5, opacity: 1 });
                    layer.bringToFront();
                } else {
                    layer.setStyle({ fillOpacity: 0.08, opacity: 0.2 });
                }
            } else {
                geojsonLayer.resetStyle(layer);
            }
        });
        // Keep selected parcel highlighted if it's a calibration parcel
        if (selectedLayer) {
            selectedLayer.setStyle({ weight: 3, color: '#ffd700', fillOpacity: calibrationFilterActive ? 0.95 : 0.9 });
        }
    }

    // --- Add GeoJSON layer ---
    const geojsonLayer = L.geoJSON(geojsonData, {
        style: function(feature) {
            return {
                fillColor: getColor(feature.properties),
                fillOpacity: 0.65,
                color: getBorderColor(feature.properties),
                weight: getWeight(feature.properties),
                opacity: 0.8
            };
        },
        onEachFeature: function(feature, layer) {
            layer.bindTooltip(makeTooltip(feature.properties), {
                sticky: true,
                direction: 'top',
                className: ''
            });

            layer.on('mouseover', function() {
                if (this !== selectedLayer) {
                    const pid = feature.properties.parcel_id;
                    if (calibrationFilterActive && !calibrationIds.has(pid)) {
                        this.setStyle({ weight: 1.5, color: '#fff', fillOpacity: 0.25 });
                    } else {
                        this.setStyle({ weight: 3, color: '#fff', fillOpacity: 0.85 });
                    }
                }
                this.bringToFront();
            });
            layer.on('mouseout', function() {
                if (this !== selectedLayer) {
                    if (calibrationFilterActive) {
                        const pid = feature.properties.parcel_id;
                        if (calibrationIds.has(pid)) {
                            this.setStyle({ fillColor: '#ffd700', fillOpacity: 0.9, color: '#b8860b', weight: 2.5, opacity: 1 });
                        } else {
                            this.setStyle({ fillOpacity: 0.08, opacity: 0.2 });
                        }
                    } else {
                        geojsonLayer.resetStyle(this);
                    }
                }
            });
            layer.on('click', function() {
                selectParcel(feature.properties, this);
            });
        }
    }).addTo(map);

    // --- Excluded parcels layer ---
    if (excludedData && excludedData.features && excludedData.features.length > 0) {
        function makeExcludedTooltip(props) {
            const addr = props.street_address || 'No address';
            let html = '<div class="parcel-tooltip">';
            html += '<div class="tt-header">' + addr + '</div>';
            if (props.parcel_id) html += '<div class="tt-row"><span class="tt-label">Parcel ID</span><span class="tt-value">' + props.parcel_id + '</span></div>';
            if (props.zoning_district) html += '<div class="tt-row"><span class="tt-label">Zoning</span><span class="tt-value">' + props.zoning_district + '</span></div>';
            html += '<div class="tt-section"><div class="tt-section-title">Excluded</div>';
            html += '<div style="color:#e63946;font-weight:600">' + (props.exclusion_reason || 'Unknown reason') + '</div>';
            html += '</div></div>';
            return html;
        }

        const excludedLayer = L.geoJSON(excludedData, {
            style: function() {
                return { fillColor: '#888', fillOpacity: 0.35, color: '#666', weight: 0.5, opacity: 0.6 };
            },
            onEachFeature: function(feature, layer) {
                layer.bindTooltip(makeExcludedTooltip(feature.properties), {
                    sticky: true, direction: 'top', className: ''
                });
                layer.on('mouseover', function() {
                    if (this !== selectedLayer) {
                        this.setStyle({ weight: 2, color: '#fff', fillOpacity: 0.5 });
                    }
                    this.bringToFront();
                });
                layer.on('mouseout', function() {
                    if (this !== selectedLayer) {
                        excludedLayer.resetStyle(this);
                    }
                });
                layer.on('click', function() {
                    const p = feature.properties;
                    if (selectedLayer) geojsonLayer.resetStyle(selectedLayer);
                    selectedLayer = this;
                    this.setStyle({ weight: 3, color: '#ffd700', fillOpacity: 0.6 });
                    this.bringToFront();
                    const el = document.getElementById('selected-parcel');
                    let html = '<button class="sp-dismiss" onclick="dismissSelection()">&times;</button>';
                    html += '<div class="sp-header">' + (p.street_address || 'No address') + '</div>';
                    if (p.parcel_id) html += '<div class="sp-row"><span class="sp-label">Parcel ID</span><span class="sp-value">' + p.parcel_id + '</span></div>';
                    if (p.zoning_district) html += '<div class="sp-row"><span class="sp-label">Zoning</span><span class="sp-value">' + p.zoning_district + '</span></div>';
                    html += '<div class="sp-row"><span class="sp-label">Status</span><span class="sp-value" style="color:#e63946">Excluded</span></div>';
                    html += '<div class="sp-row"><span class="sp-label">Reason</span><span class="sp-value" style="color:#e63946">' + (p.exclusion_reason || 'Unknown') + '</span></div>';
                    el.innerHTML = html;
                    el.style.display = 'block';
                });
            }
        }).addTo(map);

        // Ensure analyzed parcels render on top of excluded
        geojsonLayer.bringToFront();
    }

    // Fit map to data bounds
    if (geojsonLayer.getBounds().isValid()) {
        map.fitBounds(geojsonLayer.getBounds(), { padding: [40, 40] });
    }

    // --- URL parameter: auto-select parcel ---
    (function() {
        var urlParams = new URLSearchParams(window.location.search);
        var targetParcel = urlParams.get('parcel');
        if (targetParcel) {
            geojsonLayer.eachLayer(function(layer) {
                if (layer.feature && layer.feature.properties.parcel_id === targetParcel) {
                    selectParcel(layer.feature.properties, layer);
                    map.fitBounds(layer.getBounds(), { padding: [60, 60], maxZoom: 18 });
                }
            });
        }
    })();
    </script>
    </body>
    </html>
    """)

    # Replace placeholders with actual data
    html = html.replace("NEIGHBORHOOD_NAME", summary.get("neighborhood", "Unknown"))
    html = html.replace("GEOJSON_DATA_PLACEHOLDER", geojson_str)
    html = html.replace("EXCLUDED_DATA_PLACEHOLDER", excluded_str)
    html = html.replace("SUMMARY_DATA_PLACEHOLDER", summary_str)
    html = html.replace("NAV_OPTIONS_PLACEHOLDER", nav_options)

    return html


def generate_map(
    geojson_path: Path,
    output_path: Path | None = None,
    excluded_geojson_path: Path | None = None,
) -> Path:
    """
    Generate an HTML map from a GeoJSON analysis file.

    Args:
        geojson_path: Path to the analysis GeoJSON file
        output_path: Optional output path; defaults to map.html in same directory
        excluded_geojson_path: Optional path to excluded parcels GeoJSON.
            If None, auto-detects *_excluded.geojson in the same directory.

    Returns:
        Path to the generated HTML file
    """
    logger.info(f"Loading GeoJSON from: {geojson_path}")
    with open(geojson_path, "r", encoding="utf-8") as f:
        geojson_data = json.load(f)

    n_features = len(geojson_data.get("features", []))
    logger.info(f"Loaded {n_features:,} features")

    # Auto-detect excluded parcels GeoJSON
    excluded_data = None
    if excluded_geojson_path is None:
        candidates = list(geojson_path.parent.glob("*_excluded.geojson"))
        if candidates:
            excluded_geojson_path = candidates[0]
    if excluded_geojson_path is not None and excluded_geojson_path.exists():
        with open(excluded_geojson_path, "r", encoding="utf-8") as f:
            excluded_data = json.load(f)
        n_excluded = len(excluded_data.get("features", []))
        logger.info(f"Loaded {n_excluded:,} excluded parcels from: {excluded_geojson_path}")

    # Pass results_dir and current_slug so the nav bar can list other neighborhoods
    current_slug = geojson_path.parent.name
    results_dir = geojson_path.parent.parent
    html = generate_map_html(geojson_data, excluded_data, results_dir=results_dir, current_slug=current_slug)

    if output_path is None:
        output_path = geojson_path.parent / "map.html"

    output_path.write_text(html, encoding="utf-8")
    size_kb = output_path.stat().st_size / 1024
    logger.info(f"Saved map: {output_path} ({size_kb:.0f} KB)")

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an interactive HTML map from TDR analysis results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--neighborhood", metavar="NAME",
        help='Neighborhood name (looks in data/results/{name}/)',
    )
    parser.add_argument(
        "--geojson", metavar="PATH",
        help="Path to a specific GeoJSON file",
    )
    parser.add_argument(
        "--output", metavar="PATH",
        help="Output HTML file path (default: map.html in same directory as GeoJSON)",
    )
    parser.add_argument(
        "--results-dir", metavar="PATH",
        default="data/results",
        help="Base results directory (default: data/results)",
    )

    args = parser.parse_args()

    if args.geojson:
        geojson_path = Path(args.geojson).resolve()
    elif args.neighborhood:
        safe = args.neighborhood.replace(" ", "_").lower()
        results_base = (_PROJECT_ROOT / args.results_dir).resolve()
        geojson_path = results_base / safe / f"{safe}_analysis.geojson"
    else:
        parser.error("Provide either --neighborhood or --geojson")
        return

    if not geojson_path.exists():
        logger.error(f"GeoJSON not found: {geojson_path}")
        sys.exit(1)

    output_path = Path(args.output).resolve() if args.output else None
    result = generate_map(geojson_path, output_path)
    print(f"\nMap generated: {result}")
    print("Open in a web browser to view.")


if __name__ == "__main__":
    main()
