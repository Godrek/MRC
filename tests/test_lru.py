"""Unit tests for the warmed/cyclic LRU implementation."""

from __future__ import annotations

import numpy as np

from valkey_tiering_mrc import lru


def test_full_capacity_zero_miss_simple():
    keys = np.array([0, 1, 0, 1], dtype=np.int64)
    sizes = np.array([10, 20, 10, 20], dtype=np.int64)
    mrc = lru.compute_mrc(
        keys=keys,
        sizes=sizes,
        capacity_points=4,
        workload="tiny",
        workload_file="tiny.csv",
    )
    # Unique value bytes = 10 + 20 = 30
    assert mrc.unique_value_bytes_in_trace == 30
    # At full (=30) capacity, both miss ratios must be 0
    assert mrc.capacity_bytes[-1] == 30
    assert mrc.object_miss_ratio[-1] == 0.0
    assert mrc.byte_miss_ratio[-1] == 0.0


def test_monotonicity():
    rng = np.random.default_rng(0)
    n = 5_000
    keyspace = 200
    keys = rng.integers(0, keyspace, size=n, dtype=np.int64)
    sizes = (rng.integers(1, 17, size=n, dtype=np.int64) * 64).astype(np.int64)
    # Match a deterministic key->size mapping by remapping size per first occurrence
    first_idx: dict[int, int] = {}
    for i, k in enumerate(keys):
        first_idx.setdefault(int(k), int(sizes[i]))
    sizes = np.array([first_idx[int(k)] for k in keys], dtype=np.int64)

    mrc = lru.compute_mrc(
        keys=keys,
        sizes=sizes,
        capacity_points=51,
        workload="rand",
        workload_file="rand.csv",
    )
    obj = mrc.object_miss_ratio
    byt = mrc.byte_miss_ratio
    # Monotonic non-increasing as capacity grows.
    assert np.all(np.diff(obj) <= 1e-12)
    assert np.all(np.diff(byt) <= 1e-12)
    # At zero capacity every access is a miss.
    assert obj[0] == 1.0
    assert byt[0] == 1.0
    # At full capacity, zero misses.
    assert obj[-1] == 0.0
    assert byt[-1] == 0.0


def test_required_bytes_two_keys_alternating():
    # keys [0,1,0,1], sizes [10,20,10,20]
    # Second-pass measurements happen at j=4..7 (i.e. n=4)
    # j=4, i=0, key 0, p=2 -> above = sum positions [3..3] = 20 -> required = 30
    # j=5, i=1, key 1, p=3 -> above = sum positions [4..4] = 10 -> required = 30
    # j=6, i=2, key 0, p=4 -> above = sum positions [5..5] = 20 -> required = 30
    # j=7, i=3, key 1, p=5 -> above = sum positions [6..6] = 10 -> required = 30
    keys = np.array([0, 1, 0, 1], dtype=np.int64)
    sizes = np.array([10, 20, 10, 20], dtype=np.int64)
    rb = lru.compute_required_bytes(keys, sizes)
    assert rb.tolist() == [30, 30, 30, 30]


def test_inverse_curve_shapes():
    keys = np.array([0, 1, 0, 1], dtype=np.int64)
    sizes = np.array([10, 20, 10, 20], dtype=np.int64)
    mrc = lru.compute_mrc(keys, sizes, capacity_points=11, workload="tiny", workload_file="tiny.csv")
    inv = lru.compute_inverse_curve(mrc)
    # 0..100 inclusive at 1% steps = 101 entries.
    assert inv["target_miss_ratio_percent"].size == 101
    # 0% target reachable at exactly unique_value_bytes (30)
    assert inv["required_capacity_bytes_for_request_miss"][0] == 30
    assert inv["required_capacity_bytes_for_byte_miss"][0] == 30
