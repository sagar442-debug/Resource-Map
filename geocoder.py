"""Geocoding, cache management, and coordinate resolution."""

from __future__ import annotations

import json
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


def load_cache() -> dict[str, Any]:
    if not CACHE_FILE.exists():
        return {"version": 3, "clients": {}}
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Could not read geocode cache: {exc}") from exc
    if not isinstance(cache, dict):
        raise ValueError("geocode_cache.json is not a valid dictionary.")
    _migrate_cache(cache)
    cache["version"] = 3
    return cache


def _migrate_cache(cache: dict[str, Any]) -> None:
    """Migrate legacy v2 namespaces (sites, silvera_sites) into clients.*."""
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
) -> tuple[dict[str, Any] | None, int, str, bool]:
    """Returns (result, request_count, reason, is_approximate)."""
    requests = 0
    last_reason = "No result returned."
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
        matched = clean_text(location.address)
        approximate = _is_approximate_geocode(query, matched, location.raw if hasattr(location, "raw") else {})
        return (
            {
                "latitude": lat,
                "longitude": lon,
                "matched_address": matched,
                "query": query,
                "approximate": approximate,
            },
            requests,
            "",
            approximate,
        )
    return None, requests, last_reason, False


def _is_approximate_geocode(query: str, matched_address: str, raw: dict) -> bool:
    query_number = None
    for part in query.split(","):
        part = part.strip()
        if part and part[0].isdigit():
            query_number = part.split()[0]
            break
    if query_number and not _address_has_number(matched_address, query_number):
        return True
    address_type = ""
    if isinstance(raw, dict):
        address_type = clean_text(raw.get("type", "")).lower()
    if address_type in {"suburb", "neighbourhood", "city", "town", "village", "county"}:
        return True
    return False


def _address_has_number(address: str, number: str) -> bool:
    import re
    return re.search(rf"\b{re.escape(number)}\b", address) is not None


def resolve_manual_coordinates(site: dict[str, Any]) -> dict[str, Any] | None:
    """Return coordinate dict if valid manual workbook lat/lon exist."""
    lat = parse_coordinate(site["metadata"].get("Latitude") or site["metadata"].get("latitude"))
    lon = parse_coordinate(site["metadata"].get("Longitude") or site["metadata"].get("longitude"))
    if lat is None or lon is None:
        return None
    if not within_calgary_bounds(lat, lon):
        return None
    return {
        "latitude": lat,
        "longitude": lon,
        "matched_address": "Manual coordinates from source workbook",
        "coordinate_source": "Manual",
        "approximate": False,
    }


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

        manual = resolve_manual_coordinates(site)
        if manual:
            result = {**site, **manual}
            located.append(result)
            print(f"[{client['id']} {index:>3}/{total}] {label:<20} manual coordinates")
            continue

        cached = client_cache.get(key)
        if cached and cached.get("status") == "ok":
            result = {
                **site,
                "latitude": float(cached["latitude"]),
                "longitude": float(cached["longitude"]),
                "matched_address": cached.get("matched_address", ""),
                "coordinate_source": "Cache",
                "approximate": cached.get("approximate", False),
            }
            located.append(result)
            print(f"[{client['id']} {index:>3}/{total}] {label:<20} cached")
            continue

        if cached and cached.get("status") == "failed" and not retry_failed:
            failures.append(_failure_record(client, site, cached))
            print(f"[{client['id']} {index:>3}/{total}] {label:<20} cached failure")
            continue

        address = clean_text(site.get("geocode_address")) or clean_text(site.get("address"))
        postal = clean_text(site.get("postal_code"))
        queries = build_geocode_queries(address, postal)
        print(f"[{client['id']} {index:>3}/{total}] {label:<20} geocoding...", flush=True)

        matched, request_count, reason, approximate = try_geocode_queries(queries, geocode)
        new_requests += request_count

        if matched:
            client_cache[key] = {
                "status": "ok",
                **matched,
                "site_code": site.get("site_code", ""),
                "site_name": site.get("site_name", ""),
            }
            result = {
                **site,
                "latitude": matched["latitude"],
                "longitude": matched["longitude"],
                "matched_address": matched["matched_address"],
                "coordinate_source": "Geocoder",
                "approximate": approximate,
            }
            located.append(result)
            print(f"             -> {matched['latitude']:.6f}, {matched['longitude']:.6f}")
        else:
            client_cache[key] = {
                "status": "failed",
                "site_code": site.get("site_code", ""),
                "site_name": site.get("site_name", ""),
                "reason": reason,
                "queries": queries,
            }
            failures.append(_failure_record(client, site, client_cache[key], reason, queries))
            print(f"             -> NOT FOUND ({reason})")

        save_cache(cache)

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
