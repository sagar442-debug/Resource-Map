#!/usr/bin/env python3
"""Create the multi-client Resource Allocation Map."""

from __future__ import annotations

import argparse
import csv
import webbrowser
from collections import Counter
from pathlib import Path

from data_loader import load_client_sites
from geocoder import geocode_client_sites
from map_config import (
    COORDINATE_REVIEW_CSV,
    GEOCODING_FAILURES_CSV,
    OUTPUT_DIR,
    OUTPUT_MAP,
    VERSION,
    enabled_clients,
    load_client_config,
)
from map_renderer import build_map, district_for
from qa import collect_coordinate_reviews, write_coordinate_review_csv

try:
    import folium  # noqa: F401
except ImportError as exc:
    missing = getattr(exc, "name", "a required package")
    print()
    print(f"ERROR: Missing Python package: {missing}")
    print("Run Setup_Resource_Map.bat once, then try again.")
    raise SystemExit(2) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the multi-client Resource Allocation Map."
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry addresses that previously failed geocoding.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the generated map in a browser.",
    )
    return parser.parse_args()


def write_failure_csv(failures: list[dict[str, str]], output_path: Path) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not failures:
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        return
    fields = ["Client", "Site Name", "Site Code", "Address", "Area", "Reason", "Attempted Queries"]
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(failures)


def main() -> int:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 82)
    print("RESOURCE ALLOCATION MAP")
    print("=" * 82)
    print(f"VERSION: {VERSION}")
    print("=" * 82)
    print()
    print(f"Python file: {Path(__file__).resolve()}")
    print()

    config = load_client_config()
    clients = enabled_clients(config)
    if not clients:
        print("ERROR: No enabled clients found in map_clients.json.")
        return 1

    all_failures: list[dict[str, str]] = []
    client_sites: dict[str, list] = {}
    total_new_requests = 0

    for client in clients:
        print("=" * 82)
        print(f"LOADING — {client['name']} ({client['id']})")
        print("=" * 82)
        try:
            sites = load_client_sites(client)
        except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
            print(f"ERROR loading {client['id']}: {exc}")
            return 1

        print(f"  Sites loaded: {len(sites)}")
        if client.get("group_by_family"):
            families = {(district_for(s), s.get("family", "")) for s in sites}
            print(f"  Property families: {len(families)}")
            for district, count in sorted(Counter(district_for(s) for s in sites).items()):
                print(f"    {district:<10} {count}")
        else:
            for area, count in sorted(Counter(s.get("area", "") for s in sites).items()):
                print(f"    {area:<12} {count}")
        print()

        print("=" * 82)
        print(f"GEOCODING — {client['name']}")
        print("=" * 82)
        try:
            located, failures, new_requests = geocode_client_sites(
                client, sites, retry_failed=args.retry_failed
            )
        except RuntimeError as exc:
            print(f"ERROR geocoding {client['id']}: {exc}")
            return 1

        client_sites[client["id"]] = located
        all_failures.extend(failures)
        total_new_requests += new_requests
        print()

    write_failure_csv(all_failures, GEOCODING_FAILURES_CSV)

    all_located = [site for sites in client_sites.values() for site in sites]
    reviews = collect_coordinate_reviews(all_located, config.get("qa", {}))
    write_coordinate_review_csv(reviews, COORDINATE_REVIEW_CSV)

    print("=" * 82)
    print("CREATING MAP")
    print("=" * 82)
    try:
        build_map(client_sites, clients)
    except RuntimeError as exc:
        print(f"ERROR rendering map: {exc}")
        return 1

    print()
    print("=" * 82)
    print("DONE")
    print("=" * 82)
    print()
    for client in clients:
        loaded = len(client_sites.get(client["id"], []))
        print(f"  {client['name']}: {loaded} plotted")
    print()
    print(f"Geocoder requests this run: {total_new_requests}")
    print()
    print(f"Generated map:\n  {OUTPUT_MAP}")
    print()
    if all_failures:
        print(f"Geocoding failures:\n  {GEOCODING_FAILURES_CSV}")
    else:
        print("Geocoding failures: none")
    print()
    if reviews:
        print(f"Coordinate review items: {len(reviews)}")
        print(f"  {COORDINATE_REVIEW_CSV}")
    else:
        print("Coordinate review: no items flagged")
    print()

    if not args.no_open:
        webbrowser.open(OUTPUT_MAP.resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
