"""
SP3 noisiness analysis — Bug 2040804
Pulls 1-year daily SP3 data from Treeherder via STMO, computes regime-corrected
CV and P5/P95 noise bands per (test, platform), and writes noise_bands_final.csv.

Requirements: scipy, numpy (pip install scipy numpy)
Env: REDASH_API_KEY must be set (from sql.telemetry.mozilla.org/users/me)

Usage:
    python noise_analysis.py                  # fetch + analyse all platforms
    python noise_analysis.py --no-fetch       # skip fetch, reuse cached timeseries_*.json
    python noise_analysis.py --platform mac   # single platform
"""

import argparse
import csv
import json
import os
import statistics
import sys
import time
import urllib.request
from collections import defaultdict

import numpy as np
from scipy import signal
from scipy.stats import gaussian_kde

# ── Config ───────────────────────────────────────────────────────────────────

STMO_BASE = "https://sql.telemetry.mozilla.org"
STMO_QUERY_ID = 121149   # 1-year daily time series pull (Treeherder datasource)

PLATFORMS = {
    "windows":      "windows11-64-24h2-shippable",
    "windows-hwref":"windows11-64-24h2-hw-ref-shippable",
    "mac":          "macosx1500-aarch64-shippable",
    "linux1804":    "linux1804-64-shippable-qr",
    "linux2404":    "linux2404-64-shippable",
    "android-a55":  "android-hw-a55-14-0-aarch64-shippable",
}

# ── STMO fetch ────────────────────────────────────────────────────────────────

def stmo_api(method, path, data=None):
    api_key = os.environ.get("REDASH_API_KEY")
    if not api_key:
        sys.exit("REDASH_API_KEY not set — get it from sql.telemetry.mozilla.org/users/me")
    url = STMO_BASE + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }, method=method)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def fetch_timeseries(platform_names, days=365):
    """
    Pull daily-averaged performance_datum.value from mozilla-central for all
    SP3 Firefox/Fenix alertable leaf signatures on the given platforms.
    Returns list of row dicts: {test, platform, application, push_date, value_mean_on_day}.
    """
    platforms_sql = ", ".join(f"'{p}'" for p in platform_names)
    sql = f"""
WITH sp3_sigs AS (
  SELECT ps.id AS sig_id,
         COALESCE(ps.test,'') AS test,
         COALESCE(pp.platform,'') AS platform,
         COALESCE(ps.application,'') AS application
  FROM performance_signature ps
  JOIN performance_framework pf ON ps.framework_id = pf.id
  JOIN machine_platform pp ON ps.platform_id = pp.id
  JOIN repository r ON ps.repository_id = r.id
  WHERE pf.name = 'browsertime'
    AND ps.suite ILIKE '%speedometer3%'
    AND (
      (ps.application = 'firefox'
       AND ps.extra_options LIKE '%fission%' AND ps.extra_options LIKE '%webrender%'
       AND ps.extra_options NOT LIKE '%gecko-profile%'
       AND ps.extra_options NOT LIKE '%simpleperf%'
       AND ps.extra_options NOT LIKE '%nova%')
      OR
      (ps.application = 'fenix'
       AND ps.extra_options LIKE '%fission%' AND ps.extra_options LIKE '%webrender%'
       AND ps.extra_options NOT LIKE '%gecko-profile%'
       AND ps.extra_options NOT LIKE '%simpleperf%')
    )
    AND r.name = 'mozilla-central'
    AND ps.has_subtests = false
    AND ps.should_alert = true
    AND pp.platform IN ({platforms_sql})
)
SELECT s.test, s.platform, s.application,
       DATE(pd.push_timestamp) AS push_date,
       AVG(pd.value) AS value_mean_on_day,
       COUNT(pd.id) AS n_pushes_on_day
FROM sp3_sigs s
JOIN performance_datum pd ON pd.signature_id = s.sig_id
WHERE pd.push_timestamp > NOW() - INTERVAL '{days} days'
  AND pd.value IS NOT NULL
GROUP BY s.test, s.platform, s.application, DATE(pd.push_timestamp)
ORDER BY s.platform, s.test, DATE(pd.push_timestamp)
"""
    # Update query and execute via STMO
    stmo_api("POST", f"/api/queries/{STMO_QUERY_ID}", {"query": sql})
    resp = stmo_api("POST", f"/api/queries/{STMO_QUERY_ID}/results", {"parameters": {}})

    if "job" in resp:
        job_id = resp["job"]["id"]
        print(f"  queued job {job_id}, polling...")
        for _ in range(120):
            time.sleep(5)
            job = stmo_api("GET", f"/api/jobs/{job_id}")
            status = job["job"]["status"]
            if status == 3:
                result_id = job["job"]["query_result_id"]
                result = stmo_api("GET", f"/api/query_results/{result_id}")
                return result["query_result"]["data"]["rows"]
            if status == 4:
                sys.exit(f"Query failed: {job['job'].get('error')}")
            print(f"  status={status}...")
        sys.exit("Timed out waiting for query")
    elif "query_result" in resp:
        return resp["query_result"]["data"]["rows"]
    sys.exit("Unexpected response from STMO")

# ── Statistics ────────────────────────────────────────────────────────────────

def sarle(vals):
    """Sarle's bimodality coefficient. > 5/9 suggests bimodal."""
    n = len(vals)
    if n < 5:
        return 0
    m = statistics.mean(vals)
    s = statistics.stdev(vals)
    if s == 0:
        return 0
    c = [(v - m) / s for v in vals]
    sk = sum(x**3 for x in c) / n
    ku = sum(x**4 for x in c) / n - 3
    denom = ku + 3 * (n - 1)**2 / ((n - 2) * (n - 3)) if n > 3 else 1
    return (sk**2 + 1) / denom if denom else 0


