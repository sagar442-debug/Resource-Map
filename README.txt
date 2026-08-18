RESOURCE ALLOCATION MAP — VERSION 1
===================================

WHAT THIS VERSION DOES
----------------------
- Reads CHC_Master_Sites.xlsx.
- Uses the "CHC Master Sites" sheet.
- Enforces one map pin per Property Code, even if duplicate rows are accidentally
  added later.
- Geocodes the representative address for each unique property code.
- Creates OUTPUT\Resource_Allocation_Map.html.
- East CHC sites are emphasized because East is the current grounds/snow contract.
- South and West remain plotted as reference layers.
- You can turn district layers on/off from the map's layer control.
- Clicking a pin shows property code, project name, representative address,
  district, contract status, legacy code, ownership, and the geocoder match.
- Geocoding results are stored in geocode_cache.json so the same addresses are
  NOT looked up again on every run.
- Failed addresses are written to OUTPUT\Geocoding_Failures.csv for review.

FIRST RUN
---------
1. Keep CHC_Master_Sites.xlsx in this folder.
2. Run Setup_Resource_Map.bat ONCE.
3. Run Create_Resource_Map.bat.
4. The first run can take several minutes because the public geocoder is
   intentionally rate-limited. Do not close the terminal while it is running.
5. When complete, the HTML map opens in your default browser.

AFTER THE FIRST RUN
-------------------
- Normal reruns are fast because coordinates come from geocode_cache.json.
- Do NOT delete geocode_cache.json just to refresh the map. It is deliberately
  retained to avoid repeatedly sending the same geocoding requests.
- If an address was cached as failed and you have corrected the address in the
  workbook, the changed address creates a new cache key automatically.
- To deliberately retry currently failed addresses without changing them, run:
      py Create_Resource_Map.py --retry-failed

IMPORTANT: PUBLIC NOMINATIM RESTRICTIONS
----------------------------------------
This V1 deliberately uses OpenStreetMap Foundation's public Nominatim endpoint
only for the initial small, one-time CHC geocoding pass. The script:
- uses one thread only,
- waits at least 1.10 seconds between requests,
- identifies the application with a custom User-Agent,
- caches results locally,
- does not implement autocomplete.

The public service is not intended to become our permanent high-volume/regular
company geocoder. If this project grows into routine bulk geocoding, we should
switch the geocoder while keeping the rest of the mapping program unchanged.

Policy:
https://operations.osmfoundation.org/policies/nominatim/

MAP / LIBRARY REFERENCES
------------------------
Folium documentation:
https://python-visualization.github.io/folium/latest/

GeoPy documentation:
https://geopy.readthedocs.io/

NEXT PROJECT STEP
-----------------
Once the proposed-contract property list arrives, we will add it as another
source/layer with a separate marker style. After that we can calculate nearest
CHC sites, clusters, and suggested resource allocation.
