#!/usr/bin/env bash
# Regenerates every table and figure. Fixed seeds; ~45 min on 16 cores.
set -euo pipefail
PY=${PY:-python}
$PY scripts/bench_dispatch.py --reps 200
$PY scripts/bench_exact.py
$PY scripts/bench_maintenance.py
$PY scripts/bench_oht.py --reps 60
$PY scripts/bench_headline.py --reps 200 --rh-reps 20
$PY scripts/make_figures.py
$PY scripts/export_scenarios.py
$PY scripts/build_analytics.py
