"""Build the two small reference tables from their published source figures."""

import argparse
import csv
from calendar import monthrange
from datetime import date
from decimal import Decimal
from pathlib import Path


EIA_CHOKEPOINTS = (
    "https://www.eia.gov/international/content/analysis/special_topics/"
    "World_Oil_Transit_Chokepoints/"
)
EIA_STEO = "https://www.eia.gov/outlooks/steo/report/energysecurity/article.php"

# EIA World Oil Transit Chokepoints Table 3 and STEO Energy Security Table 4.
# Million barrels per day of crude oil and condensate, at published precision.
EIA_ANNUAL = ("14.4", "14.7", "16.2", "15.8", "14.6")
EIA_QUARTERLY = ("14.8", "14.9", "15.0", "15.9", "10.9", "3.7")

# IEA Strait of Hormuz factsheet, 2025 crude destination map and world total.
# https://www.iea.org/about/strait-of-hormuz
IEA_TOTAL = Decimal("14.95")
IEA_REGIONS = {"Europe": Decimal("0.6"), "Americas": Decimal("0.5"), "Africa": Decimal("0.2")}
IEA_ASIA = {"China": Decimal("4.6"), "India": Decimal("2.1"), "Other Asia": Decimal("6.2")}

# EIA Figure 5 workbook, CrudeByDestination_F5 cells A3:A11 and G3:G11.
# World Oil Transit Chokepoints, excel/Chokepoints_FY2026_F5.xlsx.
EIA_DESTINATIONS = {
    "China": "5.399681337016575",
    "India": "2.048842635359116",
    "South Korea": "1.747255464088398",
    "Japan": "1.7047350828729282",
    "Other Asia and Oceania": "2.2573845082872928",
    "Europe": "0.5863580276243094",
    "United States": "0.426802138121547",
    "Saudi Arabia": "0.018222436464088398",
    "Other": "0.5570110718232044",
}


def physical_rows():
    for year, value in enumerate(EIA_ANNUAL, start=2020):
        yield (
            year, date(year, 1, 1), date(year, 12, 31), "annual", value,
            "EIA/Vortexa", "World Oil Transit Chokepoints Table 3", EIA_CHOKEPOINTS,
        )
    for offset, value in enumerate(EIA_QUARTERLY):
        year = 2025 + offset // 4
        quarter = offset % 4 + 1
        end_month = quarter * 3
        yield (
            f"{year}Q{quarter}", date(year, end_month - 2, 1),
            date(year, end_month, monthrange(year, end_month)[1]), "quarterly", value,
            "EIA/Vortexa", "STEO Energy Security Table 4", EIA_STEO,
        )


def destination_row(source, period, group, name, flow, total, status):
    share = f"{100 * flow / total:.5f}" if flow is not None else None
    return source, period, group, name, flow, total, share, status


def destination_rows():
    asia = sum(IEA_ASIA.values())
    remainder = IEA_TOTAL - asia - sum(IEA_REGIONS.values())
    regions = [
        ("Asia", asia, "sum_of_rounded_map_categories"),
        *((name, flow, "rounded_map_estimate") for name, flow in IEA_REGIONS.items()),
        ("Destinations not shown and rounding", remainder, "arithmetic_residual"),
    ]
    for name, flow, status in regions:
        yield destination_row("IEA_Kpler", 2025, "region", name, flow, IEA_TOTAL, status)
    for name, flow in IEA_ASIA.items():
        yield destination_row("IEA_Kpler", 2025, "map_detail", name, flow, IEA_TOTAL, "rounded_map_estimate")
    for name in ("United Kingdom", "United States"):
        yield destination_row("IEA_Kpler", 2025, "map_detail", name, None, IEA_TOTAL, "not_separately_published")

    flows = {name: Decimal(value) for name, value in EIA_DESTINATIONS.items()}
    total = sum(flows.values()).quantize(Decimal("0.00000000000001"))
    for name, flow in flows.items():
        yield destination_row("EIA_Vortexa", "2025H1", "reported_destination", name, flow, total, "published_estimate")
    yield destination_row("EIA_Vortexa", "2025H1", "country_detail", "United Kingdom", None, total, "not_separately_published")


def write_table(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    print(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_table(
        args.output_dir / "eia_hormuz_crude_condensate_periods.csv",
        ("period", "period_start", "period_end", "frequency",
         "crude_condensate_million_bbl_per_day", "source", "source_table", "source_url"),
        physical_rows(),
    )
    write_table(
        args.output_dir / "hormuz_destination_shares.csv",
        ("source", "period", "row_group", "destination", "flow_million_bbl_per_day",
         "global_flow_million_bbl_per_day", "share_pct", "status"),
        destination_rows(),
    )


if __name__ == "__main__":
    main()
