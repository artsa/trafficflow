# Liikennevirta — Finnish Highway Traffic Visualiser

Liikennevirta ("traffic flow") fetches per-vehicle passage records from the Finnish Transport Infrastructure Agency's [Digitraffic TMS API](https://tie.digitraffic.fi/swagger/#/TMS%20V1/tmsRawHistory), aggregates them into per-minute time series, and presents an interactive web dashboard — and exportable PNG charts — showing both vehicle counts and average speeds across a sequence of 23 highway measurement stations that together trace a single north-south road trip.

---

## Prerequisites

| Tool                             | Version    | Notes                                          |
| -------------------------------- | ---------- | ---------------------------------------------- |
| Python                           | ≥ 3.14     | Matches `requires-python` in `pyproject.toml`  |
| [uv](https://docs.astral.sh/uv/) | any recent | Dependency manager; replaces pip/venv          |

Install `uv` if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Setup

```bash
git clone <repo-url>
cd liikennevirta
uv sync          # creates .venv and installs all dependencies
```

No `.env` file or secrets are required — the Digitraffic API is public.

## Running the web app

```bash
uv run python app.py
```

Open [http://localhost:8080](http://localhost:8080). The first load fetches station names from Digitraffic and caches them; subsequent starts are instant.

> **macOS note:** port 5000 is occupied by AirPlay Receiver — the app uses 8080 to avoid the conflict.

## Generating static PNG charts

`main.py` produces two PNG files without a browser:

```bash
uv run python main.py
```

Edit the three variables at the bottom of the file to change what is rendered:

```python
iso_date      = "2025-06-13"          # single date, or a list of two for comparison
direction_id  = 1                      # 1 = due north, 2 = due south
smooth_window = 15                     # minutes; 1 = raw per-minute data
```

Outputs:

- `tms_traffic_flow_comparison.png` — vehicles per minute over the day
- `tms_speed_profile.png` — average vehicle speed (km/h) over the day

## Downloading traffic data

Data files are CSV records of individual vehicle passages and are downloaded automatically on first request (web app or `main.py`). Cached files live in `tms_cache/` and are never re-downloaded.

To pre-fetch a specific date for all stations:

```python
from main import get_tms_data, TRIP_ORDER
for tms_id in TRIP_ORDER:
    get_tms_data(tms_id, "2025-06-13")
```

The `tms_cache/` directory is not committed to git (add it to `.gitignore`). Station names are cached in `tms_cache/_station_names.json`.

## Project structure

```text
liikennevirta/
├── app.py                    # Flask server — serves the web UI and /api/* endpoints
├── main.py                   # Standalone chart generator (matplotlib)
├── static/
│   └── index.html            # Single-file React app (CDN React + Chart.js, no build step)
├── tms_cache/                # Downloaded CSV files + cached station names (gitignored)
├── tms_raw_history_schema.md # Column definitions for the Digitraffic CSV format
└── pyproject.toml
```

## API endpoints

| Endpoint                                    | Description                                                                   |
| ------------------------------------------- | ----------------------------------------------------------------------------- |
| `GET /`                                     | Serves `static/index.html`                                                    |
| `GET /api/dates`                            | Returns `["2025-06-13", ...]` — dates available in the cache                  |
| `GET /api/data?date=YYYY-MM-DD&direction=1` | Returns per-minute flow and speed arrays for all cached stations on that date |

The `/api/data` response shape:

```jsonc
{
  "date": "2025-06-13",
  "direction": 1,
  "stations": [
    {
      "id": "144",
      "name": "Kehä III Lentoasemantie",
      "minutely": [0, 0, 1, ...],   // 1440 ints — vehicles per minute, forward-filled
      "speeds":   [0, 0, 76, ...]   // 1440 ints — avg km/h per minute, forward-filled
    }
    // ...23 stations in trip order
  ]
}
```

## The measurement stations

The 23 stations are fixed in `TRIP_ORDER` (both `app.py` and `main.py`) in the sequence they are physically encountered on the road trip:

```python
TRIP_ORDER = [144, 20017, 116, 126, 145, 146, 147, 148, 149, 109,
              7, 8, 99, 110, 998, 142, 424, 470, 461, 628, 442, 623, 922]
```

These are `tmsNumber` values from the Digitraffic stations API — **not** the station `id` field. The distinction matters for both CSV filenames and the station-names lookup; see `tms_raw_history_schema.md` for details.

## Web UI features

- **Traffic flow chart** — vehicles per minute across the full day
- **Speed chart** — average speed (km/h) across the full day
- **Direction selector** — 1 (due north) or 2 (due south)
- **Date selector** — only dates present in the local cache are listed
- **Comparison mode** — pick a second date; same colour per station, solid = date 1, dashed = date 2
- **Smoothing** — Raw / 5 min / 10 min / 15 min / 30 min / 1 h centred moving average; applied to both charts simultaneously
- **Station toggles** — show/hide individual stations; toggling one station hides it on both charts
- **Hover thickening** — moving the cursor over a line highlights it (and its comparison pair) on that chart

## Frontend architecture

`static/index.html` is a self-contained file: React 18, Chart.js 4.4, and Babel standalone are loaded from CDN — there is no build step, no `node_modules`, and no bundler. JSX is compiled in the browser at load time. This keeps the frontend zero-dependency from a toolchain perspective, at the cost of a slightly slower first parse (~1 s on a cold cache).

The component lifecycle follows a three-effect pattern:

1. **`[payload]` effect** — rebuilds both Chart.js instances from scratch when the fetched data changes.
2. **`[smoothing, payload]` effect** — updates dataset arrays in-place without rebuilding; avoids a full chart teardown on smoothing changes.
3. **`[hidden]` effect** — calls `chart.setDatasetVisibility()` without touching data.

All three effects run before the first browser paint, so there is no visible flicker between the raw-data state and the smoothed state.
