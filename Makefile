PY ?= python3
PIP ?= $(PY) -m pip

.PHONY: install test smoke smoke-lfu run compute-lfu compare clean

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

smoke-lfu:
	$(PY) -m valkey_tiering_mrc run-all \
	    --config examples/default_config.yaml \
	    --out runs/smoke \
	    --events 5000 \
	    --keyspace 5000 \
	    --capacity-points 51 \
	    --policies lru,true_lfu

run:
	$(PY) -m valkey_tiering_mrc run-all \
	    --config examples/default_config.yaml \
	    --out runs/default

compute-lfu:
	$(PY) -m valkey_tiering_mrc compute-lfu \
	    --traces data/traces \
	    --out results/lfu \
	    --capacity-points 1001

compare:
	$(PY) -m valkey_tiering_mrc compare-policies \
	    --lru-curves results/lru/lru_warmed_object_and_byte_mrc_curves.csv \
	    --lfu-curves results/lfu/true_lfu_warmed_object_and_byte_mrc_curves.csv \
	    --lru-inverse results/lru/lru_warmed_inverse_mrc_curves.csv \
	    --lfu-inverse results/lfu/true_lfu_warmed_inverse_mrc_curves.csv \
	    --out results/compare

clean:
	rm -rf data/ results/ runs/ build/ dist/ \
	    src/*.egg-info src/valkey_tiering_mrc/__pycache__ \
	    tests/__pycache__ .pytest_cache
