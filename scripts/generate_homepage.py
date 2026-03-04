"""
Homepage Generator for TDR Analysis
=====================================

Generates data/results/index.html — an Arlington-wide overview map that links
to all analyzed neighborhood maps.

Usage
-----
    python scripts/generate_homepage.py
    python scripts/generate_homepage.py --output data/results/index.html
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
sys.path.insert(0, str(_SCRIPT_DIR))

from generate_map import _compute_summary  # noqa: E402

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("generate_homepage")


def _feature_centroid(feature: dict) -> tuple[float, float] | None:
    """Compute (lat, lng) centroid from a GeoJSON feature's bounds midpoint."""
    geom = feature.get("geometry", {})
    if not geom:
        return None
    coords_flat: list[list[float]] = []
    geom_type = geom.get("type")
    coords = geom.get("coordinates", [])
    if geom_type == "Polygon":
        for ring in coords:
            coords_flat.extend(ring)
    elif geom_type == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                coords_flat.extend(ring)
    if not coords_flat:
        return None
    lngs = [c[0] for c in coords_flat]
    lats = [c[1] for c in coords_flat]
    return ((min(lats) + max(lats)) / 2, (min(lngs) + max(lngs)) / 2)


def _geojson_bounds(geojson_data: dict) -> list[float] | None:
    """Return [min_lng, min_lat, max_lng, max_lat] across all features."""
    coords_flat: list[list[float]] = []
    for f in geojson_data.get("features", []):
        geom = f.get("geometry", {})
        geom_type = geom.get("type")
        coords = geom.get("coordinates", [])
        if geom_type == "Polygon":
            for ring in coords:
                coords_flat.extend(ring)
        elif geom_type == "MultiPolygon":
            for poly in coords:
                for ring in poly:
                    coords_flat.extend(ring)
    if not coords_flat:
        return None
    lngs = [c[0] for c in coords_flat]
    lats = [c[1] for c in coords_flat]
    return [min(lngs), min(lats), max(lngs), max(lats)]


def load_neighborhood_data(results_dir: Path) -> dict[str, dict]:
    """Load summary data for all analyzed neighborhoods found in results_dir."""
    neighborhoods: dict[str, dict] = {}
    if not results_dir.exists():
        return neighborhoods

    for subdir in sorted(results_dir.iterdir()):
        if not subdir.is_dir():
            continue
        geojson_files = list(subdir.glob("*_analysis.geojson"))
        if not geojson_files:
            continue
        geojson_path = geojson_files[0]
        excluded_path = next(iter(subdir.glob("*_excluded.geojson")), None)

        try:
            with open(geojson_path, "r", encoding="utf-8") as fh:
                geojson_data = json.load(fh)
            excluded_data = None
            if excluded_path and excluded_path.exists():
                with open(excluded_path, "r", encoding="utf-8") as fh:
                    excluded_data = json.load(fh)

            summary = _compute_summary(geojson_data, excluded_data)
            bounds = _geojson_bounds(geojson_data)
            name = summary.get("neighborhood") or subdir.name.replace("_", " ").title()
            slug = subdir.name

            # Build per-parcel address lookup entries
            addr_entries: dict[str, dict] = {}
            for feat in geojson_data.get("features", []):
                props = feat.get("properties", {})
                addr = props.get("street_address", "")
                parcel_id = props.get("parcel_id", "")
                if not addr or not parcel_id:
                    continue
                centroid = _feature_centroid(feat)
                if centroid is None:
                    continue
                lat, lng = centroid
                addr_entries[addr.lower().strip()] = {
                    "display": addr,
                    "slug": slug,
                    "parcel_id": parcel_id,
                    "lat": round(lat, 6),
                    "lng": round(lng, 6),
                }

            neighborhoods[slug] = {
                "name": name,
                "slug": slug,
                "summary": summary,
                "bounds": bounds,
                "addr_entries": addr_entries,
            }
            logger.info(
                f"Loaded {name}: {summary['total_parcels']} parcels, "
                f"{len(addr_entries)} addresses"
            )
        except Exception as e:
            logger.warning(f"Failed to load {subdir.name}: {e}")

    return neighborhoods


