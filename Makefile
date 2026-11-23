PY ?= python

.PHONY: test typecheck bench bench-smoke data web

test:
	$(PY) -m pytest --cov=fabtwin --cov-report=term-missing

typecheck:
	$(PY) -m mypy fabtwin

bench:            ## regenerate every table, figure and web dataset (~45 min)
	PY=$(PY) bash scripts/bench_all.sh

bench-smoke:
	$(PY) scripts/bench_dispatch.py --reps 4 --warmup-reps 2 --out /tmp/smoke
	$(PY) scripts/bench_exact.py --quick --out /tmp/smoke-exact

data:             ## replay files + analytics for the web twin
	$(PY) scripts/export_scenarios.py
	$(PY) scripts/build_analytics.py

web: data
	cd web && npm ci && npm run build
