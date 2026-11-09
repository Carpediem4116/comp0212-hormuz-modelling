"""Download the public WTO and EIA inputs used by the two studies."""

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests


DATA = Path(__file__).resolve().parents[1] / "data"
START = "2020-01-01"
END = "2026-10-25"
SOURCES = {
    "wto_hormuz_daily.csv": (
        "https://wtomais.blob.core.windows.net/strait-of-hormuz-tracker/voy_intake_index_curde_oil_export.csv",
        "voy_load_date", "voy_intake_index", "hormuz_index",
    ),
    "eia_brent_daily.csv": (
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU&cosd={START}&coed={END}",
        "observation_date", "DCOILBRENTEU", "brent_usd_bbl",
    ),
}


def main():
    snapshots = []
    manifest = {}
    for name, (url, date_column, value_column, output_column) in SOURCES.items():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        raw = pd.read_csv(io.BytesIO(response.content), usecols=[date_column, value_column])
        raw = raw.rename(columns={date_column: "date", value_column: output_column})
        raw["date"] = pd.to_datetime(raw["date"], errors="raise")
        raw[output_column] = pd.to_numeric(raw[output_column].replace(".", pd.NA), errors="raise")
        raw = raw.loc[raw.date.between(START, END)].dropna().sort_values("date")
        if raw.empty or raw.date.duplicated().any() or (raw[output_column] < 0).any():
            raise ValueError(f"Unexpected source coverage or values for {name}")
        content = raw.to_csv(index=False, lineterminator="\n").encode("utf-8")
        manifest[name] = {
            "source_url": url,
            "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            "source_last_modified": response.headers.get("Last-Modified"),
            "source_sha256": hashlib.sha256(response.content).hexdigest(),
            "snapshot_sha256": hashlib.sha256(content).hexdigest(),
            "rows": len(raw),
            "first_date": raw.date.min().date().isoformat(),
            "last_date": raw.date.max().date().isoformat(),
        }
        snapshots.append((name, content))
    DATA.mkdir(exist_ok=True)
    for name, content in snapshots:
        (DATA / name).write_bytes(content)
    (DATA / "market_source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
