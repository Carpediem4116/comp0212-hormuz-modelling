"""Extract China Customs' monthly crude import value and net mass from Table 14."""

import argparse
import csv
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen


INDEX = "http://english.customs.gov.cn/statics/report/monthly{year}.html"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
FIELDS = ["month", "value_usd", "net_weight_kg", "source_url"]


def read_html(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def table_links(year, url):
    page = read_html(url)
    row = re.search(
        r"<tr>\s*<td>[^<]*Major Import Commodities in Quantity and Value.*?</tr>",
        page,
        flags=re.I | re.S,
    )
    if not row:
        raise ValueError(f"No Table 14 in {url}")
    links = re.findall(
        r'<a\s+href=["\']?([^>"\'\s]+)["\']?\s*>\s*([a-z]{3})\.',
        row.group(),
        flags=re.I,
    )
    if not links:
        raise ValueError(f"No monthly Table 14 links in {url}")
    return [(year, MONTHS.index(month) + 1, href) for href, month in links]


def plain_text(html):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def extract(entry):
    year, month, url = entry
    page = read_html(url)
    title = re.search(r"<title>(.*?)</title>", page, flags=re.S)
    if not title or not re.search(rf",\s*{month}\.\s*{year}\s*$", title.group(1)):
        raise ValueError(f"Unexpected month/year in {url}")
    if not re.search(r"Unit\s*:\s*US\s*\$\s*1,000", plain_text(page), flags=re.I):
        raise ValueError(f"Unexpected value unit in {url}")
    rows = (plain_text(row) for row in re.findall(r"<tr\b[^>]*>.*?</tr>", page, flags=re.I | re.S))
    matches = [row for row in rows if row.lower().startswith("crude petroleum oils ")]
    if len(matches) != 1:
        raise ValueError(f"Expected one crude petroleum oils row in {url}")
    numbers = re.match(r"Crude petroleum oils\s+10000\s*T\s+([\d,.]+)\s+([\d,.]+)", matches[0], flags=re.I)
    if not numbers:
        raise ValueError(f"Unexpected crude row in {url}: {matches[0]}")
    reported_quantity, reported_value = (
        float(number.replace(",", "")) for number in numbers.groups()
    )
    return {
        "month": f"{year:04d}-{month:02d}",
        "value_usd": round(reported_value * 1000),
        "net_weight_kg": round(reported_quantity * 10_000_000),
        "source_url": url,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2025-01")
    parser.add_argument("--end", default="2026-09")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("china_crude_import_monthly.csv"))
    args = parser.parse_args()
    years = range(int(args.start[:4]), int(args.end[:4]) + 1)
    entries = [
        (year, month, url)
        for year in years
        for _, month, url in table_links(year, INDEX.format(year="" if year == 2026 else year))
        if args.start <= f"{year:04d}-{month:02d}" <= args.end
    ]
    with ThreadPoolExecutor(max_workers=6) as executor:
        rows = sorted(executor.map(extract, entries), key=lambda row: row["month"])
    if len({row["month"] for row in rows}) != len(rows):
        raise ValueError("Duplicate month")
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(len(rows), rows[0]["month"], rows[-1]["month"], datetime.now(timezone.utc).isoformat())