def generate_homepage_html(
    civic_assoc_data: dict,
    neighborhoods: dict[str, dict],
) -> str:
    """Generate self-contained homepage HTML with embedded data."""
    # Merge address lookups across all neighborhoods
    address_lookup: dict[str, dict] = {}
    for data in neighborhoods.values():
        address_lookup.update(data.get("addr_entries", {}))

    # Build lightweight JS-side neighborhood summary (no full parcel GeoJSON)
    js_nb_data: dict[str, dict] = {}
    for slug, data in neighborhoods.items():
        s = data["summary"]
        js_nb_data[slug] = {
            "name": data["name"],
            "slug": slug,
            "bounds": data["bounds"],
            "total_parcels": s["total_parcels"],
            "total_available_gfa": s["total_available_gfa"],
            "total_est_low": s["total_est_low"],
            "total_est_high": s["total_est_high"],
            "parcels_with_capacity": s["parcels_with_capacity"],
            "neighborhood_rate_median": s["neighborhood_rate_median"],
            "vacant_count": s["vacant_count"],
            "underdeveloped_count": s["underdeveloped_count"],
            "near_capacity_count": s["near_capacity_count"],
            "overdeveloped_count": s["overdeveloped_count"],
        }

    # Compute quintile thresholds on total_available_gfa across all analyzed neighborhoods
    gfa_sorted = sorted(d["summary"]["total_available_gfa"] for d in neighborhoods.values())
    n = len(gfa_sorted)
    if n >= 5:
        thresholds = [gfa_sorted[int(n * p)] for p in (0.20, 0.40, 0.60, 0.80)]
    else:
        thresholds = [0, 0, 0, 0]

    civic_str = json.dumps(civic_assoc_data)
    nb_data_str = json.dumps(js_nb_data)
    addr_str = json.dumps(address_lookup)
    analyzed_slugs_str = json.dumps(sorted(neighborhoods.keys()))
    thresholds_str = json.dumps(thresholds)

    html = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arlington TDR Analysis</title>
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

    .legend { margin-top: 4px; margin-bottom: 4px; }
    .legend-item { display: flex; align-items: center; gap: 8px; margin: 4px 0; font-size: 12px; }
    .legend-swatch { width: 20px; height: 14px; border-radius: 2px; border: 1px solid #555; flex-shrink: 0; }

    .nb-row {
        display: flex; align-items: center; justify-content: space-between;
        padding: 8px 10px; margin: 2px 0; background: #16213e; border-radius: 4px;
        cursor: pointer; border: 1px solid transparent; transition: border-color 0.1s, background 0.1s;
    }
    .nb-row:hover, .nb-row.active { border-color: #8ecae6; background: #1e2d4a; }
    .nb-name { font-size: 13px; color: #e0e0e0; }
    .nb-link { font-size: 11px; color: #8ecae6; text-decoration: none; white-space: nowrap; }
    .nb-link:hover { color: #ffd700; }

    #hover-panel {
        background: #16213e; border: 1px solid #8ecae6; border-radius: 6px;
        padding: 12px; margin-bottom: 12px; display: none;
    }
    #hover-panel h3 { font-size: 15px; color: #fff; margin-bottom: 8px; }
    .hp-row { display: flex; justify-content: space-between; gap: 8px; padding: 2px 0; }
    .hp-label { color: #999; font-size: 12px; }
    .hp-value { color: #fff; font-weight: 600; font-size: 12px; }
    .hp-link { display: block; margin-top: 8px; color: #8ecae6; font-size: 12px; text-decoration: none; }
    .hp-link:hover { color: #ffd700; }

    #address-search { position: relative; margin-bottom: 4px; }
    #address-input {
        width: 100%; background: #16213e; color: #e0e0e0; border: 1px solid #444;
        border-radius: 4px; padding: 8px 10px; font-size: 13px; outline: none;
    }
    #address-input:focus { border-color: #8ecae6; }
    #address-input::placeholder { color: #666; }
    #address-dropdown {
        position: absolute; top: 100%; left: 0; right: 0; z-index: 9999;
        background: #16213e; border: 1px solid #444; border-top: none;
        border-radius: 0 0 4px 4px; display: none; max-height: 200px; overflow-y: auto;
    }
    .addr-option {
        padding: 7px 10px; cursor: pointer; font-size: 12px; color: #e0e0e0;
        border-bottom: 1px solid #222;
    }
    .addr-option:last-child { border-bottom: none; }
    .addr-option:hover { background: #1e2d4a; color: #fff; }

    .disclaimer { margin-top: 16px; padding: 10px; background: #2a1a1a; border-left: 3px solid #e63946; border-radius: 4px; font-size: 11px; color: #ccc; }

    #map { flex: 1; }
    </style>
    </head>
    <body>
    <div id="sidebar">
        <h1>Arlington TDR Analysis</h1>
        <div class="subtitle">Transfer of Development Rights Potential</div>

        <div id="hover-panel"></div>

        <div id="agg-stats">
            <h2>County-Wide Summary</h2>
            <div class="stat-grid" id="agg-grid"></div>
        </div>

        <h2>Map Legend</h2>
        <div class="legend">
            <div class="legend-item"><div class="legend-swatch" style="background:#009E73;border-color:#009E73"></div> Top quintile available GFA</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#56B4E9;border-color:#56B4E9"></div> Upper-middle quintile</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#F0E442;border-color:#888"></div> Middle quintile</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#E69F00;border-color:#E69F00"></div> Lower-middle quintile</div>
            <div class="legend-item"><div class="legend-swatch" style="background:#D55E00;border-color:#D55E00"></div> Bottom quintile available GFA</div>
            <div class="legend-item"><div class="legend-swatch" style="background:transparent;border-color:#555"></div> Not yet analyzed</div>
        </div>

        <h2>Address Search</h2>
        <div id="address-search">
            <input type="text" id="address-input" placeholder="Search by address\u2026" autocomplete="off">
            <div id="address-dropdown"></div>
        </div>

        <h2>Analyzed Neighborhoods</h2>
        <div id="nb-list"></div>

        <div class="disclaimer">
            <strong>Disclaimer:</strong> Analysis covers selected Arlington residential neighborhoods.
            TDR potential estimates are for policy analysis only, not property appraisals.
            All values should be independently verified before use in policy decisions.
        </div>
        <div style="margin-top:16px;padding-top:12px;border-top:1px solid #333;font-size:11px;color:#666;line-height:1.5;">
            <a href="https://github.com/joburke1/tdranalysis" style="color:#8ecae6;">Arlington Transfer of Development Rights Analysis</a>
            by <a href="https://www.linkedin.com/in/john-burke-arlingtonva/" style="color:#8ecae6;">John Burke</a>
            is marked <a href="https://creativecommons.org/publicdomain/zero/1.0/" style="color:#8ecae6;">CC0 1.0</a><img src="https://mirrors.creativecommons.org/presskit/icons/cc.svg" alt="" style="max-width:1em;max-height:1em;margin-left:.2em;vertical-align:middle;"><img src="https://mirrors.creativecommons.org/presskit/icons/zero.svg" alt="" style="max-width:1em;max-height:1em;margin-left:.2em;vertical-align:middle;">
        </div>
    </div>

    <div id="map"></div>

    <script>
    // --- Embedded data ---
    const civicData = CIVIC_DATA_PLACEHOLDER;
    const neighborhoodData = NB_DATA_PLACEHOLDER;
    const addressLookup = ADDR_LOOKUP_PLACEHOLDER;
    const analyzedSlugs = new Set(ANALYZED_SLUGS_PLACEHOLDER);
    const gfaThresholds = THRESHOLDS_PLACEHOLDER;  // [q20, q40, q60, q80]

    // --- Helpers ---
    function fmt(n) { return n == null ? 'N/A' : n.toLocaleString('en-US', {maximumFractionDigits: 0}); }
    function fmtM(n) {
        if (n == null) return 'N/A';
        if (Math.abs(n) >= 1e9) return '$' + (n/1e9).toFixed(1) + 'B';
        if (Math.abs(n) >= 1e6) return '$' + (n/1e6).toFixed(1) + 'M';
        if (Math.abs(n) >= 1e3) return '$' + (n/1e3).toFixed(0) + 'K';
        return '$' + n.toFixed(0);
    }
    function fmtD(n) { return n == null ? 'N/A' : '$' + n.toLocaleString('en-US', {maximumFractionDigits: 0}); }
    function fmtGfa(n) {
        if (n == null) return 'N/A';
        if (n >= 1e6) return (n/1e6).toFixed(1) + 'M SF';
        if (n >= 1e3) return Math.round(n/1000) + 'K SF';
        return fmt(n) + ' SF';
    }

    // --- Aggregate stats ---
    var nbs = Object.values(neighborhoodData);
    var nAnalyzed = nbs.length;
    var totalParcels = nbs.reduce(function(s, n) { return s + n.total_parcels; }, 0);
    var totalGfa = nbs.reduce(function(s, n) { return s + n.total_available_gfa; }, 0);
    var totalLow = nbs.reduce(function(s, n) { return s + n.total_est_low; }, 0);
    var totalHigh = nbs.reduce(function(s, n) { return s + n.total_est_high; }, 0);
    document.getElementById('agg-grid').innerHTML =
        '<div class="stat-box"><div class="label">Neighborhoods Analyzed</div><div class="value">' + nAnalyzed + '</div></div>' +
        '<div class="stat-box"><div class="label">Parcels Analyzed</div><div class="value">' + fmt(totalParcels) + '</div></div>' +
        '<div class="stat-box wide"><div class="label">Total Available GFA</div><div class="value">' + fmtGfa(totalGfa) + '</div></div>' +
        '<div class="stat-box wide"><div class="label">Aggregate Value Range</div><div class="value small">' + fmtM(totalLow) + ' \u2013 ' + fmtM(totalHigh) + '</div></div>';

    // --- Neighborhood list ---
    var nbList = document.getElementById('nb-list');
    var sortedSlugs = Object.keys(neighborhoodData).sort(function(a, b) {
        return neighborhoodData[a].name.localeCompare(neighborhoodData[b].name);
    });
    sortedSlugs.forEach(function(slug) {
        var nb = neighborhoodData[slug];
        var row = document.createElement('div');
        row.className = 'nb-row';
        row.dataset.slug = slug;
        row.innerHTML = '<span class="nb-name">' + nb.name + '</span>' +
            '<a href="' + slug + '/map.html" class="nb-link" onclick="event.stopPropagation()">View map \u2192</a>';
        row.addEventListener('click', function() { window.location.href = slug + '/map.html'; });
        nbList.appendChild(row);
    });

    // --- Map ---
    var map = L.map('map', {zoomControl: true});
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
        maxZoom: 20
    }).addTo(map);

    function getSlug(name) { return name.toLowerCase().replace(/ /g, '_'); }

    function getGfaColor(slug) {
        var nb = neighborhoodData[slug];
        if (!nb) return '#888';
        var gfa = nb.total_available_gfa;
        if (gfa > gfaThresholds[3]) return '#009E73';
        if (gfa > gfaThresholds[2]) return '#56B4E9';
        if (gfa > gfaThresholds[1]) return '#F0E442';
        if (gfa > gfaThresholds[0]) return '#E69F00';
        return '#D55E00';
    }

    function featureStyle(feature, isHover) {
        var slug = getSlug(feature.properties.CIVIC || '');
        var isAnalyzed = analyzedSlugs.has(slug);
        if (isAnalyzed) {
            var color = getGfaColor(slug);
            return {
                fillColor: color, fillOpacity: isHover ? 0.6 : 0.45,
                color: color, weight: isHover ? 2.5 : 1.5, opacity: 0.8
            };
        }
        return {
            fillColor: 'transparent', fillOpacity: 0,
            color: '#555', weight: 0.8, opacity: isHover ? 0.9 : 0.5
        };
    }

    function makeTooltip(slug, name, isAnalyzed) {
        var nb = neighborhoodData[slug];
        var html = '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;font-size:12px;line-height:1.5;min-width:180px">';
        html += '<div style="font-weight:700;font-size:13px;border-bottom:1px solid #ddd;padding-bottom:4px;margin-bottom:6px">' + name + '</div>';
        if (!isAnalyzed || !nb) {
            html += '<div style="color:#888">Not yet analyzed</div>';
        } else {
            var gfa = nb.total_available_gfa;
            var quintile = gfa > gfaThresholds[3] ? 'Top' : gfa > gfaThresholds[2] ? 'Upper-middle' : gfa > gfaThresholds[1] ? 'Middle' : gfa > gfaThresholds[0] ? 'Lower-middle' : 'Bottom';
            function row(label, value) { return '<div style="display:flex;justify-content:space-between;gap:12px;padding:1px 0"><span style="color:#666">' + label + '</span><span style="font-weight:600">' + value + '</span></div>'; }
            html += row('Parcels analyzed', fmt(nb.total_parcels));
            html += row('Available GFA', fmtGfa(nb.total_available_gfa));
            html += row('Value range', fmtM(nb.total_est_low) + ' \u2013 ' + fmtM(nb.total_est_high));
            if (nb.neighborhood_rate_median) html += row('Improvement $/SF', fmtD(nb.neighborhood_rate_median) + '/SF');
            html += row('Vacant buildable', fmt(nb.vacant_count));
            html += row('Underdeveloped', fmt(nb.underdeveloped_count));
            html += row('GFA quintile', quintile);
        }
        html += '</div>';
        return html;
    }

    var civicLayer = L.geoJSON(civicData, {
        style: function(feature) { return featureStyle(feature, false); },
        onEachFeature: function(feature, layer) {
            var name = feature.properties.CIVIC || 'Unknown';
            var slug = getSlug(name);
            var isAnalyzed = analyzedSlugs.has(slug);
            layer.bindTooltip(makeTooltip(slug, name, isAnalyzed), {sticky: true, direction: 'top', opacity: 0.97});
            layer.on('mouseover', function() {
                layer.setStyle(featureStyle(feature, true));
                layer.bringToFront();
                showHoverPanel(slug, name, isAnalyzed);
                document.querySelectorAll('.nb-row').forEach(function(r) { r.classList.remove('active'); });
                var row = document.querySelector('.nb-row[data-slug="' + slug + '"]');
                if (row) { row.classList.add('active'); row.scrollIntoView({block: 'nearest'}); }
            });
            layer.on('mouseout', function() {
                layer.setStyle(featureStyle(feature, false));
            });
            layer.on('click', function() {
                if (isAnalyzed) window.location.href = slug + '/map.html';
            });
        }
    }).addTo(map);

    document.getElementById('map').addEventListener('mouseleave', function() {
        document.getElementById('hover-panel').style.display = 'none';
        document.getElementById('agg-stats').style.display = 'block';
        document.querySelectorAll('.nb-row').forEach(function(r) { r.classList.remove('active'); });
    });

    // --- Hover panel ---
    function showHoverPanel(slug, name, isAnalyzed) {
        var panel = document.getElementById('hover-panel');
        var aggStats = document.getElementById('agg-stats');
        if (!isAnalyzed) {
            panel.innerHTML = '<h3>' + name + '</h3><div style="color:#999;font-size:12px;margin-top:4px;">Not yet analyzed</div>';
            panel.style.display = 'block';
            aggStats.style.display = 'none';
            return;
        }
        var nb = neighborhoodData[slug];
        if (!nb) { panel.style.display = 'none'; aggStats.style.display = 'block'; return; }
        var html = '<h3>' + name + '</h3>';
        html += '<div class="hp-row"><span class="hp-label">Parcels analyzed</span><span class="hp-value">' + fmt(nb.total_parcels) + '</span></div>';
        html += '<div class="hp-row"><span class="hp-label">Available GFA</span><span class="hp-value">' + fmtGfa(nb.total_available_gfa) + '</span></div>';
        html += '<div class="hp-row"><span class="hp-label">Value range</span><span class="hp-value">' + fmtM(nb.total_est_low) + ' \u2013 ' + fmtM(nb.total_est_high) + '</span></div>';
        if (nb.neighborhood_rate_median) {
            html += '<div class="hp-row"><span class="hp-label">Improvement $/SF</span><span class="hp-value">' + fmtD(nb.neighborhood_rate_median) + '/SF</span></div>';
        }
        html += '<div class="hp-row" style="margin-top:4px"><span class="hp-label">Vacant buildable</span><span class="hp-value">' + fmt(nb.vacant_count) + '</span></div>';
        html += '<div class="hp-row"><span class="hp-label">Underdeveloped</span><span class="hp-value">' + fmt(nb.underdeveloped_count) + '</span></div>';
        html += '<div class="hp-row"><span class="hp-label">Near capacity</span><span class="hp-value">' + fmt(nb.near_capacity_count) + '</span></div>';
        html += '<a href="' + slug + '/map.html" class="hp-link">View detailed map \u2192</a>';
        panel.innerHTML = html;
        panel.style.display = 'block';
        aggStats.style.display = 'none';
    }

    // --- Address search ---
    var addressInput = document.getElementById('address-input');
    var dropdown = document.getElementById('address-dropdown');
    var allAddressKeys = Object.keys(addressLookup);
    addressInput.addEventListener('input', function() {
        var q = this.value.toLowerCase().trim();
        dropdown.innerHTML = '';
        if (q.length < 3) { dropdown.style.display = 'none'; return; }
        var matches = allAddressKeys.filter(function(a) { return a.includes(q); }).slice(0, 10);
        if (matches.length === 0) { dropdown.style.display = 'none'; return; }
        matches.forEach(function(key) {
            var item = addressLookup[key];
            var div = document.createElement('div');
            div.className = 'addr-option';
            div.textContent = item.display;
            div.addEventListener('click', function() {
                addressInput.value = item.display;
                dropdown.style.display = 'none';
                window.location.href = item.slug + '/map.html?parcel=' + item.parcel_id;
            });
            dropdown.appendChild(div);
        });
        dropdown.style.display = 'block';
    });
    document.addEventListener('click', function(e) {
        if (!document.getElementById('address-search').contains(e.target)) {
            dropdown.style.display = 'none';
        }
    });

    // --- Fit map to analyzed neighborhoods ---
    var analyzedBoundsArr = [];
    Object.values(neighborhoodData).forEach(function(nb) {
        if (nb.bounds) {
            // bounds: [min_lng, min_lat, max_lng, max_lat]
            analyzedBoundsArr.push([nb.bounds[1], nb.bounds[0]]);
            analyzedBoundsArr.push([nb.bounds[3], nb.bounds[2]]);
        }
    });
    if (analyzedBoundsArr.length > 0) {
        map.fitBounds(L.latLngBounds(analyzedBoundsArr), {padding: [40, 40]});
    } else if (civicLayer.getBounds().isValid()) {
        map.fitBounds(civicLayer.getBounds(), {padding: [20, 20]});
    }
    </script>
    </body>
    </html>
    """)

    html = html.replace("CIVIC_DATA_PLACEHOLDER", civic_str)
    html = html.replace("NB_DATA_PLACEHOLDER", nb_data_str)
    html = html.replace("ADDR_LOOKUP_PLACEHOLDER", addr_str)
    html = html.replace("ANALYZED_SLUGS_PLACEHOLDER", analyzed_slugs_str)
    html = html.replace("THRESHOLDS_PLACEHOLDER", thresholds_str)

    return html


def generate_homepage(
    output_path: Path | None = None,
    civic_assoc_path: Path | None = None,
    results_dir: Path | None = None,
) -> Path:
    """Generate the Arlington-wide TDR homepage."""
    if civic_assoc_path is None:
        civic_assoc_path = _PROJECT_ROOT / "data" / "raw" / "civic_associations.geojson"
    if results_dir is None:
        results_dir = _PROJECT_ROOT / "data" / "results"
    if output_path is None:
        output_path = results_dir / "index.html"

    logger.info(f"Loading civic associations from: {civic_assoc_path}")
    with open(civic_assoc_path, "r", encoding="utf-8") as fh:
        civic_assoc_data = json.load(fh)
    logger.info(f"Loaded {len(civic_assoc_data.get('features', []))} civic associations")

    neighborhoods = load_neighborhood_data(results_dir)
    logger.info(f"Found {len(neighborhoods)} analyzed neighborhoods")

    html = generate_homepage_html(civic_assoc_data, neighborhoods)
    output_path.write_text(html, encoding="utf-8")
    size_kb = output_path.stat().st_size / 1024
    logger.info(f"Saved homepage: {output_path} ({size_kb:.0f} KB)")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Arlington-wide TDR homepage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output", metavar="PATH",
        help="Output HTML path (default: data/results/index.html)",
    )
    parser.add_argument(
        "--results-dir", metavar="PATH",
        default="data/results",
        help="Base results directory (default: data/results)",
    )
    args = parser.parse_args()

    output_path = Path(args.output).resolve() if args.output else None
    results_dir = (_PROJECT_ROOT / args.results_dir).resolve()
    result = generate_homepage(output_path=output_path, results_dir=results_dir)
    print(f"\nHomepage generated: {result}")
    print("Open in a web browser to view.")


if __name__ == "__main__":
    main()
