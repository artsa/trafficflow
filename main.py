import os
import json
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt
import requests

# Same 25-colour palette as the React frontend for visual consistency
COLORS = [
    '#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f',
    '#edc948', '#b07aa1', '#ff9da7', '#9c755f', '#bab0ac',
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#17becf', '#bcbd22', '#7f7f7f',
    '#393b79', '#843c39', '#3d6b35', '#7b4013', '#5a3572',
]

COLUMNS = [
    'tms_id', 'year', 'ordinal_date', 'hour', 'minute', 'second', 'hundredth',
    'length', 'lane', 'direction', 'vehicle_class', 'speed', 'faulty',
    'total_time', 'time_interval', 'queue_start'
]

def get_tms_data(tms_id, date_str, cache_dir="tms_cache"):
    """
    Checks the local cache directory for the requested TMS raw history CSV file.
    If it doesn't exist, downloads it from the Digitraffic API and caches it.
    """
    os.makedirs(cache_dir, exist_ok=True)

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        print(f"Error: Date '{date_str}' is not in ISO format (YYYY-MM-DD).")
        return None

    # Digitraffic naming convention format requires short year and annual day number (ordinal date)
    year_short = dt.year % 100
    day_number = dt.timetuple().tm_yday

    filename = f"lamraw_{tms_id}_{year_short}_{day_number}.csv"
    cache_path = os.path.join(cache_dir, filename)

    # 1. Check local Cache
    if os.path.exists(cache_path):
        print(f" -> Found cached data locally: {cache_path}")
        return cache_path

    # 2. Download from Digitraffic API if missing
    url = f"https://tie.digitraffic.fi/api/tms/v1/history/raw/{filename}"
    print(f" -> Downloading from API: {url}")

    # Digitraffic documentation highly recommends declaring identity headers
    headers = {
        "User-Agent": "TrafficAnalysisApp/1.0",
        "Digitraffic-User": "TrafficAnalysisApp/1.0"
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            with open(cache_path, "wb") as f:
                f.write(response.content)
            print(f"    Saved new file to cache: {cache_path}")
            return cache_path
        elif response.status_code == 404:
            print(f"    Error 404: No data available for Station {tms_id} on {date_str}.")
            return None
        else:
            print(f"    HTTP Error {response.status_code} occurred while downloading.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"    Network error occurred: {e}")
        return None

def load_station_names(cache_dir="tms_cache"):
    """Read station names written by app.py; returns {} if not yet fetched."""
    path = os.path.join(cache_dir, "_station_names.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def apply_smoothing(series, window):
    """Centred moving average over `window` minutes; window ≤ 1 returns series unchanged."""
    if window <= 1:
        return series
    return series.rolling(window=window, center=True, min_periods=1).mean().round().astype(int)


def plot_traffic_flow(tms_ids, dates, direction, smoothing=15, cache_dir="tms_cache"):
    """
    Plot per-minute traffic flow for one or more stations and up to two dates.

    - smoothing: centred moving-average window in minutes (1 = raw, default 15).
    - When two dates are supplied the first is drawn solid, the second dashed;
      each station keeps its colour across both dates.
    """
    if isinstance(tms_ids, (int, str)):
        tms_ids = [tms_ids]
    if isinstance(dates, str):
        dates = [dates]

    names = load_station_names(cache_dir)
    is_comparison = len(dates) > 1
    linestyles = ['-', '--']   # solid = first date, dashed = second

    fig, ax = plt.subplots(figsize=(16, 6))
    has_plotted_data = False

    for station_idx, tms_id in enumerate(tms_ids):
        color = COLORS[station_idx % len(COLORS)]
        station_label = names.get(str(tms_id), f"Station {tms_id}")

        for date_idx, date_str in enumerate(dates[:2]):   # max two dates
            file_path = get_tms_data(tms_id, date_str, cache_dir)
            if not file_path:
                continue

            try:
                df = pd.read_csv(file_path, sep=';', header=None, names=COLUMNS)
            except Exception as e:
                print(f"Error reading file {file_path}: {e}")
                continue

            df_filtered = df[(df['direction'] == direction) & (df['faulty'] == 0)]

            minute_of_day = df_filtered['hour'] * 60 + df_filtered['minute']
            per_minute = (
                minute_of_day.value_counts()
                .reindex(range(1440))
                .ffill()
                .fillna(0)
                .astype(int)
            )

            smoothed = apply_smoothing(per_minute, smoothing)

            label = (f"{station_label} ({tms_id}) — {date_str}"
                     if is_comparison else f"{station_label} ({tms_id})")
            ls = linestyles[date_idx] if is_comparison else '-'
            ax.plot(smoothed.index, smoothed.values,
                    color=color, linestyle=ls, linewidth=1.2, label=label)
            has_plotted_data = True

    if not has_plotted_data:
        print("No valid traffic data found to generate chart.")
        plt.close(fig)
        return

    smooth_label = (f" — {smoothing}-min avg" if smoothing > 1 else "")
    date_label = " vs ".join(dates[:2])
    ax.set_title(f'Traffic Flow — {date_label} — Direction {direction}{smooth_label}',
                 fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('Time of Day', fontsize=12, labelpad=10)
    ax.set_ylabel('Vehicles / Minute', fontsize=12, labelpad=10)
    ax.set_xticks(range(0, 1440, 60))
    ax.set_xticklabels([f'{h:02d}:00' for h in range(24)], rotation=45, ha='right')
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), borderaxespad=0)

    plt.tight_layout()
    output_filename = 'tms_traffic_flow_comparison.png'
    plt.savefig(output_filename, dpi=300)
    print(f"\nSuccessfully saved comparative visualization to '{output_filename}'")

def plot_speed_profile(tms_ids, dates, direction, smoothing=15, cache_dir="tms_cache"):
    """
    Plot per-minute average vehicle speed for one or more stations and up to two dates.

    Mirrors plot_traffic_flow in structure; uses mean speed per minute instead of vehicle count.
    """
    if isinstance(tms_ids, (int, str)):
        tms_ids = [tms_ids]
    if isinstance(dates, str):
        dates = [dates]

    names = load_station_names(cache_dir)
    is_comparison = len(dates) > 1
    linestyles = ['-', '--']

    fig, ax = plt.subplots(figsize=(16, 6))
    has_plotted_data = False

    for station_idx, tms_id in enumerate(tms_ids):
        color = COLORS[station_idx % len(COLORS)]
        station_label = names.get(str(tms_id), f"Station {tms_id}")

        for date_idx, date_str in enumerate(dates[:2]):
            file_path = get_tms_data(tms_id, date_str, cache_dir)
            if not file_path:
                continue

            try:
                df = pd.read_csv(file_path, sep=';', header=None, names=COLUMNS)
            except Exception as e:
                print(f"Error reading file {file_path}: {e}")
                continue

            df_filtered = df[(df['direction'] == direction) & (df['faulty'] == 0)]

            minute_of_day = df_filtered['hour'] * 60 + df_filtered['minute']
            speed_per_minute = (
                df_filtered.groupby(minute_of_day)['speed']
                .mean()
                .reindex(range(1440))
                .ffill()
                .fillna(0)
                .round()
                .astype(int)
            )

            smoothed = apply_smoothing(speed_per_minute, smoothing)

            label = (f"{station_label} ({tms_id}) — {date_str}"
                     if is_comparison else f"{station_label} ({tms_id})")
            ls = linestyles[date_idx] if is_comparison else '-'
            ax.plot(smoothed.index, smoothed.values,
                    color=color, linestyle=ls, linewidth=1.2, label=label)
            has_plotted_data = True

    if not has_plotted_data:
        print("No valid traffic data found to generate speed chart.")
        plt.close(fig)
        return

    smooth_label = (f" — {smoothing}-min avg" if smoothing > 1 else "")
    date_label = " vs ".join(dates[:2])
    ax.set_title(f'Vehicle Speeds — {date_label} — Direction {direction}{smooth_label}',
                 fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('Time of Day', fontsize=12, labelpad=10)
    ax.set_ylabel('Average Speed (km/h)', fontsize=12, labelpad=10)
    ax.set_xticks(range(0, 1440, 60))
    ax.set_xticklabels([f'{h:02d}:00' for h in range(24)], rotation=45, ha='right')
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), borderaxespad=0)

    plt.tight_layout()
    output_filename = 'tms_speed_profile.png'
    plt.savefig(output_filename, dpi=300)
    print(f"\nSuccessfully saved speed profile to '{output_filename}'")


if __name__ == "__main__":
    # --- CONFIGURATION INPUTS ---
    stations = [144,20017,116,126,145,146,147,148,149,109,7,8,99,110,998,142,424,470,461,628,442,623,922]

    # Single date — or pass a list of two dates to compare (solid vs dashed):
    iso_date = "2026-06-09"
    # iso_date = ["2025-06-13", "2026-06-12"]

    direction_id  = 1   # 1 = due north
    smooth_window = 15  # minutes; 1 = raw

    plot_traffic_flow(tms_ids=stations, dates=iso_date,
                      direction=direction_id, smoothing=smooth_window)
    plot_speed_profile(tms_ids=stations, dates=iso_date,
                       direction=direction_id, smoothing=smooth_window)