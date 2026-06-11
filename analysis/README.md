# Analysis

Python script that pulls 1-year SP3 data from STMO and computes regime-corrected noisiness scores.

## Setup

```bash
pip install scipy numpy
export REDASH_API_KEY=<your key from sql.telemetry.mozilla.org/users/me>
```

## Run

```bash
cd analysis/

# full fetch + analysis (takes ~2 min)
python noise_analysis.py

# reuse cached data (faster for re-running with different params)
python noise_analysis.py --no-fetch

# single platform
python noise_analysis.py --platform mac
```

Writes `noise_bands_final.csv` with columns:
`platform, test, is_bimodal, n_days_total, n_vals_used, median, p05, p95, cv_pct, band_width_pct, noisiness_label, suggested_alert_threshold`

## Methodology

1. Pulls daily-averaged `performance_datum.value` from mozilla-central via STMO (Treeherder Postgres)
2. Detects temporal bimodality per test using Sarle's coefficient (> 5/9)
3. For bimodal tests: splits at the largest gap between consecutive monthly medians, uses only the higher-performance regime
4. Computes CV and P5/P95 band from the stable-regime values

See `../FINDINGS.md` for full methodology and results.
