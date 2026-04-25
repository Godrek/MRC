# valkey-tiering-mrc

A reproducible Python harness for **synthetic miss-ratio-curve (MRC)** experiments
on Valkey-style cache workloads, computed under exact warmed/cyclic LRU.

It can:

1. Generate synthetic GET-only access traces for **8 workload shapes**.
2. Compute exact warmed/cyclic LRU MRCs.
3. Output **object/request miss** curves and **byte miss** curves.
4. Output **inverse MRC curves** (target miss ratio → required DRAM capacity).
5. Emit per-workload PNGs and contact-sheet PNGs.

All workload parameters are configurable via YAML and selected CLI overrides.

---

## Why warmed/cyclic MRC?

A "cold" LRU MRC double-counts compulsory (first-touch) misses that come from
the trace simply not having seen a key yet. That makes the curve look worse
than the steady-state cache ever would, and it does not converge to 0 misses
even at infinite capacity within a finite trace.

This harness uses a **warmed/cyclic** model instead:

- Replay the trace twice back-to-back.
- Only measure accesses in the second pass.
- Every key referenced in the second pass has already been inserted during
  the first pass.

Consequences:

- At `capacity = 100% of unique value bytes`, both object miss and byte miss
  are exactly **0**. This is enforced as a smoke-test invariant.
- Curves reflect steady-state hit rate, not transient warmup.

---

## Object miss vs byte miss

- **`object_miss_ratio` (= `request_miss_ratio`)**: fraction of requests
  that miss. Each request counts the same.
- **`byte_miss_ratio`**: fraction of *requested value bytes* that miss.
  Weighted by the value size of the requested key.

These can diverge when the value-size distribution is skewed: a workload
where popular keys are small but unpopular keys are huge will have a low
object miss but a high byte miss for the same DRAM capacity (and vice versa).

The deterministic key→size map (top-byte-of-hash bucketing into
small/medium/large pools) makes the same key always have the same size in
every trace, so curves can be compared apples-to-apples across workloads.

---

## Forward MRC vs inverse MRC

- **Forward MRC**: capacity → miss ratio.
  *"At C bytes of DRAM, what miss ratio do I get?"*
- **Inverse MRC**: target miss ratio → required capacity.
  *"How much DRAM do I need to keep request miss ≤ X%?"*
  *"How much DRAM do I need to keep byte miss ≤ X%?"*

The inverse curves are derived by linear interpolation between adjacent
forward-curve points. Targets that the forward curve never reaches are
emitted as `NaN`. With the warmed/cyclic model, **target = 0%** is always
reachable (at 100% of unique value bytes).

---

## Repository layout

```
.
├── README.md
├── pyproject.toml
├── Makefile
├── examples/
│   └── default_config.yaml
├── src/valkey_tiering_mrc/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── traces.py
│   ├── lru.py
│   ├── plot.py
│   └── pipeline.py
└── tests/
    ├── test_lru.py
    ├── test_traces.py
    └── test_pipeline_smoke.py
```

The package is usable both as a CLI (`python -m valkey_tiering_mrc ...`) and
as importable Python modules (`from valkey_tiering_mrc import lru, traces, ...`).

---

## Install

```bash
make install
# or, manually:
pip install -e ".[dev]"
```

Requires Python ≥ 3.10.

---

## Running a smoke test

```bash
make smoke
```

This runs `run-all` with a 5,000-event / 5,000-keyspace / 51-capacity-point
configuration and writes everything under `runs/smoke/`:

```
runs/smoke/
├── traces/                 # one CSV per enabled workload
└── lru/
    ├── lru_warmed_object_and_byte_mrc_curves.csv
    ├── lru_warmed_inverse_mrc_curves.csv
    └── plots/
        ├── forward_<workload>.png        (one per workload)
        ├── inverse_<workload>.png        (one per workload)
        ├── forward_contact_sheet.png
        └── inverse_contact_sheet.png
```

---

## Running the full experiment

```bash
make run
```

This runs the pipeline with the full default config (1M events, 1M keyspace,
1001 capacity points) and writes everything under `runs/default/`.

The CLI also exposes the four subcommands individually:

