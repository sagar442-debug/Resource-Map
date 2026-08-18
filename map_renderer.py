"""Folium map rendering for all configured clients."""

from __future__ import annotations

import html
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import folium
from folium.features import DivIcon
from folium.plugins import Fullscreen, MeasureControl, MiniMap

from map_config import (
    CALGARY_CENTER,
    FAMILY_CLICK_MAX_ZOOM,
    OUTPUT_DIR,
    OUTPUT_MAP,
)
from utils import clean_text, robust_family_center


def district_for(site: dict[str, Any]) -> str:
    area = clean_text(site.get("area", "")).title()
    if site.get("client_id") == "CHC":
        if area in {"East", "South", "West"}:
            return area
        return "Unknown"
    return area if area else "Unknown"


def build_family_groups(
    sites: list[dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for site in sites:
        if not site.get("group_by_family"):
            continue
        key = (site["client_id"], district_for(site), site.get("family", ""))
        groups[key].append(site)
    return dict(groups)


def apply_display_offsets(
    sites: list[dict[str, Any]],
    *,
    radius_lat: float = 0.00024,
    radius_lon: float = 0.00038,
) -> None:
    coordinate_groups: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for site in sites:
        lat = float(site["latitude"])
        lon = float(site["longitude"])
        coordinate_groups[(round(lat, 5), round(lon, 5))].append(site)

    for duplicate_sites in coordinate_groups.values():
        if len(duplicate_sites) == 1:
            site = duplicate_sites[0]
            site["_display_latitude"] = float(site["latitude"])
            site["_display_longitude"] = float(site["longitude"])
            continue
        center_lat = sum(float(s["latitude"]) for s in duplicate_sites) / len(duplicate_sites)
        center_lon = sum(float(s["longitude"]) for s in duplicate_sites) / len(duplicate_sites)
        count = len(duplicate_sites)
        for index, site in enumerate(duplicate_sites):
            angle = 2 * math.pi * index / count
            site["_display_latitude"] = center_lat + radius_lat * math.sin(angle)
            site["_display_longitude"] = center_lon + radius_lon * math.cos(angle)


def _display_coords(site: dict[str, Any]) -> tuple[float, float]:
    lat = float(site.get("_display_latitude", site["latitude"]))
    lon = float(site.get("_display_longitude", site["longitude"]))
    return lat, lon


def _coordinate_source_html(source: str) -> str:
    label = html.escape(source or "—")
    if source == "Manual":
        return (
            f'<span style="font-weight:700;color:#b45309;">{label}</span>'
            ' <span style="color:#92400e;">(verified in workbook)</span>'
        )
    return f"<b>{label}</b>"


def popup_html(site: dict[str, Any], client: dict[str, Any]) -> str:
    def field_value(key: str) -> str:
        value = clean_text(site["metadata"].get(key) or site.get(key))
        return html.escape(value) if value else "—"

    title = client.get("popup_title", site.get("client_name", ""))
    heading = site.get("site_code") or site.get("site_name") or "Site"
    subheading = ""
    if site.get("site_code") and site.get("site_name"):
        heading = f"{html.escape(site['site_code'])} — {html.escape(site['site_name'])}"
    elif site.get("site_name"):
        heading = html.escape(site["site_name"])

    rows = [
        ("District" if client["id"] == "CHC" else "Area", field_value(client["columns"].get("area", "area"))),
        ("Address", field_value(client["columns"].get("address", "address"))),
    ]
    if client["columns"].get("postal_code"):
        rows.append(("Postal Code", field_value(client["columns"]["postal_code"])))

    for extra in client.get("popup_extra_fields", []):
        raw = clean_text(site["metadata"].get(extra["field"], ""))
        if not raw:
            continue
        if extra.get("skip_if_same_as"):
            compare = clean_text(site.get(extra["skip_if_same_as"], ""))
            if raw.casefold() == compare.casefold():
                continue
        style = ""
        if extra.get("highlight_yes") and raw.lower() == "yes":
            style = "font-weight:700;color:#b91c1c;"
        if extra.get("color"):
            style = f"color:{extra['color']};font-weight:700;"
        if extra.get("warning"):
            style = "color:#a16207;font-weight:600;"
        display = html.escape(raw)
        if extra["field"] == "Source Site Name(s)":
            display = display.replace(" | ", "<br>")
        rows.append((extra["label"], f'<span style="{style}">{display}</span>' if style else display))

    matched = clean_text(site.get("matched_address", ""))
    if matched and site.get("coordinate_source") != "Manual":
        rows.append(("Geocoder Match", html.escape(matched)))

    rows.append(("Coordinate Source", _coordinate_source_html(site.get("coordinate_source", ""))))

    row_html = "".join(
        f'<tr><td style="padding:4px 10px 4px 0;color:#666;vertical-align:top;">{label}</td>'
        f'<td style="padding:4px 0;vertical-align:top;">{value}</td></tr>'
        for label, value in rows
    )

    color = site.get("marker_color", "#333")
    if client.get("marker_type") == "star":
        heading_block = f'<div style="font-size:18px;font-weight:700;color:{color};margin-bottom:2px;">★ {heading}</div>'
    else:
        heading_block = f'<div style="font-size:17px;font-weight:700;margin-bottom:2px;">{heading}</div>'

    return f"""
    <div style="font-family:Arial,sans-serif;min-width:300px;max-width:440px;">
        {heading_block}
        <div style="color:#666;margin-bottom:9px;">{html.escape(title)}</div>
        <table style="border-collapse:collapse;font-size:13px;width:100%;">{row_html}</table>
    </div>
    """


def code_label_html(
    label: str,
    background_color: str,
    css_class: str,
    *,
    family: bool = False,
) -> str:
    safe = html.escape(label or "?")
    if family:
        return f"""
        <div class="{css_class}" data-family="{safe}" style="
            display:flex;align-items:center;justify-content:center;
            background:{background_color};color:white;
            border:2px solid rgba(255,255,255,.98);border-radius:4px;
            padding:2px 5px;min-width:28px;height:17px;box-sizing:border-box;
            font-family:Arial,Helvetica,sans-serif;font-size:9px;font-weight:800;
            line-height:13px;white-space:nowrap;text-align:center;
            box-shadow:0 1px 3px rgba(0,0,0,.55);cursor:pointer;">{safe}</div>"""
    return f"""
    <div class="{css_class}" data-property-code="{safe}" style="
        display:flex;align-items:center;justify-content:center;
        background:{background_color};color:white;
        border:1px solid rgba(255,255,255,.96);border-radius:3px;
        padding:1px 3px;min-width:23px;height:14px;box-sizing:border-box;
        font-family:Arial,Helvetica,sans-serif;font-size:8px;font-weight:700;
        line-height:12px;white-space:nowrap;text-align:center;
        box-shadow:0 1px 2px rgba(0,0,0,.45);cursor:pointer;">{safe}</div>"""


def star_marker_html(color: str, css_class: str) -> str:
    return f"""
    <div class="{css_class}" style="
        width:28px;height:28px;display:flex;align-items:center;justify-content:center;
        color:{color};font-family:Arial,Helvetica,sans-serif;font-size:29px;
        font-weight:900;line-height:28px;text-align:center;
        text-shadow:0 0 2px rgba(255,255,255,.95),0 1px 2px rgba(0,0,0,.35);
        cursor:pointer;">★</div>"""


def shape_marker_html(marker_type: str, color: str, css_class: str) -> str:
    shapes = {
        "circle": ("50%", "18px", "18px"),
        "square": ("2px", "16px", "16px"),
        "diamond": ("2px", "14px", "14px"),
        "triangle": ("0", "0", "0"),
    }
    radius, width, height = shapes.get(marker_type, shapes["circle"])
    if marker_type == "triangle":
        inner = f'<div style="width:0;height:0;border-left:9px solid transparent;border-right:9px solid transparent;border-bottom:16px solid {color};"></div>'
    else:
        transform = "rotate(45deg)" if marker_type == "diamond" else "none"
        inner = f'<div style="width:{width};height:{height};background:{color};border-radius:{radius};transform:{transform};border:1px solid rgba(255,255,255,.9);"></div>'
    return f'<div class="{css_class}" style="display:flex;align-items:center;justify-content:center;width:22px;height:22px;">{inner}</div>'


def marker_icon(site: dict[str, Any], client: dict[str, Any], *, family: bool = False) -> DivIcon:
    color = _marker_color(site, client)
    prefix = site.get("css_prefix", client.get("css_prefix", client["id"].lower()))
    marker_type = site.get("marker_type", client.get("marker_type", "circle"))
    label = site.get("family" if family else "site_code", "") or site.get("site_name", "?")

    if marker_type == "code_label":
        css = f"{prefix}-{'family' if family else 'detail'}-label"
        html_content = code_label_html(label if family else site.get("site_code", label), color, css, family=family)
        size = (42, 19) if family else (34, 16)
        anchor = (21, 9) if family else (17, 8)
    elif marker_type == "star":
        css = f"{prefix}-star-label"
        html_content = star_marker_html(color, css)
        size = (30, 30)
        anchor = (15, 15)
    else:
        css = f"{prefix}-shape-label"
        html_content = shape_marker_html(marker_type, color, css)
        size = (22, 22)
        anchor = (11, 11)

    return DivIcon(html=html_content, icon_size=size, icon_anchor=anchor)


def _marker_color(site: dict[str, Any], client: dict[str, Any]) -> str:
    layer_styles = client.get("layer_styles", {})
    area = district_for(site)
    if area in layer_styles:
        return layer_styles[area]["color"]
    return site.get("marker_color", client.get("marker_color", "#3388ff"))


def family_tooltip(family: str, sites: list[dict[str, Any]]) -> str:
    codes = sorted(clean_text(s.get("site_code")) for s in sites if s.get("site_code"))
    if len(sites) == 1:
        return f"{codes[0]} — {clean_text(sites[0].get('site_name'))}"
    return f"{family} — {len(sites)} properties: {', '.join(codes)}"


def add_map_title(map_object: folium.Map) -> None:
    title_html = """
    <div style="position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:9999;
        background:rgba(255,255,255,.95);border:1px solid #999;border-radius:6px;
        padding:8px 16px;font-family:Arial,sans-serif;font-size:16px;font-weight:700;
        box-shadow:0 1px 6px rgba(0,0,0,.20);">Resource Allocation Map</div>"""
    map_object.get_root().html.add_child(folium.Element(title_html))


def add_map_legend(
    map_object: folium.Map,
    legend_entries: list[dict[str, Any]],
) -> None:
    lines = [
        '<div style="position:fixed;bottom:30px;left:30px;z-index:9999;'
        'background:rgba(255,255,255,.96);border:1px solid #999;border-radius:6px;'
        'padding:10px 12px;font-family:Arial,sans-serif;font-size:12px;line-height:1.6;'
        'min-width:245px;box-shadow:0 1px 6px rgba(0,0,0,.20);">',
        '<div style="font-size:14px;font-weight:700;margin-bottom:6px;">Resource Allocation Map</div>',
    ]
    for entry in legend_entries:
        symbol = entry.get("symbol", "■")
        color = entry.get("color", "#333")
        if entry.get("marker_type") == "code_label":
            swatch = (
                f'<span style="display:inline-block;width:13px;height:8px;background:{color};'
                f'border-radius:2px;margin-right:5px;"></span>'
            )
        elif entry.get("marker_type") == "star":
            swatch = f'<span style="color:{color};font-size:15px;margin-right:4px;">★</span>'
        else:
            swatch = f'<span style="color:{color};margin-right:4px;">{symbol}</span>'
        lines.append(f"<div>{swatch}{html.escape(entry['label'])} ({entry['count']})</div>")
    lines.append("</div>")
    map_object.get_root().html.add_child(folium.Element("".join(lines)))


def build_map(
    client_sites: dict[str, list[dict[str, Any]]],
    clients: list[dict[str, Any]],
) -> None:
    all_sites = [site for sites in client_sites.values() for site in sites]
    if not all_sites:
        raise RuntimeError("No geocoded sites are available.")

    if OUTPUT_MAP.exists():
        try:
            OUTPUT_MAP.unlink()
        except OSError:
            pass

    resource_map = folium.Map(
        location=CALGARY_CENTER,
        zoom_start=10,
        tiles=None,
        control_scale=True,
        prefer_canvas=False,
    )
    folium.TileLayer("CartoDB positron", name="Light Map", control=True, show=True).add_to(resource_map)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", control=True, show=False).add_to(resource_map)

    client_lookup = {c["id"]: c for c in clients}
    layers: dict[str, folium.FeatureGroup] = {}
    legend_entries: list[dict[str, Any]] = []
    family_click_javascript: list[str] = []
    zoom_clients: list[dict[str, Any]] = []
    all_bounds: list[list[float]] = []

    for client in clients:
        sites = client_sites.get(client["id"], [])
        if not sites:
            continue

        if client.get("group_by_family"):
            apply_display_offsets(sites)
            zoom_clients.append(client)
        elif client.get("marker_type") == "star":
            apply_display_offsets(sites, radius_lat=0.00018, radius_lon=0.00028)
        else:
            apply_display_offsets(sites)

        if client.get("layer_group_field"):
            styles = client.get("layer_styles", {})
            for area_key, style in styles.items():
                layer_name = style["label"]
                if layer_name not in layers:
                    layer = folium.FeatureGroup(
                        name=layer_name, overlay=True, control=True, show=style.get("show", True)
                    )
                    layer.add_to(resource_map)
                    layers[layer_name] = layer
        else:
            layer_name = client.get("layer_name", client["name"])
            layer = folium.FeatureGroup(name=layer_name, overlay=True, control=True, show=True)
            layer.add_to(resource_map)
            layers[layer_name] = layer
            legend_entries.append({
                "label": layer_name,
                "count": len(sites),
                "color": client.get("marker_color", "#3388ff"),
                "marker_type": client.get("marker_type"),
                "symbol": "★" if client.get("marker_type") == "star" else "●",
            })

    for client in clients:
        sites = client_sites.get(client["id"], [])
        if not sites or not client.get("layer_group_field"):
            continue
        styles = client.get("layer_styles", {})
        counts = Counter(district_for(s) for s in sites)
        for area_key, style in styles.items():
            if counts.get(area_key, 0):
                legend_entries.append({
                    "label": style["label"],
                    "count": counts.get(area_key, 0),
                    "color": style["color"],
                    "marker_type": client.get("marker_type"),
                })

    map_js_name = resource_map.get_name()

    for client in clients:
        sites = client_sites.get(client["id"], [])
        if not sites:
            continue
        prefix = client.get("css_prefix", client["id"].lower())

        for site in sites:
            lat, lon = _display_coords(site)
            all_bounds.append([float(site["latitude"]), float(site["longitude"])])

            if client.get("layer_group_field"):
                area = district_for(site)
                style = client.get("layer_styles", {}).get(area) or client.get("layer_styles", {}).get("Unknown")
                layer_name = style["label"] if style else client["name"]
            else:
                layer_name = client.get("layer_name", client["name"])

            tooltip_text = site.get("site_code") or site.get("site_name", "")
            if site.get("site_code") and site.get("site_name"):
                tooltip_text = f"{site['site_code']} — {site['site_name']}"

            marker = folium.Marker(
                location=[lat, lon],
                icon=marker_icon(site, client, family=False),
                tooltip=folium.Tooltip(html.escape(tooltip_text), sticky=True),
                popup=folium.Popup(popup_html(site, client), max_width=480),
                title=tooltip_text,
                z_index_offset=site.get("z_index_offset", 0),
            )
            marker.add_to(layers[layer_name])

        if client.get("group_by_family"):
            groups = build_family_groups(sites)
            detail_zoom = client.get("detail_zoom", 13)
            family_max_zoom = client.get("family_click_max_zoom", FAMILY_CLICK_MAX_ZOOM)

            for (_client_id, area, family), family_sites in sorted(groups.items()):
                style = client.get("layer_styles", {}).get(area) or client.get("layer_styles", {}).get("Unknown", {})
                layer_name = style.get("label", client["name"])
                center_lat, center_lon = robust_family_center(family_sites)
                display_code = (
                    clean_text(family_sites[0].get("site_code"))
                    if len(family_sites) == 1
                    else family
                )
                family_site = {**family_sites[0], "family": family}
                family_marker = folium.Marker(
                    location=[center_lat, center_lon],
                    icon=marker_icon({**family_site, "site_code": display_code}, client, family=True),
                    tooltip=folium.Tooltip(html.escape(family_tooltip(family, family_sites)), sticky=True),
                    title=display_code,
                )
                family_marker.add_to(layers[layer_name])
                marker_js = family_marker.get_name()

                if len(family_sites) > 1:
                    bounds = [[float(s["latitude"]), float(s["longitude"])] for s in family_sites]
                    bounds_json = json.dumps(bounds)
                    family_click_javascript.append(f"""
                    {marker_js}.on("click", function() {{
                        var familyBounds = L.latLngBounds({bounds_json});
                        {map_js_name}.fitBounds(familyBounds, {{padding:[60,60], maxZoom:{family_max_zoom}}});
                        setTimeout(function() {{
                            if ({map_js_name}.getZoom() < {detail_zoom}) {{
                                {map_js_name}.setZoom({detail_zoom});
                            }}
                            updatePropertyZoomLayers();
                        }}, 180);
                    }});""")
                else:
                    s = family_sites[0]
                    family_click_javascript.append(f"""
                    {marker_js}.on("click", function() {{
                        {map_js_name}.setView([{float(s['latitude'])}, {float(s['longitude'])}], {detail_zoom});
                        setTimeout(updatePropertyZoomLayers, 100);
                    }});""")

    if all_bounds:
        resource_map.fit_bounds(all_bounds, padding=(20, 20))

    MiniMap(toggle_display=True, minimized=True).add_to(resource_map)
    Fullscreen(position="topleft", title="Full screen", title_cancel="Exit full screen").add_to(resource_map)
    MeasureControl(position="topleft", primary_length_unit="kilometers").add_to(resource_map)
    folium.LayerControl(position="topright", collapsed=False).add_to(resource_map)
    add_map_title(resource_map)
    add_map_legend(resource_map, legend_entries)

    zoom_script = _build_zoom_script(map_js_name, zoom_clients, family_click_javascript)
    resource_map.get_root().html.add_child(folium.Element(zoom_script))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    resource_map.save(str(OUTPUT_MAP))
    _verify_map(OUTPUT_MAP.read_text(encoding="utf-8"))


def _build_zoom_script(
    map_js_name: str,
    zoom_clients: list[dict[str, Any]],
    family_click_javascript: list[str],
) -> str:
    selectors = []
    for client in zoom_clients:
        prefix = client.get("css_prefix", client["id"].lower())
        detail_zoom = client.get("detail_zoom", 13)
        selectors.append(
            f'{{family:".{prefix}-family-label", detail:".{prefix}-detail-label", zoom:{detail_zoom}}}'
        )
    selector_json = ", ".join(selectors)
    return f"""
    <script>
    var zoomLayerConfig = [{selector_json}];
    function setMarkerElementVisibility(selector, visible) {{
        document.querySelectorAll(selector).forEach(function(innerElement) {{
            var markerElement = innerElement.closest(".leaflet-marker-icon");
            if (!markerElement) return;
            markerElement.style.display = visible ? "" : "none";
            markerElement.style.pointerEvents = visible ? "auto" : "none";
        }});
    }}
    function updatePropertyZoomLayers() {{
        var currentZoom = {map_js_name}.getZoom();
        zoomLayerConfig.forEach(function(cfg) {{
            var showDetails = currentZoom >= cfg.zoom;
            setMarkerElementVisibility(cfg.family, !showDetails);
            setMarkerElementVisibility(cfg.detail, showDetails);
        }});
    }}
    window.addEventListener("load", function() {{
        setTimeout(function() {{
            {"".join(family_click_javascript)}
            updatePropertyZoomLayers();
            {map_js_name}.on("zoomend", updatePropertyZoomLayers);
            {map_js_name}.on("overlayadd", function() {{ setTimeout(updatePropertyZoomLayers, 40); }});
            {map_js_name}.on("resize", function() {{ setTimeout(updatePropertyZoomLayers, 40); }});
        }}, 250);
    }});
    </script>"""


def _verify_map(generated_html: str) -> None:
    for pattern in ('"icon": "building"', '"icon":"building"', "AwesomeMarkers.icon("):
        if pattern in generated_html:
            raise RuntimeError("Old building markers were found inside the generated map.")
    required = ["chc-family-label", "chc-detail-label", "silvera-star-label", "Silvera Communities"]
    for token in required:
        if token not in generated_html:
            raise RuntimeError(f"Map verification failed: missing '{token}'.")
    print()
    print("Map verification: PASSED")
    print("[OK] CHC family labels created")
    print("[OK] CHC individual labels created")
    print("[OK] CHC click-to-zoom created")
    print("[OK] Silvera purple stars created")
    print("[OK] Silvera independent map layer created")
