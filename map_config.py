"""Project paths, constants, and client configuration loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VERSION = "8.0 - Multi-Client Resource Allocation Map"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "DATA"
CONFIG_FILE = ROOT / "map_clients.json"
CACHE_FILE = ROOT / "geocode_cache.json"
OUTPUT_DIR = ROOT / "OUTPUT"
OUTPUT_MAP = OUTPUT_DIR / "Resource_Allocation_Map.html"
COORDINATE_REVIEW_CSV = OUTPUT_DIR / "Coordinate_Review.csv"
GEOCODING_FAILURES_CSV = OUTPUT_DIR / "Geocoding_Failures.csv"

CALGARY_CENTER = (51.0447, -114.0719)
DETAIL_ZOOM_LEVEL = 13
FAMILY_CLICK_MAX_ZOOM = 15

GEOCODE_DELAY_SECONDS = 1.10
GEOCODER_USER_AGENT = "summit-resource-allocation-map/8.0"

CALGARY_BOUNDS = {
    "min_lat": 50.75,
    "max_lat": 51.35,
    "min_lon": -114.45,
    "max_lon": -113.75,
}

# Legacy cache namespace mapping for migration.
LEGACY_CACHE_NAMESPACES = {
    "CHC": "sites",
    "SILVERA": "silvera_sites",
}


def resolve_data_file(filename: str) -> Path:
    """Check DATA/ first, then project root (backward compatible)."""
    data_path = DATA_DIR / filename
    if data_path.exists():
        return data_path
    return ROOT / filename


def load_client_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Client configuration not found:\n{CONFIG_FILE}"
        )
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or "clients" not in config:
        raise ValueError("map_clients.json must contain a 'clients' array.")
    return config


def enabled_clients(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    config = config or load_client_config()
    return [c for c in config["clients"] if c.get("enabled", True)]


def client_by_id(client_id: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_client_config()
    for client in config["clients"]:
        if client["id"] == client_id:
            return client
    raise KeyError(f"Unknown client id: {client_id}")
