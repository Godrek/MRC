"""Exact LRU MRC computation with configurable measurement modes."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    from numba import njit  # type: ignore

    _HAVE_NUMBA = True
except ImportError:  # pragma: no cover
    _HAVE_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore
        if len(args) == 1 and callable(args[0]):
            return args[0]

        def wrapper(fn):
            return fn

        return wrapper


@njit(cache=True)
def _bit_update(tree: np.ndarray, n: int, i: int, delta: int) -> None:
    while i <= n:
        tree[i] += delta
        i += i & -i


@njit(cache=True)
def _bit_prefix(tree: np.ndarray, i: int) -> int:
    s = 0
    while i > 0:
        s += tree[i]
        i -= i & -i
    return s


@njit(cache=True)
def _compute_required_bytes_cyclic(keys: np.ndarray, sizes: np.ndarray, max_key: int) -> np.ndarray:
    n = keys.shape[0]
    total_pos = 2 * n
    tree = np.zeros(total_pos + 2, dtype=np.int64)
    last_pos = np.full(max_key + 1, -1, dtype=np.int64)
    inf = np.iinfo(np.int64).max
    required = np.full(n, inf, dtype=np.int64)

    for j in range(total_pos):
        i = j % n
        k = keys[i]
        sz = sizes[i]
        p = last_pos[k]

        if p >= 0:
            if j >= p + 2:
                above = _bit_prefix(tree, j) - _bit_prefix(tree, p + 1)
            else:
                above = 0
            req = above + sz
            _bit_update(tree, total_pos, p + 1, -sz)
            if j >= n:
                required[i] = req

        _bit_update(tree, total_pos, j + 1, sz)
        last_pos[k] = j

    return required


@njit(cache=True)
def _compute_required_bytes_exclude_first_touch(
    keys: np.ndarray, sizes: np.ndarray, max_key: int
) -> tuple[np.ndarray, np.ndarray, int, int]:
    n = keys.shape[0]
    tree = np.zeros(n + 2, dtype=np.int64)
    last_pos = np.full(max_key + 1, -1, dtype=np.int64)

    required_tmp = np.empty(n, dtype=np.int64)
    measured_sizes_tmp = np.empty(n, dtype=np.int64)
    measured_count = 0
    measured_requested_bytes = np.int64(0)

    for i in range(n):
        k = keys[i]
        sz = sizes[i]
        p = last_pos[k]

        if p >= 0:
            if i >= p + 2:
                above = _bit_prefix(tree, i) - _bit_prefix(tree, p + 1)
            else:
                above = 0
            required_tmp[measured_count] = above + sz
            measured_sizes_tmp[measured_count] = sz
            measured_count += 1
            measured_requested_bytes += sz

            _bit_update(tree, n, p + 1, -sz)

        _bit_update(tree, n, i + 1, sz)
        last_pos[k] = i

    return (
        required_tmp[:measured_count].copy(),
        measured_sizes_tmp[:measured_count].copy(),
        int(measured_count),
        int(measured_requested_bytes),
    )


@dataclass
class TraceMRC:
    workload: str
    workload_file: str
    policy: str
    measurement_mode: str
    unique_objects_in_trace: int
    unique_value_bytes_in_trace: int
    total_accesses: int
    measured_accesses: int
    first_touch_accesses: int
    total_requested_bytes: int
    measured_requested_bytes: int
    capacity_fractions: np.ndarray
    capacity_bytes: np.ndarray
    object_miss_ratio: np.ndarray
    byte_miss_ratio: np.ndarray


def compute_lru_required_bytes_cyclic(keys: np.ndarray, sizes: np.ndarray) -> np.ndarray:
    keys = np.ascontiguousarray(keys, dtype=np.int64)
    sizes = np.ascontiguousarray(sizes, dtype=np.int64)
    if keys.shape != sizes.shape:
        raise ValueError("keys and sizes must have identical shape")
    if keys.size == 0:
        return np.empty(0, dtype=np.int64)
    max_key = int(keys.max())
    return _compute_required_bytes_cyclic(keys, sizes, max_key)


def compute_lru_required_bytes_exclude_first_touch(
    keys: np.ndarray, sizes: np.ndarray
) -> tuple[np.ndarray, np.ndarray, int, int, int]:
    keys = np.ascontiguousarray(keys, dtype=np.int64)
    sizes = np.ascontiguousarray(sizes, dtype=np.int64)
    if keys.shape != sizes.shape:
        raise ValueError("keys and sizes must have identical shape")
    if keys.size == 0:
        return (
            np.empty(0, dtype=np.int64),
            np.empty(0, dtype=np.int64),
            0,
            0,
            0,
        )
    max_key = int(keys.max())
    required, measured_sizes, measured, measured_bytes = _compute_required_bytes_exclude_first_touch(
        keys, sizes, max_key
    )
    return required, measured_sizes, measured, int(keys.size - measured), measured_bytes


def compute_required_bytes(keys: np.ndarray, sizes: np.ndarray) -> np.ndarray:
    """Legacy alias for warmed/cyclic required bytes."""
    return compute_lru_required_bytes_cyclic(keys, sizes)


def _capacity_grid(unique_bytes: int, points: int) -> tuple[np.ndarray, np.ndarray]:
    points = max(int(points), 2)
    fractions = np.linspace(0.0, 1.0, points)
    bytes_grid = np.rint(fractions * unique_bytes).astype(np.int64)
    if bytes_grid.size > 0:
        bytes_grid[-1] = int(unique_bytes)
    return fractions, bytes_grid


def compute_mrc(
    keys: np.ndarray,
    sizes: np.ndarray,
    capacity_points: int,
    workload: str,
    workload_file: str,
    measurement_mode: str = "exclude_first_touch",
) -> TraceMRC:
    keys = np.ascontiguousarray(keys, dtype=np.int64)
    sizes = np.ascontiguousarray(sizes, dtype=np.int64)
    if keys.size == 0:
        raise ValueError("empty trace")

    unique_keys, first_idx = np.unique(keys, return_index=True)
    unique_sizes = sizes[first_idx]
    unique_value_bytes = int(unique_sizes.sum())
    total_requested_bytes = int(sizes.sum())
    n_unique = int(unique_keys.size)
    total_accesses = int(keys.size)

    if measurement_mode == "exclude_first_touch":
        rb, measured_sizes, measured_accesses, first_touch_accesses, measured_requested_bytes = (
            compute_lru_required_bytes_exclude_first_touch(keys, sizes)
        )
    elif measurement_mode == "cyclic":
        rb = compute_lru_required_bytes_cyclic(keys, sizes)
        measured_sizes = sizes
        measured_accesses = int(keys.size)
        first_touch_accesses = 0
        measured_requested_bytes = total_requested_bytes
    else:
        raise ValueError(f"unknown measurement_mode: {measurement_mode}")

    fractions, bytes_grid = _capacity_grid(unique_value_bytes, capacity_points)

    if measured_accesses == 0:
        object_miss = np.full(fractions.size, np.nan, dtype=np.float64)
        byte_miss = np.full(fractions.size, np.nan, dtype=np.float64)
    else:
        order = np.argsort(rb, kind="stable")
        rb_sorted = rb[order]
        sz_sorted = measured_sizes[order]
        sz_cum = np.concatenate(([np.int64(0)], np.cumsum(sz_sorted, dtype=np.int64)))
        ks = np.searchsorted(rb_sorted, bytes_grid, side="right")
        misses = measured_accesses - ks
        bytes_hit = sz_cum[ks]
        bytes_miss = measured_requested_bytes - bytes_hit
        object_miss = misses.astype(np.float64) / float(measured_accesses)
        byte_miss = bytes_miss.astype(np.float64) / max(float(measured_requested_bytes), 1.0)

    policy = "lru"
    return TraceMRC(
        workload=workload,
        workload_file=workload_file,
        policy=policy,
        measurement_mode=measurement_mode,
        unique_objects_in_trace=n_unique,
        unique_value_bytes_in_trace=unique_value_bytes,
        total_accesses=total_accesses,
        measured_accesses=measured_accesses,
        first_touch_accesses=first_touch_accesses,
        total_requested_bytes=total_requested_bytes,
        measured_requested_bytes=measured_requested_bytes,
        capacity_fractions=fractions,
        capacity_bytes=bytes_grid,
        object_miss_ratio=object_miss,
        byte_miss_ratio=byte_miss,
    )


def _invert_one(cap_pts: np.ndarray, miss_pts: np.ndarray, target: float) -> float:
    if miss_pts.size == 0:
        return float("nan")
    finite_mask = np.isfinite(miss_pts)
    if not np.any(finite_mask):
        return float("nan")
    cap = cap_pts[finite_mask]
    miss = miss_pts[finite_mask]
    if miss[-1] > target + 1e-12:
        return float("nan")
    if miss[0] <= target:
        return float(cap[0])
    mask = miss <= target
    i = int(np.argmax(mask))
    m0 = float(miss[i - 1])
    m1 = float(miss[i])
    c0 = float(cap[i - 1])
    c1 = float(cap[i])
    if m0 == m1:
        return c1
    return c0 + (target - m0) * (c1 - c0) / (m1 - m0)


def compute_inverse_curve(
    mrc: TraceMRC,
    target_percent_grid: np.ndarray | None = None,
) -> dict:
    if target_percent_grid is None:
        target_percent_grid = np.arange(0, 101, 1, dtype=np.float64)
    targets = target_percent_grid / 100.0

    cap_frac = mrc.capacity_fractions
    cap_bytes = mrc.capacity_bytes
    obj_miss = mrc.object_miss_ratio
    byte_miss = mrc.byte_miss_ratio

    req_frac_obj = np.array([_invert_one(cap_frac, obj_miss, t) for t in targets])
    req_frac_byte = np.array([_invert_one(cap_frac, byte_miss, t) for t in targets])
    req_bytes_obj = np.array([_invert_one(cap_bytes, obj_miss, t) for t in targets])
    req_bytes_byte = np.array([_invert_one(cap_bytes, byte_miss, t) for t in targets])

    return {
        "target_miss_ratio_percent": target_percent_grid.astype(np.float64),
        "required_capacity_percent_of_unique_bytes_for_request_miss": req_frac_obj * 100.0,
        "required_capacity_percent_of_unique_bytes_for_byte_miss": req_frac_byte * 100.0,
        "required_capacity_bytes_for_request_miss": req_bytes_obj,
        "required_capacity_bytes_for_byte_miss": req_bytes_byte,
    }
