# SP3 Noise Band Dashboard

Live dashboard showing run-to-run noise for Speedometer 3 subtests, fetched directly from Treeherder.

**Live**: https://92kns.github.io/noise-dash/

## What it shows

For each SP3 subtest on a given platform, the dashboard computes a **noise band** — the empirical P5–P95 range of `performance_datum.value` on mozilla-central baseline runs. Values inside the band are normal variation; values outside are likely a real change.

Two metrics per test:

| Metric | What it tells you |
|---|---|
| **Band width** `(P95 − P05) / median × 100%` | How wide the noise floor is; directly usable as an alert threshold |
| **CV** `stddev / mean × 100%` | Normalized spread; good for ranking and comparing across tests |

Noisiness labels: **quiet** < 4% · **moderate** 4–10% · **noisy** 10–20% · **very noisy** ≥ 20%

## Features

- Live data from [Treeherder](https://treeherder.mozilla.org) — no pre-baked data, refreshes on every platform switch
- **Platforms**: Windows 11, Windows 11 hw-ref, macOS ARM, Linux, Android A55
- **Repository**: mozilla-central (noise baseline) or autoland (more data points)
- **Table**: all subtests sorted by band width, color-coded noisiness badge, Perfherder links
- **Chart**: time-series scatter with shaded P5/P95 band; band follows the chart's current range
- **Date ranges**: preset (1w / 1m / 3m / 1yr) or custom date picker — for both chart and table band window
- **Overall Score** is always pinned to the top of the table

## Background

Part of [Bug 2040804](https://bugzilla.mozilla.org/show_bug.cgi?id=2040804) — investigating a per-test noisiness metric for Firefox performance tests.

Key findings from the full analysis (see `../FINDINGS.md`):
- Windows regular pool is ~3× noisier than hw-ref for the same tests
- macOS ARM is the quietest platform (median band < 5%)
- The current universal 2% alert threshold is only appropriate for macOS ARM quiet tests
- `cpuTime`, `powerUsage_*`, and GC metrics are intrinsically noisy on all platforms

## Usage

Open `noise_dashboard.html` directly in a browser — no server or build step needed. Data loads live from `treeherder.mozilla.org`.

## Actions

- **deploy.yml**: deploys to GitHub Pages on every push to `main`
- **health-check.yml**: runs weekly to verify Treeherder still serves SP3 signatures for all platforms; alerts if any are missing
