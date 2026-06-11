# SP3 Noise Band Dashboard

Live dashboard showing run-to-run noise for Speedometer 3 subtests, pulled directly from Treeherder.

**Live**: https://92kns.github.io/noise-dash/

## What it shows

For each SP3 subtest on a given platform, the dashboard computes a noise band using the empirical P5 to P95 range of `performance_datum.value` on mozilla-central baseline runs. Values inside the band are normal variation. Values outside are likely a real change.

Two metrics per test:

| Metric | What it tells you |
|---|---|
| **Band width** `(P95 - P05) / median * 100%` | How wide the noise floor is, directly usable as an alert threshold |
| **CV** `stddev / mean * 100%` | Normalized spread, good for ranking and comparing across tests |

Noisiness labels: **quiet** below 4%, **moderate** 4 to 10%, **noisy** 10 to 20%, **very noisy** above 20%

## Features

- Live data from [Treeherder](https://treeherder.mozilla.org), no pre-baked data, refreshes on every platform switch
- Platforms: Windows 11, Windows 11 hw-ref, macOS ARM, Linux, Android A55
- Repository toggle between mozilla-central and autoland
- Sortable table with color-coded noisiness badges and Perfherder links per test
- Time-series chart with a shaded noise band that follows the current date range
- Date range presets (1w, 1m, 3m, 1yr) plus a custom date picker for both the chart and table band window
- Overall Score pinned to the top of the table

## Background

Part of [Bug 2040804](https://bugzilla.mozilla.org/show_bug.cgi?id=2040804), which investigates a per-test noisiness metric for Firefox performance tests.

Key findings from the full analysis:
- Windows regular pool is about 3x noisier than hw-ref for the same tests
- macOS ARM is the quietest platform with a median band under 5%
- The current universal 2% alert threshold is only appropriate for macOS ARM quiet tests
- `cpuTime`, `powerUsage_*`, and GC metrics are intrinsically noisy on all platforms

## Usage

Open `noise_dashboard.html` directly in a browser. No server or build step needed. Data loads live from `treeherder.mozilla.org`.

## Actions

- **deploy.yml** deploys to GitHub Pages on every push to main
- **health-check.yml** runs weekly to verify Treeherder still serves SP3 signatures for all platforms
