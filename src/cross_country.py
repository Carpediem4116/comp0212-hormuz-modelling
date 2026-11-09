"""Fit and validate four national crude import unit-value models."""

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "results" / "cross_country"
COUNTRIES = {"GBR": "United Kingdom", "USA": "United States", "CHN": "China", "IND": "India"}
FEATURES = {"shipment": ["shortfall"], "brent": ["log_brent"], "full": ["log_brent", "shortfall"]}
TAUS = np.geomspace(0.25, 6, 36)
END = pd.Timestamp("2026-08-01")
TRAIN_END = pd.Timestamp("2026-04-01")
PRE_END = pd.Timestamp("2026-02-01")
SEED = 212


def load_inputs():
    trade = pd.read_csv(DATA / "un_comtrade_crude_import_monthly.csv")
    trade = trade.loc[trade.country.isin(["GBR", "USA", "IND"]),
                      ["month", "country", "primary_value_usd", "weight_kg"]]
    trade = trade.rename(columns={"primary_value_usd": "value_usd", "weight_kg": "net_weight_kg"})
    china = pd.read_csv(DATA / "china_crude_import_monthly.csv")
    china["country"] = "CHN"
    prices = pd.concat([trade, china[trade.columns]], ignore_index=True)
    prices["month"] = pd.to_datetime(prices.month).dt.to_period("M").dt.to_timestamp()
    if prices.duplicated(["month", "country"]).any():
        raise ValueError("Multiple crude totals for one country/month")
    values = prices[["value_usd", "net_weight_kg"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Trade inputs must have positive value and mass")
    prices["usd_per_tonne"] = 1000 * prices.value_usd / prices.net_weight_kg
    price_table = prices.pivot(index="month", columns="country", values="usd_per_tonne")
    price_table = price_table[list(COUNTRIES)].loc[:END]

    shipment = pd.read_csv(DATA / "wto_hormuz_daily.csv", parse_dates=["date"]).set_index("date")
    if shipment.index.has_duplicates or (shipment.hormuz_index < 0).any():
        raise ValueError("Duplicate dates or negative values in WTO index")
    by_month = shipment.hormuz_index.resample("MS").agg(["mean", "count"])
    full_month = by_month["count"] == by_month.index.days_in_month
    shipments = by_month["mean"].where(full_month).rename("hormuz_index")

    daily_brent = pd.read_csv(DATA / "eia_brent_daily.csv", parse_dates=["date"]).set_index("date")
    if daily_brent.index.has_duplicates or (daily_brent.brent_usd_bbl <= 0).any():
        raise ValueError("Duplicate dates or invalid Brent quotes")
    brent_months = daily_brent.brent_usd_bbl.resample("MS").agg(["mean", "count"])
    brent = brent_months["mean"].where(brent_months["count"] >= 15).rename("brent_usd_bbl")
    return prices, price_table, shipments, brent


def build_panel(price_table, shipments, brent, lag):
    panel = price_table.join(brent).join(shipments)
    panel = panel.reindex(pd.date_range(price_table.index[0], END, freq="MS", name="month"))
    for country in COUNTRIES:
        panel[f"log_{country}"] = np.log(panel[country])
        panel[f"lag_{country}"] = panel[f"log_{country}"].shift()
    required = [*COUNTRIES, "brent_usd_bbl", "hormuz_index", "shipment_input"]
    panel = panel.join(shipments.shift(lag).rename("shipment_input")).dropna(subset=required)
    if panel.empty or not panel.index.equals(pd.date_range(panel.index[0], END, freq="MS", name="month")):
        raise ValueError("Expected a contiguous panel through August 2026")
    panel["log_brent"] = np.log(panel.brent_usd_bbl)
    panel["shortfall"] = (100 - panel.shipment_input) / 100
    return panel


def exact_step(state, target, tau):
    return state + (-np.expm1(-1 / tau)) * (target - state)


def verify():
    for tau in (0.25, 1, 3, 6):
        state = 0.0
        for step in range(1, 7):
            state = exact_step(state, 1.0, tau)
            np.testing.assert_allclose(state, 1 - np.exp(-step / tau), atol=1e-14)
        assert exact_step(1.0, 1.0, tau) == 1.0
        assert 0 < exact_step(state, 0.0, tau) < state


def design(frame, features):
    return np.column_stack([np.ones(len(frame)), frame[features].to_numpy()])


def fit_model(train, country, features):
    x = design(train, features)
    state = train[f"lag_{country}"].to_numpy()
    observed = train[f"log_{country}"].to_numpy()
    best = None
    for tau in TAUS:
        rho = np.exp(-1 / tau)
        response = observed - rho * state
        predictors = (1 - rho) * x
        coefficients, _, rank, _ = np.linalg.lstsq(predictors, response, rcond=None)
        if rank != predictors.shape[1]:
            raise ValueError(f"Rank-deficient fit for {country}")
        residual = response - predictors @ coefficients
        mse = np.mean(residual**2)
        if best is None or mse < best["mse"]:
            best = {"mse": mse, "tau": tau, "features": features, "coefs": coefficients, "residual": residual}
    return best


def fit_models(train):
    return {country: {name: fit_model(train, country, features) for name, features in FEATURES.items()}
            for country in COUNTRIES}


def replay(test, country, model, recursive):
    previous = test[f"lag_{country}"].to_numpy()
    if model is None:
        return np.exp(np.repeat(previous[0], len(test)) if recursive else previous)
    target = design(test, model["features"]) @ model["coefs"]
    tau = model["tau"]
    if not recursive:
        return np.exp(exact_step(previous, target, tau))
    state = previous[0]
    history = []
    for value in target:
        state = exact_step(state, value, tau)
        history.append(state)
    return np.exp(history)


def evaluate(test, fits):
    metrics, predictions = [], []
    for country in COUNTRIES:
        actual = test[country].to_numpy()
        for name, model in {"persistence": None, **fits[country]}.items():
            for recursive, mode in [(False, "one_step"), (True, "recursive")]:
                estimate = replay(test, country, model, recursive)
                error = estimate - actual
                metrics.append({"country": country, "model": name, "mode": mode,
                                "mae_usd_t": np.mean(np.abs(error)), "rmse_usd_t": np.sqrt(np.mean(error**2))})
                predictions.append(pd.DataFrame({"month": test.index, "country": country, "model": name, "mode": mode,
                                                 "actual_usd_t": actual, "predicted_usd_t": estimate}))
    return pd.DataFrame(metrics), pd.concat(predictions, ignore_index=True)


def simulate(train, fits):
    n, months, block = 10_000, 6, 2
    rng = np.random.default_rng(SEED)
    severity = rng.beta(8, 12, n)
    duration = rng.integers(1, 4, n)
    x = np.where(np.arange(months)[None, :] < duration[:, None], severity[:, None], 0.0)
    residual = np.column_stack([fits[country]["full"]["residual"] for country in COUNTRIES])
    residual -= residual.mean(axis=0)
    starts = rng.integers(0, len(residual) - block + 1, (n, months // block))
    noise = residual[(starts[:, :, None] + np.arange(block)).reshape(n, months)]
    baseline_brent = train.loc[:PRE_END, "log_brent"].median()
    output = []
    for j, country in enumerate(COUNTRIES):
        model = fits[country]["full"]
        alpha, beta, gamma = model["coefs"]
        equilibrium = alpha + beta * baseline_brent
        reference = stressed = np.full(n, equilibrium)
        for month in range(months + 1):
            if month:
                eps = noise[:, month - 1, j]
                reference = exact_step(reference, equilibrium, model["tau"]) + eps
                stressed = exact_step(stressed, equilibrium + gamma * x[:, month - 1], model["tau"]) + eps
            gap = 100 * np.expm1(stressed - reference)
            lo, med, hi = np.quantile(gap, [0.05, 0.50, 0.95])
            pl, pm, ph = np.quantile(np.exp(stressed), [0.05, 0.50, 0.95])
            output.append({"country": country, "month": month, "gap_p05_pct": lo, "gap_p50_pct": med,
                           "gap_p95_pct": hi, "level_p05_usd_t": pl, "level_p50_usd_t": pm, "level_p95_usd_t": ph})
    result = pd.DataFrame(output)
    assert (result.loc[result.month == 0, "gap_p50_pct"] == 0).all()
    return result


def main():
    verify()
    OUT.mkdir(parents=True, exist_ok=True)
    prices, price_table, shipments, brent = load_inputs()
    panels = {lag: build_panel(price_table, shipments, brent, lag) for lag in (0, 1, 2)}
    panel = panels[1]
    common_start = max(frame.dropna().index[0] for frame in panels.values())
    train = panel.dropna().loc[common_start:TRAIN_END]
    test = panel.loc[panel.index > TRAIN_END]
    assert len(train) >= 12 and len(test) == 4
    fits = fit_models(train)
    metrics, predictions = evaluate(test, fits)
    alternatives = {f"lag_{lag}": fit_models(panels[lag].loc[common_start:TRAIN_END]) for lag in (0, 2)}
    alternatives["pre_disruption"] = fit_models(train.loc[:PRE_END])
    coefficients = []
    for specification, set_of_fits in {"main": fits, **alternatives}.items():
        for country in COUNTRIES:
            model = set_of_fits[country]["full"]
            alpha, beta, gamma = model["coefs"]
            coefficients.append({"specification": specification, "country": country, "tau_months": model["tau"],
                                 "alpha": alpha, "beta": beta, "gamma": gamma,
                                 "pct_for_10_index_points": 100 * np.expm1(0.1 * gamma)})
    sample = {"panel_start": str(panel.index[0].date()), "last_month": str(END.date()), "panel_months": len(panel),
              "fit_start": str(common_start.date()), "training_end": str(TRAIN_END.date()),
              "training_transitions": len(train), "holdout_transitions": len(test),
              "train_shortfall_brent_log_r": train.shortfall.corr(train.log_brent), "seed": SEED}
    changes = panel[[*(f"log_{code}" for code in COUNTRIES), "shortfall", "log_brent"]].diff().dropna()
    correlations = changes.corr().loc[[f"log_{code}" for code in COUNTRIES], ["shortfall", "log_brent"]]
    prices.to_csv(OUT / "national_trade_unit_values.csv", index=False)
    panel.to_csv(OUT / "monthly_panel.csv")
    metrics.to_csv(OUT / "holdout_metrics.csv", index=False)
    predictions.to_csv(OUT / "holdout_predictions.csv", index=False)
    correlations.to_csv(OUT / "change_correlations.csv")
    pd.DataFrame(coefficients).to_csv(OUT / "sensitivity.csv", index=False)
    simulate(train, fits).to_csv(OUT / "scenario.csv", index=False)
    (OUT / "sample.json").write_text(json.dumps(sample, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(sample, indent=2))
    print("Verified analytical step response, equilibrium and decay.")


if __name__ == "__main__":
    main()