def stable_vals(series):
    """
    For bimodal time series (regime shifts), return only the higher-performance
    regime's values. For unimodal series, return all values.

    Regime detection: find the largest gap between consecutive monthly medians
    and split there. Uses Sarle's coefficient > 5/9 as the bimodal guard.
    """
    vals = [v for _, v in series]
    if len(vals) < 10 or sarle(vals) <= 5 / 9:
        return vals

    months = defaultdict(list)
    for d, v in series:
        months[d[:7]].append(v)

    monthly_meds = {mo: statistics.median(mv) for mo, mv in months.items() if len(mv) >= 5}
    if not monthly_meds:
        return vals

    sorted_meds = sorted(monthly_meds.values())
    gaps = [(sorted_meds[i + 1] - sorted_meds[i], i) for i in range(len(sorted_meds) - 1)]
    if not gaps:
        return vals

    gap_val, gap_idx = max(gaps)
    total_range = sorted_meds[-1] - sorted_meds[0]
    if gap_val < total_range * 0.15:
        return vals

    boundary = (sorted_meds[gap_idx] + sorted_meds[gap_idx + 1]) / 2
    higher = [v for v in vals if v >= boundary]
    lower = [v for v in vals if v < boundary]
    use = higher if len(higher) >= len(lower) * 0.4 else lower
    return use if len(use) >= 10 else vals


def percentile(vals, p):
    sv = sorted(vals)
    idx = (len(sv) - 1) * p / 100
    lo, hi = int(idx), min(int(idx) + 1, len(sv) - 1)
    return sv[lo] + (sv[hi] - sv[lo]) * (idx - lo)


def compute_metrics(vals):
    if len(vals) < 5:
        return None
    med = statistics.median(vals)
    if med == 0:
        return None
    p05 = percentile(vals, 5)
    p95 = percentile(vals, 95)
    mean = statistics.mean(vals)
    cv = statistics.stdev(vals) / mean * 100 if len(vals) > 1 else 0
    band_width = (p95 - p05) / med * 100
    label = (
        "quiet" if band_width < 4 else
        "moderate" if band_width < 10 else
        "noisy" if band_width < 20 else
        "very_noisy"
    )
    return {
        "median": round(med, 3),
        "p05": round(p05, 3),
        "p95": round(p95, 3),
        "cv_pct": round(cv, 2),
        "band_width_pct": round(band_width, 2),
        "noisiness_label": label,
        "n_vals": len(vals),
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fetch", action="store_true", help="reuse cached JSON files")
    parser.add_argument("--platform", help="single platform key from PLATFORMS dict")
    args = parser.parse_args()

    target_platforms = (
        {args.platform: PLATFORMS[args.platform]}
        if args.platform and args.platform in PLATFORMS
        else PLATFORMS
    )

    cache_path = "timeseries_cache.json"

    if args.no_fetch and os.path.exists(cache_path):
        print(f"Loading cached data from {cache_path}")
        with open(cache_path) as f:
            rows = json.load(f)
    else:
        print(f"Fetching 1-year time series for: {list(target_platforms.values())}")
        rows = fetch_timeseries(list(target_platforms.values()))
        with open(cache_path, "w") as f:
            json.dump(rows, f)
        print(f"Fetched {len(rows)} rows, cached to {cache_path}")

    # Build per-(test, platform) time series
    ts = defaultdict(dict)
    for r in rows:
        if r.get("value_mean_on_day") is None:
            continue
        key = (r["test"], r["platform"])
        ts[key][r["push_date"]] = float(r["value_mean_on_day"])

    sorted_ts = {k: sorted(d.items()) for k, d in ts.items()}

    # Compute metrics
    results = []
    for (test, plat), series in sorted_ts.items():
        if plat not in target_platforms.values():
            continue
        if len(series) < 10:
            continue

        all_vals = [v for _, v in series]
        good_vals = stable_vals(series)
        is_bimodal = sarle(all_vals) > 5 / 9

        m = compute_metrics(good_vals)
        if not m:
            continue

        results.append({
            "platform": plat,
            "test": test if test else "score",
            "is_bimodal": is_bimodal,
            "n_days_total": len(series),
            "n_vals_used": m["n_vals"],
            **{k: v for k, v in m.items() if k != "n_vals"},
            "suggested_alert_threshold": round(max(2.0, round(m["band_width_pct"] * 2 * 2) / 2), 1),
        })

    results.sort(key=lambda r: (r["platform"], -r["band_width_pct"]))

    # Write CSV
    out = "noise_bands_final.csv"
    fields = [
        "platform", "test", "is_bimodal", "n_days_total", "n_vals_used",
        "median", "p05", "p95", "cv_pct", "band_width_pct",
        "noisiness_label", "suggested_alert_threshold",
    ]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow(r)

    print(f"\nWrote {len(results)} rows to {out}")

    # Summary
    print("\nPlatform summary (median band width, mode-corrected):\n")
    plat_rows = defaultdict(list)
    for r in results:
        plat_rows[r["platform"]].append(r)

    for plat, prs in sorted(plat_rows.items()):
        bws = sorted(r["band_width_pct"] for r in prs)
        bimo = sum(1 for r in prs if r["is_bimodal"])
        labels = defaultdict(int)
        for r in prs:
            labels[r["noisiness_label"]] += 1
        print(
            f"  {plat[:48]:48} n={len(prs):3} bimo={bimo:3}"
            f" | med band={bws[len(bws)//2]:5.1f}%"
            f" | quiet={labels['quiet']} mod={labels['moderate']}"
            f" noisy={labels['noisy']} v.noisy={labels['very_noisy']}"
        )


if __name__ == "__main__":
    main()
