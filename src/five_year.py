"""Five-year monthly price study using independently measured tanker activity."""

import json

import numpy as np
import pandas as pd

from cross_country import COUNTRIES, DATA, ROOT, evaluate, fit_models, verify


OUT = ROOT / "results" / "five_year"
START = "2021-07-01"
END = "2026-06-01"
TRAIN_END = "2024-12-01"
REGIMES = [
    ("COVID emergency", START, "2023-04-01"),
    ("May 2023 to Dec 2024", "2023-05-01", TRAIN_END),
    ("2025", "2025-01-01", "2025-12-01"),
    ("Jan to Feb 2026", "2026-01-01", "2026-02-01"),
    ("Mar to Jun 2026", "2026-03-01", END),
]


def import_prices():
    trade = pd.concat([pd.read_csv(DATA / name) for name in (
        "un_comtrade_crude_import_extended.csv", "un_comtrade_crude_import_monthly.csv",
    )], ignore_index=True)
    trade = trade[["month", "country", "primary_value_usd", "weight_kg", "source_url"]].rename(
        columns={"primary_value_usd": "value_usd", "weight_kg": "mass_kg"})
    trade["source"] = "UN Comtrade HS 270900"
    customs = pd.concat([pd.read_csv(DATA / name) for name in (
        "china_crude_import_extended.csv", "china_crude_import_monthly.csv",
    )], ignore_index=True)
    customs = customs.rename(columns={"net_weight_kg": "mass_kg"})
    customs["country"] = "CHN"
    customs["source"] = "China GACC Table 14"
    values = pd.concat([customs[trade.columns], trade], ignore_index=True)
    values["month"] = pd.to_datetime(values.month).dt.to_period("M").dt.to_timestamp()
    values = values.loc[values.month.between(START, END) & values.country.isin(COUNTRIES)].copy()
    if values.duplicated(["month", "country", "source"]).any():
        raise ValueError("Multiple import totals from the same provider for one country and month")
    amounts = values[["value_usd", "mass_kg"]].to_numpy(dtype=float)
    if not np.isfinite(amounts).all() or (amounts <= 0).any():
        raise ValueError("Import values and masses must be finite and positive")
    values["usd_per_tonne"] = 1000 * values.value_usd / values.mass_kg
    china_check = values.loc[values.country.eq("CHN")].pivot(
        index="month", columns="source", values="usd_per_tonne").dropna()
    china_check["comtrade_vs_gacc_pct"] = 100 * (
        china_check["UN Comtrade HS 270900"] / china_check["China GACC Table 14"] - 1)
    values = values.drop_duplicates(["month", "country"], keep="first").sort_values(["month", "country"])
    monthly = values.pivot(index="month", columns="country", values="usd_per_tonne").reindex(columns=COUNTRIES)
    expected = pd.date_range(START, END, freq="MS", name="month")
    if not monthly.index.equals(expected) or monthly.isna().any().any():
        missing = monthly.reindex(expected).isna().stack()
        raise ValueError(f"Five-year price panel incomplete: {missing[missing].index.tolist()}")
    return values, monthly, china_check


def activity_and_brent():
    daily = pd.read_csv(DATA / "portwatch_hormuz_daily.csv", parse_dates=["date"]).set_index("date").sort_index()
    daily = daily[["n_tanker", "capacity_tanker"]].loc["2020-01-01":"2026-06-30"]
    days = pd.date_range("2020-01-01", "2026-06-30", freq="D", name="date")
    if not daily.index.equals(days) or not np.isfinite(daily.to_numpy()).all() or (daily < 0).any().any():
        raise ValueError("Invalid daily PortWatch data or missing days")
    normal = daily.loc["2024"].mean()
    index = (100 * daily / normal).rename(columns={"n_tanker": "tanker_count_index",
                                                  "capacity_tanker": "tanker_volume_index"})
    monthly = daily.join(index).resample("MS").mean().rename_axis("month")
    prices = pd.read_csv(DATA / "eia_brent_daily.csv", parse_dates=["date"]).set_index("date").sort_index()
    if prices.index.has_duplicates or (prices.brent_usd_bbl <= 0).any():
        raise ValueError("Invalid Brent observations")
    brent = prices.brent_usd_bbl.resample("MS").agg(["mean", "count"])
    brent = brent["mean"].where(brent["count"] >= 15).rename("brent_usd_bbl")
    monthly = monthly.join(brent)
    if monthly.brent_usd_bbl.isna().any():
        raise ValueError("Missing Brent observations")
    return monthly, index


def make_panel(prices, market, measure):
    panel = prices.join(market)
    panel["shortfall"] = (100 - market[measure].shift(1).reindex(panel.index)) / 100
    panel["log_brent"] = np.log(panel.brent_usd_bbl)
    for country in COUNTRIES:
        panel[f"log_{country}"] = np.log(panel[country])
        panel[f"lag_{country}"] = panel[f"log_{country}"].shift()
    if panel.dropna().shape[0] != len(panel) - 1:
        raise ValueError("Expected only the first price observation to lack a lag")
    return panel


