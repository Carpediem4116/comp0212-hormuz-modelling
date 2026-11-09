"""Render the five-year market history and the separate EIA physical-flow series."""

import csv
from datetime import date, timedelta
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt


OUT = Path(__file__).resolve().parent
WIDTH = 15 / 2.54
COUNTRIES = {"GBR": ("United Kingdom", "#3564A0"), "USA": ("United States", "#AA442A"),
             "CHN": ("China", "#784C89"), "IND": ("India", "#007F68")}
STYLE = {"font.family": "Times New Roman", "font.size": 9, "axes.labelweight": "bold",
         "axes.labelsize": 9, "axes.titlesize": 9, "legend.frameon": False,
         "xtick.direction": "in", "ytick.direction": "in", "axes.linewidth": 0.75,
         "lines.linewidth": 1.5, "pdf.fonttype": 42}


def read(filename):
    with (OUT / filename).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def numeric(rows, column):
    return [float(row[column]) for row in rows]


def main():
    with plt.rc_context(STYLE):
        panel = read("monthly_panel.csv")
        months = [date.fromisoformat(row["month"]) for row in panel]
        fig, axes = plt.subplots(3, 1, figsize=(WIDTH, 6.0), layout="constrained")
        axes[0].plot(months, numeric(panel, "tanker_volume_index"), label="Estimated tanker cargo", color="#3564A0")
        axes[0].plot(months, numeric(panel, "tanker_count_index"), label="Observed tanker count",
                     color="#707070", linestyle="--", linewidth=1.0)
        axes[0].set(ylabel="2024 mean = 100", title="Hormuz tanker activity from IMF PortWatch")
        axes[0].legend(ncols=2, loc="lower left")
        axes[1].plot(months, numeric(panel, "brent_usd_bbl"), color="#292929")
        axes[1].set(ylabel="USD per barrel", title="Brent spot benchmark")
        for code, (label, color) in COUNTRIES.items():
            axes[2].plot(months, numeric(panel, code), label=label, color=color)
        axes[2].set(ylabel="USD per tonne", title="National crude import unit values")
        fig.legend(*axes[2].get_legend_handles_labels(), ncols=4, loc="outside lower center")
        for axis in axes:
            axis.axvline(date(2025, 1, 1), color="#555555", linewidth=0.75, linestyle="--")
            for event in (date(2023, 5, 1), date(2025, 6, 1), date(2026, 3, 1)):
                axis.axvline(event, color="#7F7F7F", linewidth=0.75, linestyle=":")
            axis.set(xlim=(months[0], months[-1]), xlabel="Observation month")
            axis.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
            axis.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        fig.savefig(OUT / "timeline.pdf")

        official = read("physical_flow_crosscheck.csv")
        starts = [date.fromisoformat(row["period_start"]) for row in official]
        ends = [date.fromisoformat(row["period_end"]) + timedelta(days=1) for row in official]
        flows = numeric(official, "crude_condensate_million_bbl_per_day")
        widths = [(end - start).days for start, end in zip(starts, ends, strict=True)]
        physical, ax = plt.subplots(figsize=(WIDTH, 2.6), layout="constrained")
        ax.bar(starts, flows, width=widths, align="edge", color="#356284", edgecolor="white", linewidth=0.75)
        ax.axvline(date(2025, 1, 1), color="#535353", linestyle="--", linewidth=1.0)
        ax.set(xlabel="Publication interval", ylabel="Million barrels per day", xlim=(starts[0], ends[-1]),
               title="EIA crude oil and condensate through Hormuz")
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        physical.savefig(OUT / "physical.pdf")
        plt.close(fig)
        plt.close(physical)


if __name__ == "__main__":
    main()
