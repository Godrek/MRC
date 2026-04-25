PY ?= python3
PIP ?= $(PY) -m pip

.PHONY: install test smoke run clean

install:
	$(PIP) install -e ".[dev]"

test:
	$(PY) -m pytest -q

smoke:
	$(PY) -m valkey_tiering_mrc run-all \
	    --config examples/default_config.yaml \
	    --out runs/smoke \
	    --events 5000 \
	    --keyspace 5000 \
	    --capacity-points 51

run:
	$(PY) -m valkey_tiering_mrc run-all \
	    --config examples/default_config.yaml \
	    --out runs/default

clean:
	rm -rf data/ results/ runs/ build/ dist/ \
	    src/*.egg-info src/valkey_tiering_mrc/__pycache__ \
	    tests/__pycache__ .pytest_cache
