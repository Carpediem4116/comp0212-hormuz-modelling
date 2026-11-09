"""Draw vector figures from the frozen monthly analysis outputs."""

import csv
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt


OUT = Path(__file__).resolve().parent
DATA = OUT.parents[1] / "data"
WIDTH = 15 / 2.54
COUNTRIES = {"GBR": ("United Kingdom", "#3564A0"), "USA": ("United States", "#AA442A"),
             "CHN": ("China", "#784C89"), "IND": ("India", "#007F68")}
STYLE = {"font.family": "Times New Roman", "font.size": 9, "axes.labelweight": "bold",
         "axes.labelsize": 9, "axes.titlesize": 9, "legend.frameon": False,
         "xtick.direction": "in", "ytick.direction": "in", "axes.linewidth": 0.75,
         "lines.linewidth": 1.5, "pdf.fonttype": 42}


def read(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def numbers(rows, key):
    return [float(row[key]) for row in rows]


def calendar_axis(axis, dates, interval):
    axis.set_xlim(dates[0], dates[-1])
    axis.xaxis.set_major_locator(mdates.MonthLocator(interval=interval))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    axis.set_xlabel("Observation month")


def main():
    with plt.rc_context(STYLE):
        panel = read(OUT / "monthly_panel.csv")
        dates = [date.fromisoformat(row["month"]) for row in panel]
        timeline, axes = plt.subplots(3, 1, figsize=(WIDTH, 6.0), layout="constrained")
        axes[0].plot(dates, numbers(panel, "hormuz_index"), color="#355F7A", marker="o", ms=2.5)
        axes[0].axhline(100, color="#747474", linewidth=0.75, linestyle=":")
        axes[0].set(ylabel="Shipment index", title="WTO observed outbound crude shipments")
        axes[1].plot(dates, numbers(panel, "brent_usd_bbl"), color="#292929", marker="o", ms=2.5)
        axes[1].set(ylabel="USD per barrel", title="Brent spot benchmark")
        for code, (name, color) in COUNTRIES.items():
            axes[2].plot(dates, numbers(panel, code), label=name, color=color)
        axes[2].set(ylabel="USD per tonne", title="National crude import unit values")
        timeline.legend(*axes[2].get_legend_handles_labels(), ncols=4, loc="outside lower center")
        for axis in axes:
            axis.axvline(date(2026, 5, 1), linewidth=0.75, color="#747474", linestyle="--")
            calendar_axis(axis, dates, 3)
        timeline.savefig(OUT / "timeline.pdf")

        forecasts = read(OUT / "holdout_predictions.csv")
        holdout, axes = plt.subplots(2, 2, figsize=(WIDTH, 3.9), layout="constrained")
        for axis, (code, (name, _)) in zip(axes.flat, COUNTRIES.items(), strict=True):
            relevant = [row for row in forecasts if row["country"] == code and row["mode"] == "one_step"]
            for model, label, color, style in [("persistence", "Persistence", "#666666", ":"),
                                                ("brent", "Brent only", "#0072B2", "--"),
                                                ("full", "Brent + flow", "#C4532B", "-.")]:
                rows = [row for row in relevant if row["model"] == model]
                dates = [date.fromisoformat(row["month"]) for row in rows]
                axis.plot(dates, numbers(rows, "predicted_usd_t"), label=label, color=color, linestyle=style)
            axis.plot(dates, numbers(rows, "actual_usd_t"), label="Observed", color="#222222", marker="o", ms=2.7)
            axis.set(ylabel="USD per tonne", title=name)
            calendar_axis(axis, dates, 1)
        holdout.legend(*axes[0, 0].get_legend_handles_labels(), ncols=4, loc="outside lower center")
        holdout.savefig(OUT / "holdout.pdf")

        draws = read(OUT / "scenario.csv")
        scenario, axis = plt.subplots(figsize=(WIDTH, 3.1), layout="constrained")
        axis.axhline(0, color="#747474", linewidth=0.75, linestyle=":")
        for code, (name, color) in COUNTRIES.items():
            rows = [row for row in draws if row["country"] == code]
            months = numbers(rows, "month")
            axis.plot(months, numbers(rows, "gap_p50_pct"), label=name, color=color)
            axis.fill_between(months, numbers(rows, "gap_p05_pct"), numbers(rows, "gap_p95_pct"),
                              color=color, alpha=0.14, linewidth=0)
        axis.set(xlabel="Months after model input changes", ylabel="Paired unit-value difference (%)", xticks=range(7))
        scenario.legend(*axis.get_legend_handles_labels(), ncols=4, loc="outside lower center")
        scenario.savefig(OUT / "scenario.pdf")

        routes = read(DATA / "hormuz_destination_shares.csv")
        destination, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.6), layout="constrained")
        regions = [row for row in routes if row["row_group"] == "region"]
        markets = [row for row in routes if row["source"] == "EIA_Vortexa" and row["destination"] in
                   ["China", "India", "United States"]]
        for axis, records, title, limit in zip(axes, [regions, markets],
                ["Regions  |  IEA, 2025", "Selected countries  |  EIA, 2025 H1"], [100, 45], strict=True):
            labels = ["Unshown / rounding" if row["status"] == "arithmetic_residual" else row["destination"]
                      for row in records]
            values = numbers(records, "share_pct")
            bars = axis.barh(labels, values, color="#356284", height=0.60)
            axis.bar_label(bars, labels=[f"{value:.1f}%" for value in values], padding=3)
            axis.invert_yaxis()
            axis.set(title=title, xlabel="Share of total flow (%)", xlim=(0, limit))
        destination.savefig(OUT / "destinations.pdf")
        for figure in (timeline, holdout, scenario, destination):
            plt.close(figure)


if __name__ == "__main__":
    main()
