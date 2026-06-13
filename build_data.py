#!/usr/bin/env python3
"""Pre-compute per-date/direction JSON files for static hosting.

Usage:
    uv run python build_data.py

Output:
    dist/dates.json
    dist/data/{YYYY-MM-DD}/1.json
    dist/data/{YYYY-MM-DD}/2.json
    dist/index.html  (copied from static/)
"""
import json
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

CACHE_DIR = Path("tms_cache")
DIST_DIR = Path("dist")
STATIC_DIR = Path("static")

TRIP_ORDER = [144, 20017, 116, 126, 145, 146, 147, 148, 149, 109, 7, 8, 99, 110, 998,
              142, 424, 470, 461, 628, 442, 623, 922]

COLUMNS = [
    "tms_id", "year", "ordinal_date", "hour", "minute", "second", "hundredth",
    "length", "lane", "direction", "vehicle_class", "speed", "faulty",
    "total_time", "time_interval", "queue_start",
]


def ordinal_to_iso(year_short: str, day_number: str) -> str:
    year = 2000 + int(year_short)
    d = datetime(year, 1, 1) + timedelta(days=int(day_number) - 1)
    return d.strftime("%Y-%m-%d")


def load_station_names() -> dict[str, str]:
    names_file = CACHE_DIR / "_station_names.json"
    if names_file.exists():
        return json.loads(names_file.read_text(encoding="utf-8"))
    try:
        resp = requests.get(
            "https://tie.digitraffic.fi/api/tms/v1/stations",
            headers={"User-Agent": "TrafficAnalysisApp/1.0",
                     "Digitraffic-User": "TrafficAnalysisApp/1.0"},
            timeout=15,
        )
        if resp.status_code == 200:
            names = {
                str(f["properties"]["tmsNumber"]): f["properties"]["name"]
                for f in resp.json().get("features", [])
                if f.get("properties", {}).get("tmsNumber") is not None
            }
            names_file.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
            return names
    except Exception as exc:
        print(f"Warning: could not fetch station names: {exc}")
    return {}


def build_direction(date_str: str, direction: int, names: dict,
                    year_short: int, day_number: int) -> dict:
    pattern = re.compile(rf"^lamraw_(\d+)_{year_short}_{day_number}\.csv$")
    by_id: dict[str, dict] = {}

    for fname in os.listdir(CACHE_DIR):
        m = pattern.match(fname)
        if not m:
            continue
        tms_id = m.group(1)
        try:
            df = pd.read_csv(CACHE_DIR / fname, sep=";", header=None, names=COLUMNS)
            df_dir = df[(df["direction"] == direction) & (df["faulty"] == 0)]
            minute_of_day = df_dir["hour"] * 60 + df_dir["minute"]
            per_minute = (
                minute_of_day.value_counts()
                .reindex(range(1440)).ffill().fillna(0).astype(int)
            )
            speed_per_minute = (
                df_dir.groupby(minute_of_day)["speed"]
                .mean().reindex(range(1440)).ffill().fillna(0).round().astype(int)
            )
            by_id[tms_id] = {
                "name": names.get(tms_id, f"Station {tms_id}"),
                "minutely": per_minute.tolist(),
                "speeds": speed_per_minute.tolist(),
            }
        except Exception as exc:
            print(f"  Warning: error reading {fname}: {exc}")

    ordered_ids = [str(i) for i in TRIP_ORDER if str(i) in by_id]
    extras = [k for k in by_id if k not in set(ordered_ids)]
    return {
        "date": date_str,
        "direction": direction,
        "stations": [{"id": tid, **by_id[tid]} for tid in ordered_ids + extras],
    }


def discover_dates() -> list[str]:
    pattern = re.compile(r"^lamraw_\d+_(\d+)_(\d+)\.csv$")
    dates: set[str] = set()
    for fname in os.listdir(CACHE_DIR):
        m = pattern.match(fname)
        if m:
            dates.add(ordinal_to_iso(m.group(1), m.group(2)))
    return sorted(dates)


def main() -> None:
    if not CACHE_DIR.exists():
        raise SystemExit(f"Cache directory '{CACHE_DIR}' not found. Run main.py first.")

    names = load_station_names()
    dates = discover_dates()
    if not dates:
        raise SystemExit("No CSV files found in tms_cache/.")
    print(f"Found {len(dates)} date(s) to process")

    DIST_DIR.mkdir(exist_ok=True)
    (DIST_DIR / "data").mkdir(exist_ok=True)

    for date_str in dates:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        year_short = dt.year % 100
        day_number = dt.timetuple().tm_yday
        date_dir = DIST_DIR / "data" / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        for direction in (1, 2):
            payload = build_direction(date_str, direction, names, year_short, day_number)
            (date_dir / f"{direction}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
        print(f"  {date_str}")

    (DIST_DIR / "dates.json").write_text(json.dumps(dates), encoding="utf-8")

    for src in STATIC_DIR.iterdir():
        shutil.copy2(src, DIST_DIR / src.name)

    print(f"\nBuilt {len(dates)} date(s) → {DIST_DIR}/")


if __name__ == "__main__":
    main()
