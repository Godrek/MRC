# valkey-tiering-mrc

A reproducible Python harness for **synthetic miss-ratio-curve (MRC)** experiments
on Valkey-style cache workloads, computed under exact warmed/cyclic LRU.

It can:

1. Generate synthetic GET-only access traces for **8 workload shapes**.
2. Compute exact warmed/cyclic LRU MRCs.
3. Compute warmed/cyclic **true LFU** MRCs (per-capacity replay; global
   frequency counters with LRU tie-break).
4. Output **object/request miss** curves and **byte miss** curves.
5. Output **inverse MRC curves** (target miss ratio → required DRAM capacity).
6. Emit per-workload PNGs, contact-sheet PNGs, and **LRU-vs-LFU comparison**
   charts.

All workload parameters are configurable via YAML and selected CLI overrides.

---

## LRU results gallery

The charts below were generated from the full default LRU run
(`events=1,000,000`, `keyspace=1,000,000`, `capacity_points=1001`,
`seed=42`). Reproduce with `make run`.

### Forward MRC contact sheet (capacity → miss ratio)

![Forward MRC contact sheet](docs/charts/forward_contact_sheet.png)

### Inverse MRC contact sheet (target miss → required capacity)

![Inverse MRC contact sheet](docs/charts/inverse_contact_sheet.png)

### Per-workload curves

Each workload shows its forward MRC on the left (DRAM % vs miss %) and
its inverse MRC on the right (target miss % vs required DRAM %). Blue
is object/request miss; red is byte miss. The gap between the two
lines is the **object-vs-byte divergence** induced by the deterministic
heavy-tailed value-size map.

#### `uniform_random` — no-locality baseline

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/forward_uniform_random.png) | ![](docs/charts/inverse_uniform_random.png) |

#### `moving_hot_window` — LRU-friendly recency locality

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/forward_moving_hot_window.png) | ![](docs/charts/inverse_moving_hot_window.png) |

#### `stable_zipfian_hot_set` — stable popularity distribution

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/forward_stable_zipfian_hot_set.png) | ![](docs/charts/inverse_stable_zipfian_hot_set.png) |

#### `stable_hot_set_plus_scans` — scan pollution / anti-LRU workload

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/forward_stable_hot_set_plus_scans.png) | ![](docs/charts/inverse_stable_hot_set_plus_scans.png) |

#### `rotating_hot_sets` — phase changes / hot-set adaptation

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/forward_rotating_hot_sets.png) | ![](docs/charts/inverse_rotating_hot_sets.png) |

#### `hot_core_noisy_tail` — stable hot core plus tail noise

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/forward_hot_core_noisy_tail.png) | ![](docs/charts/inverse_hot_core_noisy_tail.png) |

#### `size_skewed` — object-vs-byte divergence demo

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/forward_size_skewed.png) | ![](docs/charts/inverse_size_skewed.png) |

#### `read_churn_hot_region` — rapidly shifting active region

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/forward_read_churn_hot_region.png) | ![](docs/charts/inverse_read_churn_hot_region.png) |

---

## True LFU results gallery

The charts below were generated from a warmed/cyclic true-LFU run at
`events=100,000`, `keyspace=100,000`, `capacity_points=51`, `seed=42`.
Same trace shapes and value-size mapping as the LRU run above; smaller
scale because true LFU does a **full per-capacity replay** instead of a
single stack-distance pass. Reproduce with:

```bash
python -m valkey_tiering_mrc run-all \
    --config examples/default_config.yaml \
    --out runs/lfu_demo \
    --events 100000 --keyspace 100000 --capacity-points 51 \
    --policies lru,true_lfu --seed 42
```

### Forward MRC contact sheet (capacity → miss ratio)

![Forward LFU MRC contact sheet](docs/charts/lfu/forward_contact_sheet.png)

### Inverse MRC contact sheet (target miss → required capacity)

![Inverse LFU MRC contact sheet](docs/charts/lfu/inverse_contact_sheet.png)

### Per-workload curves

