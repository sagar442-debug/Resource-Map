"""Geocoding, cache management, coordinate resolution, and address-quality checks."""

from __future__ import annotations

import json
import re
from typing import Any

from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from map_config import (
    CACHE_FILE,
    GEOCODE_DELAY_SECONDS,
    GEOCODER_USER_AGENT,
    LEGACY_CACHE_NAMESPACES,
)
from utils import (
    build_geocode_queries,
    clean_text,
    parse_coordinate,
    within_calgary_bounds,
)


BROAD_NOMINATIM_TYPES = {
    "suburb",
    "neighbourhood",
    "neighborhood",
    "city",
    "town",
    "village",
    "county",
    "municipality",
    "administrative",
}

QUADRANTS = {"NE", "NW", "SE", "SW"}

STREET_TYPE_TOKENS = {
    "RD", "ROAD", "ST", "STREET", "AVE", "AV", "AVENUE", "DR", "DRIVE",
    "BLVD", "BV", "BOULEVARD", "TR", "TRAIL", "PL", "PLACE", "CL", "CLOSE",
    "CR", "CRESCENT", "LN", "LANE", "CT", "COURT", "CO", "WAY", "WY",
    "PK", "PARK", "PT", "POINT", "RI", "RISE", "SQ", "SQUARE", "TC", "TE",
    "TERRACE", "HT", "HEIGHTS", "GA", "GATE", "GD", "GARDENS", "GR", "GREEN",
    "MR", "MANOR", "ME", "MEWS", "CM", "COMMON", "LK", "LINK", "VW", "VIEW",
}

GENERIC_ADDRESS_TOKENS = {"CALGARY", "ALBERTA", "AB", "CANADA"}


def _tokens(text: str) -> list[str]:
    text = clean_text(text).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return [token for token in text.split() if token]


def _extract_civic_number(address: str) -> str | None:
    """Return the leading civic/building number, not the numbered street."""
    first_part = clean_text(address).split(",", 1)[0].strip()
    match = re.match(r"^\s*(\d+[A-Za-z]?)\b", first_part)
    return match.group(1).upper() if match else None


def _extract_returned_house_number(matched_address: str, raw: dict[str, Any]) -> str | None:
    if isinstance(raw, dict):
        details = raw.get("address")
        if isinstance(details, dict):
            value = clean_text(details.get("house_number") or details.get("building"))
            if value:
                match = re.match(r"^\s*(\d+[A-Za-z]?)\b", value)
                if match:
                    return match.group(1).upper()

    first_part = clean_text(matched_address).split(",", 1)[0].strip()
    match = re.match(r"^\s*(\d+[A-Za-z]?)\b", first_part)
    return match.group(1).upper() if match else None


def _extract_quadrant(text: str) -> str | None:
    for token in reversed(_tokens(text)):
        if token in QUADRANTS:
            return token
    return None


def _road_text(matched_address: str, raw: dict[str, Any]) -> str:
    if isinstance(raw, dict):
        details = raw.get("address")
        if isinstance(details, dict):
            for key in ("road", "pedestrian", "residential", "highway", "path"):
                value = clean_text(details.get(key))
                if value:
                    return value

    # For cached results raw addressdetails are not available. Keep the first
    # couple of comma-separated pieces because Nominatim can format a result as
    # "8540, Silver Springs Road NW, ...".
    parts = [part.strip() for part in clean_text(matched_address).split(",") if part.strip()]
    return " ".join(parts[:2]) if parts else ""


def _street_tokens(address: str, *, matched: bool = False, raw: dict[str, Any] | None = None) -> set[str]:
    base = _road_text(address, raw or {}) if matched else clean_text(address).split(",", 1)[0].strip()
    tokens = _tokens(base)

    # Remove only the leading civic number. Keep numbered street names such as 11 St.
    if tokens and re.fullmatch(r"\d+[A-Z]?", tokens[0]):
        tokens = tokens[1:]

    result: set[str] = set()
    for token in tokens:
        if token in STREET_TYPE_TOKENS or token in QUADRANTS or token in GENERIC_ADDRESS_TOKENS:
            continue
        result.add(token)
    return result


