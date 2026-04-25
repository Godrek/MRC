"""Unit tests for the true-LFU policy and its capacity-sweep simulator."""

from __future__ import annotations

import numpy as np

from valkey_tiering_mrc.policies import TrueLFUCache
from valkey_tiering_mrc.simulate import compute_true_lfu_mrc


# ---------------------------------------------------------------------------
# TrueLFUCache reference behavior
# ---------------------------------------------------------------------------

def _replay_warmed_cyclic(keys, sizes, capacity_bytes):
    """Two-pass replay; return measured (object_miss, byte_miss, n, byte_total)."""
    cache = TrueLFUCache(capacity_bytes)
    n = len(keys)
    obj_miss = 0
    byte_miss = 0
    byte_total = 0
    for j in range(2 * n):
        i = j % n
        res = cache.access(int(keys[i]), int(sizes[i]), j)
        if j >= n:
            byte_total += int(sizes[i])
            if not res.hit:
                obj_miss += 1
                byte_miss += int(sizes[i])
    return obj_miss, byte_miss, n, byte_total


def test_full_capacity_zero_miss():
    keys = [0, 1, 0, 1]
    sizes = [10, 20, 10, 20]
    obj_miss, byte_miss, n, byte_total = _replay_warmed_cyclic(keys, sizes, 30)
    assert obj_miss == 0
    assert byte_miss == 0
    assert n == 4
    assert byte_total == 60


def test_capacity_zero_all_miss():
    keys = [0, 1, 0, 1, 2]
    sizes = [10, 20, 10, 20, 5]
    obj_miss, byte_miss, n, byte_total = _replay_warmed_cyclic(keys, sizes, 0)
    assert obj_miss == n
    assert byte_miss == byte_total
    # Even with no DRAM, the global frequency counter must still increment.
    cache = TrueLFUCache(0)
    cache.access(7, 4, 0)
    cache.access(7, 4, 1)
    assert cache.frequency(7) == 2
    assert cache.num_resident() == 0


def test_evicts_lower_frequency_under_pressure():
    """Capacity for one value: frequent key 0 must beat one-off key 1."""
    cache = TrueLFUCache(capacity_bytes=10)
    cache.access(0, 10, 0)  # admit 0
    cache.access(0, 10, 1)  # freq[0]=2
    cache.access(0, 10, 2)  # freq[0]=3
    cache.access(1, 10, 3)  # admit 1, evict who? (0 freq=3, 1 freq=1) -> evict 1
    assert cache.is_resident(0)
    assert not cache.is_resident(1)
    assert cache.frequency(0) == 3
    assert cache.frequency(1) == 1


def test_lru_tiebreak_among_equal_frequency():
    """Tied frequencies must evict the least-recently-used."""
    # Make three keys size=10 each, capacity=20 (room for two).
    cache = TrueLFUCache(capacity_bytes=20)
    cache.access(0, 10, 0)  # resident: {0}
    cache.access(1, 10, 1)  # resident: {0,1}
    # Now both have freq=1. Touch 0 to make 1 the LRU at freq=1.
    cache.access(0, 10, 2)  # freq[0]=2, freq[1]=1, last_access[0]=2
    cache.access(1, 10, 3)  # freq[1]=2, last_access[1]=3
    # Both freq=2 now. last_access: 0 -> 2, 1 -> 3 (1 is more recent).
    cache.access(2, 10, 4)  # admit 2 (freq becomes 1), forces eviction.
    # Tied with key 2? No: freq[2]=1, freq[0]=2, freq[1]=2 -- 2 is the lowest, evict it!
    # That confirms a frequent key survives. To test LRU tie-break specifically:
    cache2 = TrueLFUCache(capacity_bytes=20)
    cache2.access(0, 10, 0)  # freq[0]=1
    cache2.access(1, 10, 1)  # freq[1]=1
    cache2.access(0, 10, 2)  # freq[0]=2, last_access=2
    cache2.access(1, 10, 3)  # freq[1]=2, last_access=3
    # Both resident with freq=2; key 0 is LRU among the tie.
    cache2.access(2, 10, 4)  # admit 2; freq[2]=1 -> 2 is the lowest freq, gets evicted
    assert cache2.is_resident(0) and cache2.is_resident(1)

    # Now genuinely test LRU tie-break by warming key 2 first.
    cache3 = TrueLFUCache(capacity_bytes=20)
    cache3.access(0, 10, 0)
    cache3.access(0, 10, 1)  # freq[0]=2
    cache3.access(1, 10, 2)
    cache3.access(1, 10, 3)  # freq[1]=2
    # Both have freq=2. last_access: 0->1, 1->3. So 0 is LRU among tie.
    # Touch a phantom by re-touching and admitting a third key with equal freq.
    cache3.access(2, 10, 4)
    cache3.access(2, 10, 5)  # freq[2]=2; admit forces eviction.
    # Three keys all freq=2. last_access: 0->1, 1->3, 2->5. LRU among tied is 0.
    assert not cache3.is_resident(0)
    assert cache3.is_resident(1)
    assert cache3.is_resident(2)


def test_oversized_value_does_not_admit():
    cache = TrueLFUCache(capacity_bytes=8)
    res = cache.access(99, 100, 0)  # value too big to fit
    assert res.hit is False
    assert cache.num_resident() == 0
    assert cache.frequency(99) == 1


# ---------------------------------------------------------------------------
# Capacity-sweep simulator (numba kernel)
# ---------------------------------------------------------------------------

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
    assert mrc.unique_value_bytes_in_trace == 30
    assert mrc.capacity_bytes[-1] == 30
    assert mrc.object_miss_ratio[-1] == 0.0
    assert mrc.byte_miss_ratio[-1] == 0.0
    # Capacity 0 -> everything misses.
    assert mrc.object_miss_ratio[0] == 1.0
    assert mrc.byte_miss_ratio[0] == 1.0


def test_simulator_lfu_helps_on_hot_key_plus_scan():
    """LFU should keep a very hot key resident through a scan that LRU would evict."""
    # 10 hot accesses to key 0, then a scan over keys 1..5, then another hot access to 0.
    # Capacity for two values of size 10. LRU would have evicted key 0 by the
    # time the scan finishes; LFU keeps key 0 because freq[0]>>freq[1..5].
    pattern = (
        [0] * 10
        + [1, 2, 3, 4, 5]
        + [0]
    )
    sizes_per_key = {0: 10, 1: 10, 2: 10, 3: 10, 4: 10, 5: 10}
    keys = np.array(pattern, dtype=np.int64)
    sizes = np.array([sizes_per_key[k] for k in pattern], dtype=np.int64)

    # Capacity = 20 bytes (room for two values).
    mrc = compute_true_lfu_mrc(
        keys=keys, sizes=sizes,
        capacity_points=11, workload="hot+scan", workload_file="hot+scan.csv",
    )
    # Find the entry for capacity_bytes == 20.
    idx = int(np.argmin(np.abs(mrc.capacity_bytes - 20)))
    # Sanity: at this capacity we should not be missing every access.
    assert mrc.object_miss_ratio[idx] < 1.0
    # And at full capacity (60), zero miss is required.
    assert mrc.object_miss_ratio[-1] == 0.0
    assert mrc.byte_miss_ratio[-1] == 0.0