Each workload shows its forward LFU MRC on the left and its inverse LFU
MRC on the right. Blue is object/request miss; red is byte miss.

#### `uniform_random` — no-locality baseline

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/lfu/forward_uniform_random.png) | ![](docs/charts/lfu/inverse_uniform_random.png) |

#### `moving_hot_window` — LRU-friendly recency locality

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/lfu/forward_moving_hot_window.png) | ![](docs/charts/lfu/inverse_moving_hot_window.png) |

#### `stable_zipfian_hot_set` — stable popularity distribution

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/lfu/forward_stable_zipfian_hot_set.png) | ![](docs/charts/lfu/inverse_stable_zipfian_hot_set.png) |

#### `stable_hot_set_plus_scans` — scan pollution / anti-LRU workload

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/lfu/forward_stable_hot_set_plus_scans.png) | ![](docs/charts/lfu/inverse_stable_hot_set_plus_scans.png) |

#### `rotating_hot_sets` — phase changes / hot-set adaptation

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/lfu/forward_rotating_hot_sets.png) | ![](docs/charts/lfu/inverse_rotating_hot_sets.png) |

#### `hot_core_noisy_tail` — stable hot core plus tail noise

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/lfu/forward_hot_core_noisy_tail.png) | ![](docs/charts/lfu/inverse_hot_core_noisy_tail.png) |

#### `size_skewed` — object-vs-byte divergence demo

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/lfu/forward_size_skewed.png) | ![](docs/charts/lfu/inverse_size_skewed.png) |

#### `read_churn_hot_region` — rapidly shifting active region

| Forward | Inverse |
| --- | --- |
| ![](docs/charts/lfu/forward_read_churn_hot_region.png) | ![](docs/charts/lfu/inverse_read_churn_hot_region.png) |

---

## LRU vs true LFU comparison

The charts below come from the same run as the LFU gallery above (LRU
recomputed at the same scale so the two policies share trace inputs):
`events=100,000`, `keyspace=100,000`, `capacity_points=51`, `seed=42`.
Blue is LRU; green is true LFU.

### Object/request miss — LRU vs true LFU

![LRU vs true LFU object miss](docs/charts/compare/lru_vs_true_lfu_object_contact_sheet.png)

### Byte miss — LRU vs true LFU

![LRU vs true LFU byte miss](docs/charts/compare/lru_vs_true_lfu_byte_contact_sheet.png)

### Combined per-workload (object + byte for both policies)

![LRU vs true LFU combined](docs/charts/compare/lru_vs_true_lfu_combined_contact_sheet.png)

### Inverse comparison: required capacity for object miss target

![LRU vs true LFU inverse object](docs/charts/compare/lru_vs_true_lfu_inverse_object_contact_sheet.png)

### Inverse comparison: required capacity for byte miss target

![LRU vs true LFU inverse byte](docs/charts/compare/lru_vs_true_lfu_inverse_byte_contact_sheet.png)

What to look for:

- **Workloads where LFU wins** (lower miss at the same capacity): stable
  popularity distributions and the hot-core-plus-noisy-tail shape — both
  reward a frequency-aware policy that doesn't get evicted by tail traffic.
- **Workloads where LRU wins or matches**: pure-recency shapes
  (`moving_hot_window`, `read_churn_hot_region`) and the no-locality
  `uniform_random` baseline. With no decay, LFU can be sticky on a stale
  hot set when popularity actually drifts.
- **Both policies** converge to **0 miss at 100% capacity** — the
  warmed/cyclic invariant.

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

## True LFU policy simulation

Two policies are computed in this harness, **using two different methods**:

- **LRU** is computed via a single warmed/cyclic byte stack-distance pass
  (Fenwick tree). One pass produces curves for every capacity point.
- **True LFU** is computed by **per-capacity full trace replay**. Each
  capacity gets its own simulation because the eviction choice depends on
  the live resident set under that capacity. Stack-distance does not
  generalize to LFU.

The LFU policy implemented here is intentionally **idealized**:

