PY ?= python

.PHONY: test typecheck bench bench-smoke

test:
	$(PY) -m pytest --cov=fabtwin --cov-report=term-missing

typecheck:
	$(PY) -m mypy fabtwin

bench:
	$(PY) scripts/bench_dispatch.py --reps 200

bench-smoke:
	$(PY) scripts/bench_dispatch.py --reps 4 --warmup-reps 2 --out /tmp/smoke
