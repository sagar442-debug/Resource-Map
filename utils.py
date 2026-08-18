"""Shared text, address, and geometry helpers."""

from __future__ import annotations

import math
import re
from typing import Any

from map_config import CALGARY_BOUNDS

STREET_TYPES = {
    "AV": "Ave", "AVE": "Ave", "ST": "St", "RD": "Rd", "DR": "Dr",
    "PL": "Pl", "CL": "Close", "CR": "Crescent", "LN": "Lane",
    "CO": "Court", "CT": "Court", "TR": "Trail", "TRAIL": "Trail",
    "WY": "Way", "WAY": "Way", "BV": "Blvd", "BL": "Blvd", "BLVD": "Blvd",
    "GR": "Green", "GA": "Gate", "GD": "Gardens", "HT": "Heights",
    "TC": "Terrace", "TE": "Terrace", "PT": "Point", "PK": "Park",
    "RI": "Rise", "RO": "Row", "SQ": "Square", "MR": "Manor", "ME": "Mews",
    "CM": "Common", "LK": "Link", "VW": "View",
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"none", "nan"}:
        return ""
    return text


def property_family(property_code: str, family_regex: str = r"^[A-Za-z]+") -> str:
    code = clean_text(property_code).upper()
    match = re.match(family_regex, code)
    if match:
        return match.group(0)
    return code


def normalize_address(address: str) -> str:
    text = re.sub(r"\s+", " ", address.strip())
    text = re.sub(
        r"\b0+(\d+)\s+(AV|AVE|ST|RD|DR|PL|CL|CR|LN|CO|CT|TR|WY|BV|BL|BLVD)\b",
        lambda m: f"{int(m.group(1))} {m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(\d{1,3})st\b", r"\1 St", text, flags=re.IGNORECASE)
    for short, full in sorted(STREET_TYPES.items(), key=lambda item: -len(item[0])):
        text = re.sub(rf"\b{re.escape(short)}\b", full, text, flags=re.IGNORECASE)
    if "calgary" not in text.lower():
        text += ", Calgary, Alberta, Canada"
    else:
        text = re.sub(r"\bCalgary\s+AB\b", "Calgary, Alberta", text, flags=re.IGNORECASE)
        if "canada" not in text.lower():
            text += ", Canada"
    text = re.sub(r"\s*,\s*", ", ", text)
    return text


def build_geocode_queries(address: str, postal_code: str = "") -> list[str]:
    address = clean_text(address)
    postal_code = clean_text(postal_code)
    if not address:
        return []
    candidates = [f"{address}, Calgary, Alberta, Canada"]
    if postal_code:
        candidates.append(f"{address}, Calgary, Alberta, {postal_code}, Canada")
    candidates.append(normalize_address(address))
    unique: list[str] = []
    seen: set[str] = set()
    for query in candidates:
        query = re.sub(r"\s+", " ", query).strip()
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(query)
    return unique


def within_calgary_bounds(lat: float, lon: float) -> bool:
    return (
        CALGARY_BOUNDS["min_lat"] <= lat <= CALGARY_BOUNDS["max_lat"]
        and CALGARY_BOUNDS["min_lon"] <= lon <= CALGARY_BOUNDS["max_lon"]
    )


def parse_coordinate(value: Any) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def extract_leading_street_number(address: str) -> str | None:
    match = re.match(r"^\s*(\d+[A-Za-z]?)\b", clean_text(address))
    return match.group(1) if match else None


def address_contains_number(address: str, number: str) -> bool:
    if not number:
        return True
    return re.search(rf"\b{re.escape(number)}\b", clean_text(address)) is not None


def median_value(values: list[float]) -> float:
    sorted_values = sorted(values)
    count = len(sorted_values)
    mid = count // 2
    if count % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2


def robust_family_center(sites: list[dict[str, Any]]) -> tuple[float, float]:
    """Medoid: median lat/lon, then nearest actual site coordinates."""
    if len(sites) == 1:
        site = sites[0]
        return float(site["latitude"]), float(site["longitude"])
    lats = [float(s["latitude"]) for s in sites]
    lons = [float(s["longitude"]) for s in sites]
    med_lat = median_value(lats)
    med_lon = median_value(lons)
    best_site = min(
        sites,
        key=lambda s: haversine_km(
            med_lat, med_lon, float(s["latitude"]), float(s["longitude"])
        ),
    )
    return float(best_site["latitude"]), float(best_site["longitude"])