def _street_similarity(requested: str, matched_address: str, raw: dict[str, Any]) -> float | None:
    requested_tokens = _street_tokens(requested)
    returned_tokens = _street_tokens(matched_address, matched=True, raw=raw)
    if not requested_tokens or not returned_tokens:
        return None
    return len(requested_tokens & returned_tokens) / max(len(requested_tokens), 1)


def evaluate_geocode_quality(
    requested_address: str,
    matched_address: str,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a geocoder result as Exact, Approximate, or Unknown."""
    raw = raw or {}
    requested_address = clean_text(requested_address)
    matched_address = clean_text(matched_address)

    requested_number = _extract_civic_number(requested_address)
    returned_number = _extract_returned_house_number(matched_address, raw)
    requested_quadrant = _extract_quadrant(requested_address)
    returned_quadrant = _extract_quadrant(_road_text(matched_address, raw) or matched_address)
    street_similarity = _street_similarity(requested_address, matched_address, raw)

    issues: list[dict[str, str]] = []
    score = 0
    hard_mismatch = False

    if requested_number:
        if returned_number == requested_number:
            score += 60
        elif returned_number:
            score -= 55
            hard_mismatch = True
            issues.append({
                "type": "Civic Number Mismatch",
                "details": f"Requested civic number {requested_number} but geocoder returned {returned_number}.",
            })
        else:
            score += 5
            issues.append({
                "type": "Street Number Missing From Geocoder Result",
                "details": f"Requested civic number {requested_number} was not present in the geocoder result.",
            })

    if street_similarity is not None:
        if street_similarity >= 0.75:
            score += 25
        elif street_similarity >= 0.50:
            score += 10
            issues.append({
                "type": "Possible Street Name Mismatch",
                "details": "Geocoder street name only partially matches the requested address.",
            })
        else:
            score -= 35
            hard_mismatch = True
            issues.append({
                "type": "Possible Street Name Mismatch",
                "details": "Geocoder street name does not closely match the requested address.",
            })

    if requested_quadrant and returned_quadrant:
        if requested_quadrant == returned_quadrant:
            score += 10
        else:
            score -= 35
            hard_mismatch = True
            issues.append({
                "type": "Quadrant Mismatch",
                "details": f"Requested quadrant {requested_quadrant} but geocoder returned {returned_quadrant}.",
            })

    address_type = ""
    if isinstance(raw, dict):
        address_type = clean_text(raw.get("addresstype") or raw.get("type") or "").lower()
    if address_type in BROAD_NOMINATIM_TYPES:
        score -= 10
        issues.append({
            "type": "Approximate Geocode",
            "details": f"Nominatim returned a broad '{address_type}' result.",
        })

    if requested_number:
        exact = (
            returned_number == requested_number
            and not hard_mismatch
            and (street_similarity is None or street_similarity >= 0.50)
            and (
                not requested_quadrant
                or not returned_quadrant
                or requested_quadrant == returned_quadrant
            )
        )
        quality = "Exact" if exact else "Approximate"
    else:
        if (
            matched_address
            and not hard_mismatch
            and street_similarity is not None
            and street_similarity >= 0.75
            and address_type not in BROAD_NOMINATIM_TYPES
        ):
            quality = "Exact"
        elif matched_address:
            quality = "Approximate"
        else:
            quality = "Unknown"

    return {
        "coordinate_quality": quality,
        "approximate": quality != "Exact",
        "quality_score": score,
        "quality_issues": issues,
        "requested_civic_number": requested_number or "",
        "returned_civic_number": returned_number or "",
    }


def _addresses_compatible(current_address: str, cached_address_or_query: str) -> bool:
    """Return False when a workbook address edit makes a cached request obsolete."""
    current_address = clean_text(current_address)
    cached_address_or_query = clean_text(cached_address_or_query)
    if not current_address or not cached_address_or_query:
        return True

    current_number = _extract_civic_number(current_address)
    cached_number = _extract_civic_number(cached_address_or_query)
    if current_number and cached_number and current_number != cached_number:
        return False

    current_quadrant = _extract_quadrant(current_address)
    cached_quadrant = _extract_quadrant(cached_address_or_query)
    if current_quadrant and cached_quadrant and current_quadrant != cached_quadrant:
        return False

    current_street = _street_tokens(current_address)
    cached_street = _street_tokens(cached_address_or_query)
    if current_street and cached_street and not (current_street & cached_street):
        return False

    return True


# =============================================================================
# CACHE
# =============================================================================


def load_cache() -> dict[str, Any]:
    if not CACHE_FILE.exists():
        return {"version": 4, "clients": {}}
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Could not read geocode cache: {exc}") from exc
    if not isinstance(cache, dict):
        raise ValueError("geocode_cache.json is not a valid dictionary.")
    _migrate_cache(cache)
    cache["version"] = 4
    return cache


def _migrate_cache(cache: dict[str, Any]) -> None:
    """Migrate legacy namespaces (sites, silvera_sites) into clients.*."""
    clients = cache.setdefault("clients", {})
    for client_id, legacy_key in LEGACY_CACHE_NAMESPACES.items():
        if legacy_key in cache and isinstance(cache[legacy_key], dict):
            existing = clients.setdefault(client_id, {})
            for key, value in cache[legacy_key].items():
                existing.setdefault(key, value)


def save_cache(cache: dict[str, Any]) -> None:
    CACHE_FILE.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def cache_key_for_site(client: dict[str, Any], site: dict[str, Any]) -> str:
    columns = client["columns"]
    parts: list[str] = []
    for field in client.get("cache_key_fields", ["site_code", "address"]):
        if field in site:
            parts.append(clean_text(site.get(field)))
        elif field in columns:
            parts.append(clean_text(site["metadata"].get(columns[field], "")))
        else:
            parts.append(clean_text(site["metadata"].get(field, "")))
    return "|".join(parts)


# =============================================================================
# LIVE GEOCODING
# =============================================================================


def create_geocoder():
    geolocator = Nominatim(user_agent=GEOCODER_USER_AGENT, timeout=15)
    return RateLimiter(
        geolocator.geocode,
        min_delay_seconds=GEOCODE_DELAY_SECONDS,
        max_retries=2,
        error_wait_seconds=5.0,
        swallow_exceptions=True,
    )


def try_geocode_queries(
    queries: list[str],
    geocode,
    *,
    requested_address: str = "",
) -> tuple[dict[str, Any] | None, int, str, bool]:
    """
    Try every candidate query until an Exact match is found.

    Approximate Calgary results are remembered as fallbacks rather than being
    accepted immediately.
    """
    requests = 0
    last_reason = "No result returned."
    best_approximate: dict[str, Any] | None = None
    requested_address = clean_text(requested_address)

    for query in queries:
        requests += 1
        try:
            location = geocode(
                query,
                exactly_one=True,
                country_codes="ca",
                language="en",
                addressdetails=True,
            )
        except Exception as exc:
            location = None
            last_reason = f"Geocoder error: {exc}"

        if location is None:
            continue

        lat = float(location.latitude)
        lon = float(location.longitude)
        if not within_calgary_bounds(lat, lon):
            last_reason = f"Result outside Calgary bounds: {lat:.6f}, {lon:.6f}"
            continue

        matched_address = clean_text(location.address)
        raw = location.raw if hasattr(location, "raw") and isinstance(location.raw, dict) else {}
        quality = evaluate_geocode_quality(requested_address or query, matched_address, raw)

        candidate = {
            "latitude": lat,
            "longitude": lon,
            "matched_address": matched_address,
            "query": query,
            **quality,
        }

        if quality["coordinate_quality"] == "Exact":
            return candidate, requests, "", False

        if (
            best_approximate is None
            or candidate["quality_score"] > best_approximate.get("quality_score", -999999)
        ):
            best_approximate = candidate

    if best_approximate is not None:
        return best_approximate, requests, "", True

    return None, requests, last_reason, False


# Backward compatibility in case another project module imports these helpers.
def _is_approximate_geocode(query: str, matched_address: str, raw: dict) -> bool:
    return evaluate_geocode_quality(query, matched_address, raw)["approximate"]


def _address_has_number(address: str, number: str) -> bool:
    return re.search(rf"\b{re.escape(number)}\b", clean_text(address)) is not None


# =============================================================================
# MANUAL COORDINATES
# =============================================================================


def resolve_manual_coordinates(site: dict[str, Any]) -> dict[str, Any] | None:
    """Return coordinate dict if valid manual workbook lat/lon exist."""
    metadata = site.get("metadata") or {}

    lat_value = site.get("latitude")
    lon_value = site.get("longitude")

    if clean_text(lat_value) == "":
        lat_value = metadata.get("Latitude") or metadata.get("latitude")
    if clean_text(lon_value) == "":
        lon_value = metadata.get("Longitude") or metadata.get("longitude")

    lat = parse_coordinate(lat_value)
    lon = parse_coordinate(lon_value)
    if lat is None or lon is None:
        return None
    if not within_calgary_bounds(lat, lon):
        return None

    return {
        "latitude": lat,
        "longitude": lon,
        "matched_address": "Manual coordinates from source workbook",
        "coordinate_source": "Manual",
        "coordinate_quality": "Verified",
        "approximate": False,
        "quality_issues": [],
        "quality_score": 100,
    }


def _current_geocode_address(site: dict[str, Any]) -> str:
    return clean_text(site.get("geocode_address")) or clean_text(site.get("address"))


def _cache_entry_is_stale(site: dict[str, Any], cached: dict[str, Any]) -> bool:
    current_geocode = _current_geocode_address(site)
    current_source = clean_text(site.get("address")) or current_geocode

    stored_geocode = clean_text(cached.get("geocode_address"))
    if stored_geocode and not _addresses_compatible(current_geocode, stored_geocode):
        return True

    stored_source = clean_text(cached.get("source_address"))
    if stored_source and not _addresses_compatible(current_source, stored_source):
        return True

    # Legacy cache entries often have only the query that produced the result.
    stored_query = clean_text(cached.get("query"))
    if stored_query and not _addresses_compatible(current_geocode, stored_query):
        return True

    return False


def _reevaluate_cached_quality(site: dict[str, Any], cached: dict[str, Any]) -> dict[str, Any]:
    matched_address = clean_text(cached.get("matched_address"))
    requested_address = _current_geocode_address(site)

    if not matched_address:
        quality = clean_text(cached.get("coordinate_quality")) or "Unknown"
        return {
            "coordinate_quality": quality,
            "approximate": quality not in {"Exact", "Verified"},
            "quality_issues": cached.get("quality_issues", []),
            "quality_score": cached.get("quality_score", 0),
        }

    quality = evaluate_geocode_quality(requested_address, matched_address, {})

    cached["coordinate_quality"] = quality["coordinate_quality"]
    cached["approximate"] = quality["approximate"]
    cached["quality_issues"] = quality["quality_issues"]
    cached["quality_score"] = quality["quality_score"]
    cached["requested_civic_number"] = quality["requested_civic_number"]
    cached["returned_civic_number"] = quality["returned_civic_number"]

    return quality


# =============================================================================
# CLIENT RESOLUTION
# =============================================================================


def geocode_client_sites(
    client: dict[str, Any],
    sites: list[dict[str, Any]],
    *,
    retry_failed: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], int]:
    cache = load_cache()
    client_cache = cache.setdefault("clients", {}).setdefault(client["id"], {})
    geocode = create_geocoder()
    located: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    new_requests = 0
    total = len(sites)

    for index, site in enumerate(sites, start=1):
        label = site.get("site_code") or site.get("site_name") or "?"
        key = cache_key_for_site(client, site)

        # 1. Manual workbook coordinates always win.
        manual = resolve_manual_coordinates(site)
        if manual:
            located.append({**site, **manual})
            print(f"[{client['id']} {index:>3}/{total}] {label:<20} manual coordinates (Verified)")
            continue

        cached = client_cache.get(key)

        # If the workbook address changed, do not silently use coordinates from
        # the old address. The old cache entry stays in the JSON but is ignored.
        if cached and _cache_entry_is_stale(site, cached):
            print(f"[{client['id']} {index:>3}/{total}] {label:<20} cached address changed; re-geocoding")
            cached = None

        # 2. Cached success, but re-evaluate old matches before trusting them.
        if cached and cached.get("status") == "ok":
            quality = _reevaluate_cached_quality(site, cached)
            cached["source_address"] = clean_text(site.get("address"))
            cached["geocode_address"] = _current_geocode_address(site)

            result = {
                **site,
                "latitude": float(cached["latitude"]),
                "longitude": float(cached["longitude"]),
                "matched_address": cached.get("matched_address", ""),
                "coordinate_source": "Cache",
                "coordinate_quality": quality["coordinate_quality"],
                "approximate": quality["approximate"],
                "quality_issues": quality.get("quality_issues", []),
                "quality_score": quality.get("quality_score", 0),
            }
            located.append(result)
            print(
                f"[{client['id']} {index:>3}/{total}] {label:<20} "
                f"cached ({quality['coordinate_quality']})"
            )
            continue

        if cached and cached.get("status") == "failed" and not retry_failed:
            failures.append(_failure_record(client, site, cached))
            print(f"[{client['id']} {index:>3}/{total}] {label:<20} cached failure")
            continue

        # 3. Live geocoding.
        address = _current_geocode_address(site)
        postal = clean_text(site.get("postal_code"))
        queries = build_geocode_queries(address, postal)
        print(f"[{client['id']} {index:>3}/{total}] {label:<20} geocoding...", flush=True)

        matched, request_count, reason, approximate = try_geocode_queries(
            queries,
            geocode,
            requested_address=address,
        )
        new_requests += request_count

        if matched:
            client_cache[key] = {
                "status": "ok",
                **matched,
                "site_code": site.get("site_code", ""),
                "site_name": site.get("site_name", ""),
                "source_address": clean_text(site.get("address")),
                "geocode_address": address,
            }
            result = {
                **site,
                "latitude": matched["latitude"],
                "longitude": matched["longitude"],
                "matched_address": matched["matched_address"],
                "coordinate_source": "Geocoder",
                "coordinate_quality": matched.get(
                    "coordinate_quality",
                    "Approximate" if approximate else "Exact",
                ),
                "approximate": approximate,
                "quality_issues": matched.get("quality_issues", []),
                "quality_score": matched.get("quality_score", 0),
            }
            located.append(result)
            print(
                f"             -> {matched['latitude']:.6f}, {matched['longitude']:.6f} "
                f"({result['coordinate_quality']})"
            )
        else:
            client_cache[key] = {
                "status": "failed",
                "site_code": site.get("site_code", ""),
                "site_name": site.get("site_name", ""),
                "source_address": clean_text(site.get("address")),
                "geocode_address": address,
                "reason": reason,
                "queries": queries,
            }
            failures.append(_failure_record(client, site, client_cache[key], reason, queries))
            print(f"             -> NOT FOUND ({reason})")

        save_cache(cache)

    # Also persists new quality classifications for legacy cache entries.
    save_cache(cache)
    return located, failures, new_requests


def _failure_record(
    client: dict[str, Any],
    site: dict[str, Any],
    cached: dict[str, Any],
    reason: str = "",
    queries: list[str] | None = None,
) -> dict[str, str]:
    return {
        "Client": client["name"],
        "Site Name": site.get("site_name", ""),
        "Site Code": site.get("site_code", ""),
        "Address": clean_text(site.get("address")),
        "Area": site.get("area", ""),
        "Reason": reason or cached.get("reason", "Previously not found"),
        "Attempted Queries": " | ".join(queries or cached.get("queries", [])),
    }
