#!/usr/bin/env python3
"""Analyze CloudFront access logs stored in the local logs/ directory.

Usage:
    uv run python scripts/analyze_logs.py [--days N]

Run scripts/sync_logs.py first to pull logs from S3.

Country is inferred from the CloudFront edge location (x-edge-location field),
which encodes the nearest airport code. No external service or database needed.
"""
import argparse
import gzip
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / "logs"

# Subset of CloudFront edge location prefixes → country.
# Full list: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/LocationsOfEdgeServers.html
EDGE_TO_COUNTRY: dict[str, str] = {
    "HEL": "Finland",
    "TLL": "Estonia",
    "RIX": "Latvia",
    "VNO": "Lithuania",
    "ARN": "Sweden",
    "CPH": "Denmark",
    "OSL": "Norway",
    "LHR": "United Kingdom",
    "LGW": "United Kingdom",
    "STN": "United Kingdom",
    "MAN": "United Kingdom",
    "CDG": "France",
    "ORY": "France",
    "MRS": "France",
    "FRA": "Germany",
    "MUC": "Germany",
    "DUS": "Germany",
    "BER": "Germany",
    "HAM": "Germany",
    "AMS": "Netherlands",
    "BRU": "Belgium",
    "LUX": "Luxembourg",
    "ZRH": "Switzerland",
    "GVA": "Switzerland",
    "VIE": "Austria",
    "MAD": "Spain",
    "BCN": "Spain",
    "LIS": "Portugal",
    "FCO": "Italy",
    "MXP": "Italy",
    "WAW": "Poland",
    "KRK": "Poland",
    "PRG": "Czech Republic",
    "BUD": "Hungary",
    "OTP": "Romania",
    "SOF": "Bulgaria",
    "ATH": "Greece",
    "IST": "Turkey",
    "IAD": "United States",
    "IAH": "United States",
    "ORD": "United States",
    "JFK": "United States",
    "EWR": "United States",
    "LAX": "United States",
    "SFO": "United States",
    "SEA": "United States",
    "DFW": "United States",
    "ATL": "United States",
    "MIA": "United States",
    "BOS": "United States",
    "DEN": "United States",
    "PHX": "United States",
    "MSP": "United States",
    "YYZ": "Canada",
    "YVR": "Canada",
    "YUL": "Canada",
    "SYD": "Australia",
    "MEL": "Australia",
    "NRT": "Japan",
    "HND": "Japan",
    "KIX": "Japan",
    "ICN": "South Korea",
    "SIN": "Singapore",
    "HKG": "Hong Kong",
    "BOM": "India",
    "DEL": "India",
    "HYD": "India",
    "PEK": "China",
    "PVG": "China",
    "SHA": "China",
    "DXB": "United Arab Emirates",
    "GRU": "Brazil",
    "GIG": "Brazil",
    "EZE": "Argentina",
    "SCL": "Chile",
    "BOG": "Colombia",
    "MEX": "Mexico",
    "JNB": "South Africa",
    "CAI": "Egypt",
    "NBO": "Kenya",
}


def edge_to_country(edge_location: str) -> str:
    prefix = edge_location[:3].upper()
    return EDGE_TO_COUNTRY.get(prefix, f"Unknown ({prefix})")


def parse_log_file(path: Path) -> list[dict]:
    rows = []
    open_fn = gzip.open if path.suffix == ".gz" else open
    fields: list[str] = []
    try:
        with open_fn(path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line.startswith("#Fields:"):
                    fields = line[len("#Fields:"):].strip().split("\t")
                    continue
                if line.startswith("#") or not line:
                    continue
                if not fields:
                    continue
                parts = line.split("\t")
                if len(parts) != len(fields):
                    continue
                rows.append(dict(zip(fields, parts)))
    except Exception as exc:
        print(f"  Warning: could not read {path.name}: {exc}", file=sys.stderr)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze CloudFront access logs.")
    parser.add_argument("--days", type=int, default=30,
                        help="How many recent days to include (default: 30)")
    args = parser.parse_args()

    if not LOGS_DIR.exists():
        sys.exit(f"logs/ directory not found. Run scripts/sync_logs.py first.")

    log_files = sorted(LOGS_DIR.glob("*.gz")) + sorted(LOGS_DIR.glob("*.log"))
    if not log_files:
        sys.exit(f"No log files found in {LOGS_DIR}/")

    cutoff = date.today() - timedelta(days=args.days)

    requests_per_day: Counter = Counter()
    requests_per_hour: Counter = Counter()
    requests_per_path: Counter = Counter()
    requests_per_country: Counter = Counter()
    requests_per_status: Counter = Counter()
    total = 0

    for path in log_files:
        for row in parse_log_file(path):
            row_date_str = row.get("date", "")
            try:
                row_date = date.fromisoformat(row_date_str)
            except ValueError:
                continue
            if row_date < cutoff:
                continue

            # Skip CloudFront health checks and bot traffic on non-content paths
            status = row.get("sc-status", "-")
            uri = row.get("cs-uri-stem", "-")
            edge = row.get("x-edge-location", "")
            time_str = row.get("time", "00:00:00")

            try:
                hour = int(time_str.split(":")[0])
            except ValueError:
                hour = 0

            total += 1
            requests_per_day[row_date_str] += 1
            requests_per_hour[hour] += 1
            requests_per_path[uri] += 1
            requests_per_country[edge_to_country(edge)] += 1
            requests_per_status[status] += 1

    if total == 0:
        print(f"No requests found in the last {args.days} days.")
        return

    print(f"\n{'='*60}")
    print(f"  CloudFront traffic — last {args.days} days  ({total:,} requests)")
    print(f"{'='*60}\n")

    print(f"{'─'*40}")
    print("  Requests per day (most recent first)")
    print(f"{'─'*40}")
    for day_str, count in sorted(requests_per_day.items(), reverse=True)[:30]:
        bar = "█" * min(40, count // max(1, max(requests_per_day.values()) // 40))
        print(f"  {day_str}  {count:>6,}  {bar}")

    print(f"\n{'─'*40}")
    print("  Hourly distribution (UTC)")
    print(f"{'─'*40}")
    peak = max(requests_per_hour.values()) if requests_per_hour else 1
    for hour in range(24):
        count = requests_per_hour.get(hour, 0)
        bar = "█" * (count * 30 // peak)
        print(f"  {hour:02d}:00  {count:>6,}  {bar}")

    print(f"\n{'─'*40}")
    print("  Visitors by country (edge location)")
    print(f"{'─'*40}")
    for country, count in requests_per_country.most_common(20):
        print(f"  {country:<30}  {count:>6,}")

    print(f"\n{'─'*40}")
    print("  Top requested paths")
    print(f"{'─'*40}")
    for path_str, count in requests_per_path.most_common(20):
        print(f"  {count:>6,}  {path_str}")

    print(f"\n{'─'*40}")
    print("  HTTP status codes")
    print(f"{'─'*40}")
    for status, count in sorted(requests_per_status.items()):
        print(f"  {status:<6}  {count:>6,}")

    print()


if __name__ == "__main__":
    main()