```bash
python -m valkey_tiering_mrc generate-traces \
    --config examples/default_config.yaml \
    --out data/traces

python -m valkey_tiering_mrc compute-lru \
    --traces data/traces \
    --out results/lru \
    --capacity-points 1001

python -m valkey_tiering_mrc plot \
    --curves results/lru/lru_warmed_object_and_byte_mrc_curves.csv \
    --inverse results/lru/lru_warmed_inverse_mrc_curves.csv \
    --out results/lru/plots

python -m valkey_tiering_mrc run-all \
    --config examples/default_config.yaml \
    --out runs/default
```

CLI overrides (apply to `generate-traces` and `run-all`):

- `--events <N>`
- `--keyspace <N>`
- `--seed <N>`
- `--capacity-points <N>`

---

## Configuring workload parameters

Every workload is defined in `examples/default_config.yaml`. To disable a
workload, set its `enabled: false`. To tweak parameters, edit the YAML — no
code changes needed. Key knobs per workload:

- `uniform_random`: nothing — pure random baseline.
- `moving_hot_window`: `window_size`, `move_every_events`, `window_step`,
  `hot_probability`.
- `stable_zipfian_hot_set`: `zipf_alpha`.
- `stable_hot_set_plus_scans`: `hot_keyspace`, `hot_zipf_alpha`,
  `period_events`, `scan_events_per_period`, `scan_start_key`.
- `rotating_hot_sets`: `phase_len_events`, `phases`, `hotset_size`,
  `hot_probability`.
- `hot_core_noisy_tail`: `core_keyspace`, `core_zipf_alpha`,
  `core_probability`, `tail_start_key`.
- `size_skewed`: `zipf_alpha` (uses the deterministic size map to surface
  object-vs-byte divergence).
- `read_churn_hot_region`: `refresh_every_events`, `hotset_size`,
  `hot_probability`.

Global knobs (`global` block): `seed`, `events`, `keyspace`, `chunk_size`,
`capacity_points`. Value-size knobs (`value_sizes` block): bucket
probabilities and the small/medium/large size pools.

---

## Reproducibility

- A single `global.seed` deterministically derives a per-workload seed, so
  re-running with the same config yields byte-identical traces and curves.
- The deterministic key→size map (top byte of a 64-bit multiplicative hash,
  bucketed into small/medium/large) means the same key has the same value
  size across every trace.

---

## CSV output schemas

`lru_warmed_object_and_byte_mrc_curves.csv`:

- `workload_file`, `workload`, `policy`,
  `capacity_fraction_of_unique_bytes`, `capacity_bytes`,
  `unique_objects_in_trace`, `unique_value_bytes_in_trace`,
  `total_requested_bytes`,
  `object_miss_ratio`, `byte_miss_ratio`.

`lru_warmed_inverse_mrc_curves.csv`:

- `workload`, `policy`, `target_miss_ratio_percent`,
  `required_capacity_percent_of_unique_bytes_for_request_miss`,
  `required_capacity_percent_of_unique_bytes_for_byte_miss`,
  `required_capacity_bytes_for_request_miss`,
  `required_capacity_bytes_for_byte_miss`,
  `unique_value_bytes_in_trace`.

---

## Tests

```bash
make test
```

Tests cover:

- LRU sanity (`[0,1,0,1]` with sizes `[10,20,10,20]` → 0 miss at C=30).
- Monotonicity of both miss curves vs capacity.
- Trace generation for all enabled workloads at `events=100, keyspace=100`.
- Pipeline smoke test that asserts 0 miss at 100% capacity for every
  workload and that all expected output artifacts (CSVs + contact sheets)
  exist.

---

## Current limitations

- **GET-only** traces (no SET / DEL / EXPIRE / RESP shape).
- **Exact LRU only** — no LFU, no probabilistic eviction, no SLRU/2Q/ARC.
- **No promotion / spill / SSD-pressure** modeling. The MRC reflects DRAM
  capacity only; tiering effects are not simulated.
- **No TTL / write / invalidation** modeling.
- **No multi-tenancy / class-of-service** modeling.

These are explicit non-goals for v0.1 — the harness is intentionally a
clean reference for warmed/cyclic exact-LRU MRCs.
