"""Fetch IMF PortWatch daily Strait of Hormuz tanker activity."""

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


ENDPOINT = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
    "Daily_Chokepoints_Data/FeatureServer/0/query"
)
CHOKEPOINT = "chokepoint6"
PERIODS = (
    ("2020-01-01", "2021-12-31"),
    ("2022-01-01", "2023-12-31"),
    ("2024-01-01", "2025-12-31"),
    ("2026-01-01", "2026-06-30"),
)
FIELDS = ("date", "n_tanker", "capacity_tanker")


def fetch_period(period):
    start, end = period
    params = {
        "f": "json",
        "where": f"portid='{CHOKEPOINT}' AND date >= DATE '{start}' AND date <= DATE '{end}'",
        "outFields": ",".join((*FIELDS, "portid", "portname")),
        "returnGeometry": "false",
        "orderByFields": "date ASC",
    }
    with urlopen(f"{ENDPOINT}?{urlencode(params)}", timeout=60) as response:
        payload = json.load(response)
    if "error" in payload or payload.get("exceededTransferLimit"):
        raise ValueError(f"PortWatch request failed or was truncated for {start} to {end}")

    rows = []
    for feature in payload["features"]:
        row = feature["attributes"]
        if row["portid"] != CHOKEPOINT or row["portname"] != "Strait of Hormuz":
            raise ValueError(f"Unexpected PortWatch feature: {row['portid']}, {row['portname']}")
        if any(type(row[key]) is not int or row[key] < 0 for key in FIELDS[1:]):
            raise ValueError(f"Invalid tanker activity value on {row['date']}")
        rows.append(tuple(row[key] for key in FIELDS))

    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    expected = [
        (start_date + timedelta(days=offset)).isoformat()
        for offset in range((end_date - start_date).days + 1)
    ]
    if [row[0] for row in rows] != expected:
        raise ValueError(f"Missing, duplicate or unsorted PortWatch dates for {start} to {end}")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=Path(__file__).with_name("portwatch_hormuz_daily.csv"),
    )
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=len(PERIODS)) as executor:
        periods = list(executor.map(fetch_period, PERIODS))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(FIELDS)
        for rows in periods:
            writer.writerows(rows)
    digest = sha256(args.output.read_bytes()).hexdigest()
    print(f"{args.output.name}: {sum(map(len, periods))} rows, SHA-256 {digest}")


if __name__ == "__main__":
    main()
