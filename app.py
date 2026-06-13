# Run with: uv run python app.py  (requires `uv sync` after adding flask to pyproject.toml)
import os
import json
import re
from datetime import datetime, timedelta

import pandas as pd
import requests
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")

CACHE_DIR = "tms_cache"

# Route order from main.py — stations in the sequence they are passed on the trip
TRIP_ORDER = [144,20017,116,126,145,146,147,148,149,109,7,8,99,110,998,142,424,470,461,628,442,623,922]

COLUMNS = [
    "tms_id", "year", "ordinal_date", "hour", "minute", "second", "hundredth",
    "length", "lane", "direction", "vehicle_class", "speed", "faulty",
    "total_time", "time_interval", "queue_start",
]


def ordinal_to_iso(year_short: str, day_number: str) -> str:
    year = 2000 + int(year_short)
    d = datetime(year, 1, 1) + timedelta(days=int(day_number) - 1)
    return d.strftime("%Y-%m-%d")


def get_available_dates() -> list[str]:
    pattern = re.compile(r"^lamraw_\d+_(\d+)_(\d+)\.csv$")
    dates: set[str] = set()
    for fname in os.listdir(CACHE_DIR):
        m = pattern.match(fname)
        if m:
            dates.add(ordinal_to_iso(m.group(1), m.group(2)))
    return sorted(dates)


def load_station_names() -> dict[str, str]:
    names_file = os.path.join(CACHE_DIR, "_station_names.json")
    if os.path.exists(names_file):
        with open(names_file, encoding="utf-8") as f:
            return json.load(f)

    try:
        resp = requests.get(
            "https://tie.digitraffic.fi/api/tms/v1/stations",
            headers={
                "User-Agent": "TrafficAnalysisApp/1.0",
                "Digitraffic-User": "TrafficAnalysisApp/1.0",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            names = {
                str(f["properties"]["tmsNumber"]): f["properties"]["name"]
                for f in resp.json().get("features", [])
                if f.get("properties", {}).get("tmsNumber") is not None
            }
            with open(names_file, "w", encoding="utf-8") as f:
                json.dump(names, f, ensure_ascii=False)
            return names
    except Exception as exc:
        print(f"Could not fetch station names: {exc}")

    return {}


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/dates")
def api_dates():
    return jsonify(get_available_dates())


@app.route("/api/data")
def api_data():
    date_str = request.args.get("date", "")
    direction_str = request.args.get("direction", "1")

    if not date_str:
        return jsonify({"error": "date parameter required"}), 400

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        direction = int(direction_str)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    year_short = dt.year % 100
    day_number = dt.timetuple().tm_yday

    names = load_station_names()
    by_id: dict[str, dict] = {}
    pattern = re.compile(rf"^lamraw_(\d+)_{year_short}_{day_number}\.csv$")

    for fname in os.listdir(CACHE_DIR):
        m = pattern.match(fname)
        if not m:
            continue
        tms_id = m.group(1)
        fpath = os.path.join(CACHE_DIR, fname)
        try:
            df = pd.read_csv(fpath, sep=";", header=None, names=COLUMNS)
            df_dir = df[(df["direction"] == direction) & (df["faulty"] == 0)]
            # Per-minute counts (1440 bins). Forward-fill so minutes with no
            # passage carry the flow rate from the last minute that had traffic.
            minute_of_day = df_dir["hour"] * 60 + df_dir["minute"]
            per_minute = (
                minute_of_day.value_counts()
                .reindex(range(1440))
                .ffill()
                .fillna(0)
                .astype(int)
            )
            speed_per_minute = (
                df_dir.groupby(minute_of_day)["speed"]
                .mean()
                .reindex(range(1440))
                .ffill()
                .fillna(0)
                .round()
                .astype(int)
            )
            by_id[tms_id] = {
                "name": names.get(tms_id, f"Station {tms_id}"),
                "minutely": per_minute.tolist(),
                "speeds": speed_per_minute.tolist(),
            }
        except Exception as exc:
            print(f"Error reading {fname}: {exc}")

    # Return stations in trip order; any IDs not in TRIP_ORDER come last
    ordered_ids = [str(i) for i in TRIP_ORDER if str(i) in by_id]
    extras = [k for k in by_id if k not in set(ordered_ids)]
    stations = [
        {"id": tid, **by_id[tid]}
        for tid in ordered_ids + extras
    ]

    return jsonify({"date": date_str, "direction": direction, "stations": stations})


if __name__ == "__main__":
    app.run(debug=True, port=8080, use_reloader=False)
