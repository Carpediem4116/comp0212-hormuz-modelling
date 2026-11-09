# COMP0212 Hormuz Modelling

Python code for two related studies of crude oil import costs in the United Kingdom, United States, China and India. The five-year study uses a monthly IMF PortWatch tanker-activity proxy. A separate, shorter study uses the WTO–AXSMarine outbound crude shipment index. The models compare adjustment to Brent and the shipping measures against persistence, with chronological holdouts and a stochastic disruption scenario.

## Set up

Use Python 3.11 or a compatible newer version. Run the commands from the repository root in an active Python environment.

```sh
python -m pip install -r requirements.txt
```

## Prepare the inputs

The scripts download the public inputs to the local data directory. Source providers can revise historical values and their terms apply. UN Comtrade queries are rate-limited, so this step can take several minutes.

```sh
python src/fetch_inputs.py
python data/fetch_portwatch_hormuz.py
python data/fetch_comtrade_monthly.py --start 2021-07 --end 2024-12 --output data/un_comtrade_crude_import_extended.csv
python data/fetch_comtrade_monthly.py --start 2025-01 --end 2026-08
python data/fetch_china_gacc_monthly.py --start 2021-07 --end 2024-12 --output data/china_crude_import_extended.csv
python data/fetch_china_gacc_monthly.py --start 2025-01 --end 2026-08
python data/build_reference_tables.py
```

## Run the analysis

```sh
python src/five_year.py
python src/cross_country.py
python results/five_year/figures.py
python results/cross_country/figures.py
```

The scripts write the aligned panels, validation metrics and figures under the corresponding results directories. To produce the optional LaTeX table snippets, create a local report directory and run both table scripts.

```sh
mkdir report
python src/five_year_tables.py
python src/report_tables.py
```

## Data sources

- [IMF PortWatch daily chokepoint data](https://portwatch.imf.org/datasets/3da2b9ca97684916b75c4013f95d18ab_0/about)
- [WTO–AXSMarine Strait of Hormuz Trade Tracker](https://datalab.wto.org/Strait-of-Hormuz-Trade-Tracker)
- [EIA Brent spot price via FRED](https://fred.stlouisfed.org/series/DCOILBRENTEU)
- [UN Comtrade](https://comtradeplus.un.org/) and [China Customs monthly statistics](http://english.customs.gov.cn/statics/report/monthly.html)
- [EIA oil transit chokepoints](https://www.eia.gov/international/content/analysis/special_topics/World_Oil_Transit_Chokepoints/), [EIA global energy security](https://www.eia.gov/outlooks/steo/report/energysecurity/article.php) and [IEA Strait of Hormuz](https://www.iea.org/about/strait-of-hormuz)

PortWatch covers tanker traffic in both directions. The WTO index measures AIS-visible outbound crude shipments. The code analyses these series separately. Customs unit values represent import value per tonne and depend on the mix of oil received. Holdout results measure model performance on those dates.
