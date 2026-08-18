RESOURCE ALLOCATION MAP
=======================

WHAT THIS TOOL DOES
-------------------
This application creates an interactive map (Folium/Leaflet) showing all
contract sites across multiple clients in Calgary. Use it to review geographic
overlap, crew coverage, travel distances, and future resource allocation.

Current clients are configured in map_clients.json (CHC and Silvera by default).
New contracts can be added through configuration and Excel workbooks without
writing new Python code for each client.


HOW TO RUN THE MAP
------------------
1. Place client workbooks in DATA/ or the project root (both are supported).
2. Run Setup_Resource_Map.bat once on a new computer.
3. Double-click Create_Resource_Map.bat.
4. The map is saved to OUTPUT\Resource_Allocation_Map.html and opens in your browser.

Normal reruns are fast because coordinates are stored in geocode_cache.json.


HOW TO MANUALLY FIX A BAD LOCATION
----------------------------------
1. Open the client's Excel workbook (for example CHC_Master_Sites.xlsx).
2. Find the site row.
3. Enter verified Latitude and Longitude (Calgary-area decimal degrees).
4. Save the workbook.
5. Run Create_Resource_Map.bat again.

Manual workbook coordinates ALWAYS override the cache and geocoding.
You do NOT need to delete geocode_cache.json.


COORDINATE PRIORITY
-------------------
For every client/site:

  1. Manual Latitude/Longitude in the workbook
  2. Cached coordinates (geocode_cache.json)
  3. Automatic Nominatim geocoding

Popups show Coordinate Source: Manual, Cache, or Geocoder.


HOW TO ADD A NEW CLIENT (EXAMPLE: CCSD SCHOOLS)
-----------------------------------------------
1. Copy DATA\NEW_CLIENT_TEMPLATE.xlsx to DATA\CCSD_Sites.xlsx (or similar name).
2. Fill in site rows (Site Name, Address, Area, etc.).
   - Site Code is optional.
   - Latitude/Longitude are optional (leave blank to geocode automatically).
3. Open map_clients.json and add a new entry under "clients", for example:

   {
     "id": "CCSD",
     "name": "CCSD Schools",
     "file": "CCSD_Sites.xlsx",
     "sheet": "Sites",
     "enabled": true,
     "header_mode": "first_row",
     "marker_type": "circle",
     "marker_color": "#2563eb",
     "group_by_family": false,
     "dedupe_by": "site_code",
     "cache_key_fields": ["site_code", "address"],
     "columns": {
       "site_name": "Site Name",
       "site_code": "Site Code",
       "address": "Address",
       "geocode_address": "Geocode Address",
       "postal_code": "Postal Code",
       "area": "Area",
       "latitude": "Latitude",
       "longitude": "Longitude",
       "service_types": "Service Type"
     },
     "required_columns": [
       "Site Name", "Address"
     ],
     "required_row_fields": ["address"],
     "dedupe_by": "site_code",
     "layer_name": "CCSD Schools"
   }

4. Run Create_Resource_Map.bat.

Marker types available in configuration:
  code_label  - compact rectangle (CHC style)
  star        - purple/colored star (Silvera style)
  circle, square, diamond, triangle - future contracts

Column requirements:
  required_columns     - workbook header columns that must exist in the sheet
  required_row_fields  - logical fields that must be non-blank per row (row skipped if missing)
                         Examples: site_code (CHC), address (Silvera)
  All other mapped columns are optional (Area, Postal Code, Site Code, Geocode Address,
  Service Type, Latitude, Longitude). If Geocode Address is blank or not mapped,
  the program uses Address for geocoding.

Deduplication (dedupe_by):
  Configured per client (site_code, address, site_name, or another mapped field).
  Blank dedupe values are ignored — unrelated sites are never collapsed together.
  Only rows with the same non-blank dedupe value are treated as duplicates.

Optional settings:
  layer_group_field + layer_styles  - split one client into sub-layers (CHC uses District)
  group_by_family + family_regex    - property family grouping at low zoom (CHC)
  z_index_offset                    - raise markers above others (Silvera uses 10000)


QA REPORTS (OUTPUT FOLDER)
--------------------------
Coordinate_Review.csv
  Informational and review flags. Does NOT stop map generation.
  Issue types include:
    Manual Override
    Duplicate / Near-Duplicate Coordinates
    Possible Street Number Mismatch
    Family Outlier
    Approximate Geocode

Geocoding_Failures.csv
  Sites that could not be geocoded (all clients combined).
  Review addresses, correct the workbook, and rerun.
  To retry failed addresses without changing them:
      py Create_Resource_Map.py --retry-failed


GEOCODE CACHE
-------------
geocode_cache.json stores successful and failed geocoding results.
Do NOT delete it routinely. Deleting it forces hundreds of new geocoding
requests and slows every run.

The cache is organized by client id (CHC, SILVERA, etc.).
Existing CHC/Silvera cache data is preserved and migrated automatically.


CHC MAP BEHAVIOUR (PRESERVED)
-----------------------------
- Property families (FHT, RUN, PIN, etc.) show at city zoom.
- Individual codes (FHT1, RUN2, etc.) show at zoom 13+.
- Clicking a family zooms to that cluster.
- East = red, South = blue, West = green, Unknown = orange.
- District layers can be toggled independently.


SILVERA MAP BEHAVIOUR (PRESERVED)
---------------------------------
- Purple stars at every zoom level.
- Stars render above CHC labels when overlapping.
- Independent Silvera layer checkbox.


PROJECT FILES
-------------
Create_Resource_Map.py      Main entry point (run via BAT file)
map_clients.json            Client configuration
map_config.py               Paths and settings
data_loader.py              Generic Excel loading
geocoder.py                 Geocoding and cache
qa.py                       Coordinate quality review
map_renderer.py             Map and marker rendering
DATA\                       Recommended location for workbooks
DATA\NEW_CLIENT_TEMPLATE.xlsx Blank workbook for new clients
geocode_cache.json          Geocoding cache (do not delete casually)
OUTPUT\                     Generated map and reports


TROUBLESHOOTING
---------------
- "Missing Python package" -> run Setup_Resource_Map.bat
- "Workbook not found" -> check DATA/ and project root
- "Missing required columns" -> compare workbook headers to map_clients.json
- Silvera header issues -> program searches for the header row (does not use max_row)
