"""Unit tests for the first-touch-excluded LRU implementation."""

from __future__ import annotations

import math

import numpy as np

from valkey_tiering_mrc import lru


def test_first_touch_exclusion_capacity_30():
    keys = np.array([0, 1, 0, 1], dtype=np.int64)
    sizes = np.array([10, 20, 10, 20], dtype=np.int64)
    mrc = lru.compute_mrc(
        keys=keys,
        sizes=sizes,
        capacity_points=4,
        workload="tiny",
        workload_file="tiny.csv",
        measurement_mode="exclude_first_touch",
    )
    assert mrc.measured_accesses == 2
    assert mrc.first_touch_accesses == 2
    assert mrc.capacity_bytes[-1] == 30
    assert mrc.object_miss_ratio[-1] == 0.0
    assert mrc.byte_miss_ratio[-1] == 0.0


def test_first_touch_exclusion_capacity_0():
    keys = np.array([0, 1, 0, 1], dtype=np.int64)
    sizes = np.array([10, 20, 10, 20], dtype=np.int64)
    mrc = lru.compute_mrc(
        keys=keys,
        sizes=sizes,
        capacity_points=2,
        workload="tiny",
        workload_file="tiny.csv",
        measurement_mode="exclude_first_touch",
    )
    assert mrc.capacity_bytes[0] == 0
    assert mrc.measured_accesses == 2
    assert mrc.object_miss_ratio[0] == 1.0
    assert mrc.byte_miss_ratio[0] == 1.0


def test_required_bytes_two_keys_alternating_exclude_first_touch():
    keys = np.array([0, 1, 0, 1], dtype=np.int64)
    sizes = np.array([10, 20, 10, 20], dtype=np.int64)
    rb, measured_sizes, measured, first_touches, measured_bytes = (
        lru.compute_lru_required_bytes_exclude_first_touch(keys, sizes)
    )
    assert measured == 2
    assert first_touches == 2
    assert measured_sizes.tolist() == [10, 20]
    assert measured_bytes == 30
    assert rb.tolist() == [30, 30]


def test_all_unique_has_nan_miss_ratios():
    keys = np.array([0, 1, 2, 3], dtype=np.int64)
    sizes = np.array([10, 20, 30, 40], dtype=np.int64)
    mrc = lru.compute_mrc(
        keys=keys,
        sizes=sizes,
        capacity_points=5,
        workload="unique",
        workload_file="unique.csv",
    )
    assert mrc.measured_accesses == 0
    assert np.all(np.isnan(mrc.object_miss_ratio))
    assert np.all(np.isnan(mrc.byte_miss_ratio))

    inv = lru.compute_inverse_curve(mrc)
    assert math.isnan(inv["required_capacity_bytes_for_request_miss"][0])


def test_inverse_curve_shapes():
    keys = np.array([0, 1, 0, 1], dtype=np.int64)
    sizes = np.array([10, 20, 10, 20], dtype=np.int64)
    mrc = lru.compute_mrc(keys, sizes, capacity_points=11, workload="tiny", workload_file="tiny.csv")
    inv = lru.compute_inverse_curve(mrc)
    assert inv["target_miss_ratio_percent"].size == 101
    assert inv["required_capacity_bytes_for_request_miss"][0] == 30
    assert inv["required_capacity_bytes_for_byte_miss"][0] == 30
