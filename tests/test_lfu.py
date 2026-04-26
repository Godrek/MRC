"""Unit tests for the true-LFU policy and simulator."""

from __future__ import annotations

import numpy as np

from valkey_tiering_mrc.policies import TrueLFUCache
from valkey_tiering_mrc import lru
from valkey_tiering_mrc.simulate import compute_true_lfu_mrc


def _replay_exclude_first_touch(keys, sizes, capacity_bytes):
    cache = TrueLFUCache(capacity_bytes)
    seen = set()
    obj_miss = 0
    byte_miss = 0
    measured = 0
    measured_bytes = 0
    for t, (k, sz) in enumerate(zip(keys, sizes)):
        res = cache.access(int(k), int(sz), t)
        first_touch = k not in seen
        seen.add(k)
        if not first_touch:
            measured += 1
            measured_bytes += int(sz)
            if not res.hit:
                obj_miss += 1
                byte_miss += int(sz)
    return obj_miss, byte_miss, measured, measured_bytes


def test_first_touch_exclusion_capacity_30():
    keys = [0, 1, 0, 1]
    sizes = [10, 20, 10, 20]
    obj_miss, byte_miss, measured, measured_bytes = _replay_exclude_first_touch(keys, sizes, 30)
    assert measured == 2
    assert measured_bytes == 30
    assert obj_miss == 0
    assert byte_miss == 0


def test_first_touch_exclusion_capacity_0():
    keys = [0, 1, 0, 1]
    sizes = [10, 20, 10, 20]
    obj_miss, byte_miss, measured, measured_bytes = _replay_exclude_first_touch(keys, sizes, 0)
    assert measured == 2
    assert measured_bytes == 30
    assert obj_miss == 2
    assert byte_miss == 30


def test_oversized_value_does_not_admit():
    cache = TrueLFUCache(capacity_bytes=8)
    res = cache.access(99, 100, 0)
    assert res.hit is False
    assert cache.num_resident() == 0
    assert cache.frequency(99) == 1


def test_simulator_full_capacity_zero_miss():
    keys = np.array([0, 1, 0, 1], dtype=np.int64)
    sizes = np.array([10, 20, 10, 20], dtype=np.int64)
    mrc = compute_true_lfu_mrc(
        keys=keys,
        sizes=sizes,
        capacity_points=4,
        workload="tiny",
        workload_file="tiny.csv",
    )
    assert mrc.measured_accesses == 2
    assert mrc.first_touch_accesses == 2
    assert mrc.unique_value_bytes_in_trace == 30
    assert mrc.capacity_bytes[-1] == 30
    assert mrc.object_miss_ratio[-1] == 0.0
    assert mrc.byte_miss_ratio[-1] == 0.0
    assert mrc.object_miss_ratio[0] == 1.0
    assert mrc.byte_miss_ratio[0] == 1.0


def test_no_cyclic_future_leakage_fixture():
    phase_shift = [0] * 30 + [1, 2] * 20
    keys = np.array(phase_shift, dtype=np.int64)
    sizes = np.array([10] * len(phase_shift), dtype=np.int64)

    lfu = compute_true_lfu_mrc(keys, sizes, capacity_points=4, workload="phase", workload_file="phase.csv")
    lru_mrc = lru.compute_mrc(keys, sizes, capacity_points=4, workload="phase", workload_file="phase.csv")

    idx = int(np.argmin(np.abs(lfu.capacity_bytes - 20)))
    # LFU keeps stale key 0 due high frequency from first phase; second phase repeats 1/2.
    assert lfu.object_miss_ratio[idx] > 0.0
    # This fixture exposes stale-frequency behavior where LRU is no worse.
    assert lfu.object_miss_ratio[idx] >= lru_mrc.object_miss_ratio[idx]


def test_all_unique_nan():
    keys = np.array([0, 1, 2, 3], dtype=np.int64)
    sizes = np.array([10, 10, 10, 10], dtype=np.int64)
    mrc = compute_true_lfu_mrc(keys, sizes, capacity_points=3, workload="u", workload_file="u.csv")
    assert mrc.measured_accesses == 0
    assert np.all(np.isnan(mrc.object_miss_ratio))
    assert np.all(np.isnan(mrc.byte_miss_ratio))