- Global frequency counters that **never decay**.
- LRU tie-break among resident keys with equal frequency.
- No approximate Morris counters, no randomized sampling, no admission
  threshold, no TTL, no writes, no decay.
- Capacity is resident DRAM value bytes; SSD/dataset is assumed to hold
  every value (this is a **spill/residency** simulator, not a
  cache-existence simulator).
- Same warmed/cyclic invariant as LRU: replay each trace twice; measure
  only the second pass; at 100% capacity both miss ratios are exactly 0.

This is **not** Valkey's approximate LFU. The point is to compare a
recency-based ideal (LRU) against a frequency-based ideal (true LFU) so
you can see when frequency wins, when recency wins, and when one becomes
sticky under phase changes (true LFU has no decay, so an old hot set can
shadow a new one).

### Performance note

True LFU per-capacity replay is significantly slower than the LRU
stack-distance pass. With the default config (1M events × 1001 capacity
points × 8 workloads) it is **not** practical to run unmodified. To keep
LFU experiments tractable, use one or more of:

- `--capacity-points` with a smaller value (e.g. 51 or 101 instead of 1001).
- `--workload <name1>,<name2>` on `compute-lfu` to filter to a subset.
- A smaller `--events` / `--keyspace` for the trace generation step.

The simulator is numba-jitted with O(resident_count) eviction scans —
intentionally simple for experiment correctness, not production
performance.

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

The CLI also exposes each subcommand individually:

```bash
python -m valkey_tiering_mrc generate-traces \
    --config examples/default_config.yaml \
    --out data/traces

python -m valkey_tiering_mrc compute-lru \
    --traces data/traces \
    --out results/lru \
    --capacity-points 1001

python -m valkey_tiering_mrc compute-lfu \
    --traces data/traces \
    --out results/lfu \
    --capacity-points 51 \
    --workload uniform_random,stable_zipfian_hot_set

python -m valkey_tiering_mrc plot \
    --curves results/lru/lru_warmed_object_and_byte_mrc_curves.csv \
    --inverse results/lru/lru_warmed_inverse_mrc_curves.csv \
    --out results/lru/plots

python -m valkey_tiering_mrc compare-policies \
    --lru-curves results/lru/lru_warmed_object_and_byte_mrc_curves.csv \
    --lfu-curves results/lfu/true_lfu_warmed_object_and_byte_mrc_curves.csv \
    --lru-inverse results/lru/lru_warmed_inverse_mrc_curves.csv \
    --lfu-inverse results/lfu/true_lfu_warmed_inverse_mrc_curves.csv \
    --out results/compare

python -m valkey_tiering_mrc run-all \
    --config examples/default_config.yaml \
    --out runs/default \
    --policies lru,true_lfu
```

CLI overrides (apply to `generate-traces` and `run-all`):

- `--events <N>`
- `--keyspace <N>`
- `--seed <N>`
- `--capacity-points <N>`

`run-all --policies` selects the policies to run (subset of `lru,true_lfu`,
default `lru`). When both are present, comparison plots are emitted under
`<out>/compare/`.

`compute-lfu --workload <name>[,<name>...]` filters which trace files to
simulate, useful for keeping LFU runs tractable.

There are also `make compute-lfu` and `make compare` targets that wire up
the same commands against `data/traces` / `results/lru` / `results/lfu`.

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
- **LRU and true LFU only** — no probabilistic eviction, no SLRU/2Q/ARC,
  no Valkey-style approximate LFU yet.
- **No decay** in the LFU implementation. Frequency counters grow forever,
  so a workload with phase changes can leave true LFU sticky on stale hot
  sets.
- **No promotion / spill / SSD-pressure** metrics. The MRC reflects DRAM
  capacity and miss ratio only; tiering effects are not simulated.
- **No TTL / write / invalidation** modeling.
- **No multi-tenancy / class-of-service** modeling.

These are explicit non-goals for v0.x — the harness is intentionally a
clean reference for warmed/cyclic exact-LRU MRCs and idealized true-LFU
MRCs that can be compared apples-to-apples.
