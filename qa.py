"""Coordinate quality checks and review report generation."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

from map_config import OUTPUT_DIR
from utils import (
    address_contains_number,
    extract_leading_street_number,
    haversine_km,
    robust_family_center,
)


REVIEW_FIELDS = [
    "Client",
    "Site Name",
    "Site Code",
    "Address",
    "Latitude",
    "Longitude",
    "Coordinate Source",
    "Issue Type",
    "Details",
]


def _review_row(
    site: dict[str, Any],
    issue_type: str,
    details: str,
) -> dict[str, str]:
    return {
        "Client": site.get("client_name", ""),
        "Site Name": site.get("site_name", ""),
        "Site Code": site.get("site_code", ""),
        "Address": site.get("address", ""),
        "Latitude": f"{float(site['latitude']):.6f}",
        "Longitude": f"{float(site['longitude']):.6f}",
        "Coordinate Source": site.get("coordinate_source", ""),
        "Issue Type": issue_type,
        "Details": details,
    }


def collect_coordinate_reviews(
    all_sites: list[dict[str, Any]],
    qa_config: dict[str, Any],
) -> list[dict[str, str]]:
    reviews: list[dict[str, str]] = []
    precision = qa_config.get("duplicate_coordinate_precision", 5)
    near_meters = qa_config.get("duplicate_distance_meters", 15)
    outlier_km = qa_config.get("family_outlier_distance_km", 2.0)

    for site in all_sites:
        if site.get("coordinate_source") == "Manual":
            reviews.append(
                _review_row(
                    site,
                    "Manual Override",
                    "Coordinates supplied in source workbook (informational).",
                )
            )

        if site.get("approximate"):
            reviews.append(
                _review_row(
                    site,
                    "Approximate Geocode",
                    "Geocoder result may be broad or imprecise; verify on map.",
                )
            )

        source_address = site.get("geocode_address") or site.get("address", "")
        matched = site.get("matched_address", "")
        if source_address and matched and site.get("coordinate_source") == "Geocoder":
            number = extract_leading_street_number(source_address)
            if number and not address_contains_number(matched, number):
                reviews.append(
                    _review_row(
                        site,
                        "Possible Street Number Mismatch",
                        f"Requested '{number}' but geocoder returned '{matched}'.",
                    )
                )

    reviews.extend(_duplicate_reviews(all_sites, precision, near_meters))
    reviews.extend(_family_outlier_reviews(all_sites, outlier_km))
    return reviews


def _duplicate_reviews(
    sites: list[dict[str, Any]],
    precision: int,
    near_meters: float,
) -> list[dict[str, str]]:
    reviews: list[dict[str, str]] = []
    buckets: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for site in sites:
        key = (
            round(float(site["latitude"]), precision),
            round(float(site["longitude"]), precision),
        )
        buckets[key].append(site)

    for coord, group in buckets.items():
        if len(group) < 2:
            continue
        unique_keys = {
            (s.get("client_id"), s.get("site_code") or s.get("site_name"))
            for s in group
        }
        if len(unique_keys) < 2:
            continue
        names = ", ".join(
            f"{s.get('client_name')}: {s.get('site_code') or s.get('site_name')}"
            for s in group
        )
        for site in group:
            reviews.append(
                _review_row(
                    site,
                    "Duplicate / Near-Duplicate Coordinates",
                    f"Shares coordinates {coord[0]:.{precision}f}, {coord[1]:.{precision}f} with: {names}",
                )
            )
    return reviews


def _family_outlier_reviews(
    sites: list[dict[str, Any]],
    outlier_km: float,
) -> list[dict[str, str]]:
    reviews: list[dict[str, str]] = []
    families: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for site in sites:
        if not site.get("group_by_family") or not site.get("family"):
            continue
        key = (site["client_id"], site.get("area", "Unknown"), site["family"])
        families[key].append(site)

    for family_sites in families.values():
        if len(family_sites) < 2:
            continue
        center_lat, center_lon = robust_family_center(family_sites)
        distances = [
            haversine_km(center_lat, center_lon, float(s["latitude"]), float(s["longitude"]))
            for s in family_sites
        ]
        median_dist = sorted(distances)[len(distances) // 2]
        for site, dist in zip(family_sites, distances):
            if dist > outlier_km and dist > median_dist * 3 and dist > median_dist + 0.5:
                reviews.append(
                    _review_row(
                        site,
                        "Family Outlier",
                        (
                            f"{dist:.2f} km from family center "
                            f"(threshold {outlier_km} km; median member distance {median_dist:.2f} km)."
                        ),
                    )
                )
    return reviews


def write_coordinate_review_csv(
    reviews: list[dict[str, str]],
    output_path: Path,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not reviews:
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        return
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(reviews)
