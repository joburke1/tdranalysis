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


def _compute_summary(geojson_data: dict) -> dict:
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
    confidence_counts: dict[str, int] = {}
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

        # Confidence
        conf = p.get("valuation_confidence", "not_applicable")
        confidence_counts[conf] = confidence_counts.get(conf, 0) + 1

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

    return {
        "neighborhood": neighborhood_name,
        "total_parcels": total,
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
        "confidence_counts": confidence_counts,
        "neighborhood_rate_median": neighborhood_rate_median,
        "neighborhood_rate_low": neighborhood_rate_low,
        "neighborhood_rate_high": neighborhood_rate_high,
        "neighborhood_rate_sample": neighborhood_rate_sample,
        "pct_underdeveloped": round(
            (underdeveloped_count + vacant_count) / total * 100, 1
        ) if total > 0 else 0,
    }


def generate_map_html(geojson_data: dict) -> str:
    """Generate a self-contained HTML string with embedded map."""
    summary = _compute_summary(geojson_data)
    geojson_str = json.dumps(geojson_data)
    summary_str = json.dumps(summary)

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
                <div class="label">Underdeveloped + Vacant</div>
                <div class="value" id="s-pct-underdev"></div>
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

        <h2>Neighborhood Calibration</h2>
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

        <h2>Valuation Confidence</h2>
        <div class="breakdown" id="confidence-breakdown"></div>

        <h2>Legend</h2>
        <div class="legend">
            <div class="legend-item"><div class="legend-swatch" style="background:#084594"></div> High development potential</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#4292c6"></div> Moderate potential</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#c6dbef"></div> Low potential</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#4292c6"></div> Near capacity</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#d94801"></div> Overdeveloped</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#2d6a4f; border: 2px solid #40916c"></div> Vacant buildable</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#888"></div> Excluded / no data</div>
        </div>

        <div class="disclaimer">
            <strong>Disclaimer:</strong> Valuation estimates are for TDR policy analysis only,
            not property appraisals. Improvement $/SF derived from recent construction in this
            neighborhood. All values should be independently verified before use in policy decisions.
        </div>
    </div>

    <div id="map"></div>

    <script>
    // --- Embedded data ---
    const geojsonData = GEOJSON_DATA_PLACEHOLDER;
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
    document.getElementById('s-pct-underdev').textContent = fmtPct(summary.pct_underdeveloped);
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
        : '$185/SF (estimated \u2014 limited local data)';
    document.getElementById('s-rate-sample').textContent = fmt(summary.neighborhood_rate_sample) + ' homes';

    function fillBreakdown(id, obj) {
        const el = document.getElementById(id);
        const sorted = Object.entries(obj).sort((a, b) => b[1] - a[1]);
        el.innerHTML = sorted.map(([k, v]) =>
            '<div class="breakdown-row"><span class="bk-label">' + k + '</span><span class="bk-value">' + fmt(v) + '</span></div>'
        ).join('');
    }
    fillBreakdown('zoning-breakdown', summary.zoning_counts);
    fillBreakdown('status-breakdown', summary.status_counts);
    // Map jargon labels to user-friendly text
    const friendlyConfidence = {};
    const confLabels = {'not_applicable': 'No unused capacity', 'low': 'Low', 'medium': 'Medium', 'high': 'High'};
    for (const [k, v] of Object.entries(summary.confidence_counts)) {
        friendlyConfidence[confLabels[k] || k] = v;
    }
    fillBreakdown('confidence-breakdown', friendlyConfidence);

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

        // Vacant = green
        if (status === 'vacant') return '#2d6a4f';

        // Overdeveloped = amber/orange (warning)
        if (status === 'overdeveloped') return '#d94801';

        // Near-capacity = medium blue
        if (status === 'near-capacity') return '#4292c6';

        // No data
        if (avail == null) return '#888';

        // Blue gradient for underdeveloped (more potential = darker blue)
        if (avail <= 0) return '#4292c6';
        const t = Math.min(avail / maxGfa, 1);
        if (t < 0.33) return '#c6dbef';
        if (t < 0.66) return '#4292c6';
        return '#084594';
    }

    function getWeight(props) {
        if (props.development_status === 'vacant') return 2.5;
        return 1;
    }

    function getBorderColor(props) {
        if (props.development_status === 'vacant') return '#40916c';
        return '#444';
    }

    // --- Tooltip ---
    function makeTooltip(props) {
        const addr = props.street_address || 'No address';
        const pid = props.parcel_id || '';
        const zoning = props.zoning_district || '';
        const status = props.development_status || 'unknown';
        const conf = props.valuation_confidence || '';

        let html = '<div class="parcel-tooltip">';
        html += '<div class="tt-header">' + addr + '</div>';
        html += '<div class="tt-row"><span class="tt-label">Parcel ID</span><span class="tt-value">' + pid + '</span></div>';
        html += '<div class="tt-row"><span class="tt-label">Zoning</span><span class="tt-value">' + zoning + '</span></div>';
        html += '<div class="tt-row"><span class="tt-label">Status</span><span class="tt-value">' + status + '</span></div>';

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
            html += '<div class="tt-row"><span class="tt-label">Confidence</span><span class="tt-value">' + conf + '</span></div>';
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
        html += '<div class="sp-row"><span class="sp-label">Status</span><span class="sp-value">' + (props.development_status || '') + '</span></div>';
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
                    this.setStyle({ weight: 3, color: '#fff', fillOpacity: 0.85 });
                }
                this.bringToFront();
            });
            layer.on('mouseout', function() {
                if (this !== selectedLayer) {
                    geojsonLayer.resetStyle(this);
                }
            });
            layer.on('click', function() {
                selectParcel(feature.properties, this);
            });
        }
    }).addTo(map);

    // Fit map to data bounds
    if (geojsonLayer.getBounds().isValid()) {
        map.fitBounds(geojsonLayer.getBounds(), { padding: [40, 40] });
    }
    </script>
    </body>
    </html>
    """)

    # Replace placeholders with actual data
    html = html.replace("NEIGHBORHOOD_NAME", summary.get("neighborhood", "Unknown"))
    html = html.replace("GEOJSON_DATA_PLACEHOLDER", geojson_str)
    html = html.replace("SUMMARY_DATA_PLACEHOLDER", summary_str)

    return html


def generate_map(geojson_path: Path, output_path: Path | None = None) -> Path:
    """
    Generate an HTML map from a GeoJSON analysis file.

    Args:
        geojson_path: Path to the analysis GeoJSON file
        output_path: Optional output path; defaults to map.html in same directory

    Returns:
        Path to the generated HTML file
    """
    logger.info(f"Loading GeoJSON from: {geojson_path}")
    with open(geojson_path, "r", encoding="utf-8") as f:
        geojson_data = json.load(f)

    n_features = len(geojson_data.get("features", []))
    logger.info(f"Loaded {n_features:,} features")

    html = generate_map_html(geojson_data)

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