def flow_crosscheck(daily_index):
    physical = pd.read_csv(DATA / "eia_hormuz_crude_condensate_periods.csv")
    for measure in daily_index:
        physical[measure] = [
            daily_index.loc[row.period_start:row.period_end, measure].mean()
            for row in physical.itertuples(index=False)
        ]
    return physical


def main():
    verify()
    OUT.mkdir(parents=True, exist_ok=True)
    source_values, prices, china_check = import_prices()
    market, daily_index = activity_and_brent()
    variants = {"volume": "tanker_volume_index", "count": "tanker_count_index"}
    panels, errors, predictions, coefficients = {}, [], [], []
    for variant, measure in variants.items():
        panel = make_panel(prices, market, measure)
        panels[variant] = panel
        train = panel.dropna().loc[:TRAIN_END]
        test = panel.loc["2025-01-01":]
        if len(panel) != 60 or len(train) != 41 or len(test) != 18:
            raise ValueError("Unexpected five-year split")
        fit = fit_models(train)
        for country in COUNTRIES:
            model = fit[country]["full"]
            alpha, beta, gamma = model["coefs"]
            coefficients.append({"proxy": variant, "country": country, "tau_months": model["tau"],
                                 "alpha": alpha, "beta": beta, "gamma": gamma,
                                 "pct_for_10_index_points": 100 * np.expm1(0.1 * gamma)})
        metrics, estimates = evaluate(test, fit)
        errors.append(metrics.assign(proxy=variant))
        predictions.append(estimates.assign(proxy=variant))

    panel = panels["volume"]
    predictions = pd.concat(predictions, ignore_index=True)
    periods = []
    for label, begin, finish in REGIMES:
        block = panel.loc[begin:finish]
        periods.append({"regime": label, "months": len(block),
                        **block[["tanker_volume_index", "tanker_count_index", "brent_usd_bbl", *COUNTRIES]].mean().to_dict()})

    held_out = predictions.loc[predictions["mode"].eq("one_step")].copy()
    held_out["absolute_error_usd_t"] = abs(held_out.actual_usd_t - held_out.predicted_usd_t)
    by_period = []
    for label, begin, finish in [
        ("2025", "2025-01-01", "2025-12-01"),
        ("Jan to Feb 2026", "2026-01-01", "2026-02-01"),
        ("Mar to Jun 2026", "2026-03-01", END),
    ]:
        mask = held_out.month.between(begin, finish)
        by_period.append(held_out.loc[mask].groupby(["proxy", "country", "model"]).absolute_error_usd_t.mean()
                         .reset_index().assign(period=label))

    source_values.to_csv(OUT / "national_import_values.csv", index=False)
    china_check.to_csv(OUT / "china_source_crosscheck.csv")
    panel.to_csv(OUT / "monthly_panel.csv")
    market.loc[:"2021-06-01"].to_csv(OUT / "early_pandemic_context.csv")
    flow_crosscheck(daily_index).to_csv(OUT / "physical_flow_crosscheck.csv", index=False)
    pd.DataFrame(periods).to_csv(OUT / "regime_means.csv", index=False)
    pd.concat(errors, ignore_index=True).to_csv(OUT / "holdout_metrics.csv", index=False)
    pd.DataFrame(coefficients).to_csv(OUT / "fitted_coefficients.csv", index=False)
    pd.concat(by_period, ignore_index=True).to_csv(OUT / "holdout_mae_by_regime.csv", index=False)
    predictions.to_csv(OUT / "holdout_predictions.csv", index=False)
    crude = pd.read_csv(DATA / "wto_hormuz_daily.csv", parse_dates=["date"]).set_index("date").hormuz_index
    overlap = market[["tanker_volume_index", "tanker_count_index"]].join(crude.resample("MS").mean()).dropna()
    overlap.to_csv(OUT / "proxy_overlap.csv")
    summary = {
        "panel_months": len(panel), "price_observations": len(source_values),
        "first_month": START, "last_month": END,
        "training_transitions": 41, "holdout_transitions": 18, "training_last_month": TRAIN_END,
        "china_provider_rows": source_values.loc[source_values.country.eq("CHN"), "source"].value_counts().to_dict(),
        "china_source_overlap_months": len(china_check),
        "china_overlap_median_absolute_difference_pct": float(china_check.comtrade_vs_gacc_pct.abs().median()),
        "april_2020_brent_usd_bbl": float(market.loc["2020-04-01", "brent_usd_bbl"]),
        "volume_vs_crude_r_2025": float(overlap.loc["2025", "tanker_volume_index"].corr(overlap.loc["2025", "hormuz_index"])),
        "volume_vs_crude_r_full_overlap": float(overlap.tanker_volume_index.corr(overlap.hormuz_index)),
    }
    (OUT / "sample.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
