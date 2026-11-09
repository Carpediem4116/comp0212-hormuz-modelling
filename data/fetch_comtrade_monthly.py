"""Download UN Comtrade monthly national crude import value and weight.

The public preview API permits one monthly period per request. Keep the
reported value and weight so the unit-value calculation can be reproduced.
"""
import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ENDPOINT = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
COUNTRIES = {826: "GBR", 842: "USA", 156: "CHN", 699: "IND"}
FIELDS = [
    "month", "country", "reporter_code", "commodity_code", "partner_code",
    "primary_value_usd", "cif_value_usd", "net_weight_kg",
    "is_net_weight_estimated", "supplementary_quantity", "supplementary_unit_code",
    "is_supplementary_quantity_estimated", "weight_kg", "weight_source",
    "unit_value_usd_per_tonne", "source_url", "retrieved_at_utc",
]


def months(start, end):
    year, month = map(int, start.split("-"))
    while (period := f"{year:04d}-{month:02d}") <= end:
        yield period
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def download(period):
    params = {
        "period": period.replace("-", ""),
        "reporterCode": ",".join(map(str, COUNTRIES)),
        "flowCode": "M", "partnerCode": 0, "partner2Code": 0,
        "cmdCode": "270900", "customsCode": "C00", "motCode": 0,
        "maxrecords": 500,
    }
    url = ENDPOINT + "?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "COMP0212 coursework reproducibility"})
    for attempt in range(6):
        try:
            with urlopen(request, timeout=30) as response:
                return url, json.load(response)["data"]
        except HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == 5:
                raise
            time.sleep(5 + attempt * 3)
        except (TimeoutError, OSError):
            if attempt == 5:
                raise
            time.sleep(5 + attempt * 3)


def collect(start, end):
    rows = []
    for period in months(start, end):
        url, records = download(period)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        observed = set()
        for record in records:
            code = int(record["reporterCode"])
            if code in observed:
                raise ValueError(f"Duplicate aggregate import for {code} in {period}")
            if str(record["cmdCode"]) != "270900" or int(record["partnerCode"]) != 0:
                raise ValueError(f"Unexpected commodity or partner for {code} in {period}")
            observed.add(code)
            value = record["primaryValue"]
            net_weight = record["netWgt"]
            alternate = record["altQty"]
            alternate_unit = record["altQtyUnitCode"]
            if net_weight is not None and net_weight > 0:
                weight, weight_source = net_weight, "netWgt"
            elif alternate_unit == 8 and alternate is not None and alternate > 0:
                # UN Comtrade supplementary unit code 8 is kilograms.
                weight, weight_source = alternate, "altQty_kg"
            else:
                weight, weight_source = None, "unavailable"
                print(f"No usable mass for {code} in {period}", flush=True)
            unit_value = value * 1000 / weight if value and value > 0 and weight else None
            rows.append({
                "month": period, "country": COUNTRIES[code],
                "reporter_code": code, "commodity_code": record["cmdCode"],
                "partner_code": record["partnerCode"],
                "primary_value_usd": value, "cif_value_usd": record["cifvalue"],
                "net_weight_kg": net_weight, "is_net_weight_estimated": record["isNetWgtEstimated"],
                "supplementary_quantity": alternate, "supplementary_unit_code": alternate_unit,
                "is_supplementary_quantity_estimated": record["isAltQtyEstimated"],
                "weight_kg": weight, "weight_source": weight_source,
                "unit_value_usd_per_tonne": unit_value,
                "source_url": url, "retrieved_at_utc": now,
            })
        print(period, ",".join(COUNTRIES[code] for code in sorted(observed)), flush=True)
        time.sleep(3.25)
    return sorted(rows, key=lambda row: (row["month"], row["country"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2025-01")
    parser.add_argument("--end", default="2026-09")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("un_comtrade_crude_import_monthly.csv"))
    args = parser.parse_args()
    rows = collect(args.start, args.end)
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
