"""Exact warmed/cyclic LRU MRC computation.

Algorithm:
    Replay the trace twice; only measure the second pass. For every access we
    compute `required_bytes[i]` -- the minimum DRAM value-byte capacity needed
    for access i to hit under exact LRU. Curve derivation then sweeps across
    capacity points 0..unique_value_bytes.

The hot loop uses a Fenwick tree (BIT) over global replay positions storing
the active resident byte size of each key's most recent access. Time
complexity is O(N log N) for N = 2 * len(trace).
"""

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


# ---------------------------------------------------------------------------
# Fenwick tree primitives (1-indexed). Operate on a numpy int64 array.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Exact warmed/cyclic LRU stack-distance pass.
# ---------------------------------------------------------------------------

@njit(cache=True)
def _compute_required_bytes(
    keys: np.ndarray, sizes: np.ndarray, max_key: int
) -> np.ndarray:
    n = keys.shape[0]
    total_pos = 2 * n
    # Fenwick tree of size total_pos, 1-indexed -> +1 buffer
    tree = np.zeros(total_pos + 2, dtype=np.int64)
    last_pos = np.full(max_key + 1, -1, dtype=np.int64)
    INF = np.iinfo(np.int64).max
    required = np.full(n, INF, dtype=np.int64)

    for j in range(total_pos):
        i = j % n
        k = keys[i]
        sz = sizes[i]
        p = last_pos[k]

        if p >= 0:
            # Sum of active bytes at global positions (p+1 .. j-1) inclusive,
            # i.e. Fenwick 1-indexed range [p+2 .. j].
            if j >= p + 2:
                above = _bit_prefix(tree, j) - _bit_prefix(tree, p + 1)
            else:
                above = 0
            req = above + sz
            # Remove old position p (Fenwick index p+1)
            _bit_update(tree, total_pos, p + 1, -sz)
            if j >= n:
                required[i] = req

        # Add current position j (Fenwick index j+1) with size sz
        _bit_update(tree, total_pos, j + 1, sz)
        last_pos[k] = j

    return required


# ---------------------------------------------------------------------------
# Curve derivation
# ---------------------------------------------------------------------------

@dataclass
class TraceMRC:
    """Per-trace MRC results."""

    workload: str
    workload_file: str
    unique_objects_in_trace: int
    unique_value_bytes_in_trace: int
    total_requested_bytes: int
    capacity_fractions: np.ndarray  # shape (P,)
    capacity_bytes: np.ndarray      # shape (P,)
    object_miss_ratio: np.ndarray   # shape (P,)
    byte_miss_ratio: np.ndarray     # shape (P,)


def compute_required_bytes(keys: np.ndarray, sizes: np.ndarray) -> np.ndarray:
    """Return per-access required DRAM bytes under exact warmed/cyclic LRU."""
    keys = np.ascontiguousarray(keys, dtype=np.int64)
    sizes = np.ascontiguousarray(sizes, dtype=np.int64)
    if keys.shape != sizes.shape:
        raise ValueError("keys and sizes must have identical shape")
    if keys.size == 0:
        return np.empty(0, dtype=np.int64)
    max_key = int(keys.max())
    return _compute_required_bytes(keys, sizes, max_key)


def _capacity_grid(unique_bytes: int, points: int) -> tuple[np.ndarray, np.ndarray]:
    points = max(int(points), 2)
    fractions = np.linspace(0.0, 1.0, points)
    bytes_grid = np.rint(fractions * unique_bytes).astype(np.int64)
    # Make sure the last point exactly equals unique_bytes (sweeps to 100%)
    if bytes_grid.size > 0:
        bytes_grid[-1] = int(unique_bytes)
    return fractions, bytes_grid


def compute_mrc(
    keys: np.ndarray,
    sizes: np.ndarray,
    capacity_points: int,
    workload: str,
    workload_file: str,
) -> TraceMRC:
    """Compute the warmed/cyclic LRU forward MRC curves for a single trace."""
    keys = np.ascontiguousarray(keys, dtype=np.int64)
    sizes = np.ascontiguousarray(sizes, dtype=np.int64)
    if keys.size == 0:
        raise ValueError("empty trace")

    # unique_value_bytes: sum of value sizes across distinct keys.
    unique_keys, first_idx = np.unique(keys, return_index=True)
    unique_sizes = sizes[first_idx]
    unique_value_bytes = int(unique_sizes.sum())
    total_requested_bytes = int(sizes.sum())
    n_unique = int(unique_keys.size)

    rb = compute_required_bytes(keys, sizes)

    # Sort (rb, sizes) once for vectorized capacity sweep.
    order = np.argsort(rb, kind="stable")
    rb_sorted = rb[order]
    sz_sorted = sizes[order]
    sz_cum = np.concatenate(
        ([np.int64(0)], np.cumsum(sz_sorted, dtype=np.int64))
    )  # length N+1

    fractions, bytes_grid = _capacity_grid(unique_value_bytes, capacity_points)

    # For each capacity C, hits = number of accesses with rb <= C.
    ks = np.searchsorted(rb_sorted, bytes_grid, side="right")
    misses = rb.size - ks
    bytes_hit = sz_cum[ks]
    bytes_miss = total_requested_bytes - bytes_hit

    object_miss = misses.astype(np.float64) / float(rb.size)
    byte_miss = bytes_miss.astype(np.float64) / max(float(total_requested_bytes), 1.0)

    return TraceMRC(
        workload=workload,
        workload_file=workload_file,
        unique_objects_in_trace=n_unique,
        unique_value_bytes_in_trace=unique_value_bytes,
        total_requested_bytes=total_requested_bytes,
        capacity_fractions=fractions,
        capacity_bytes=bytes_grid,
        object_miss_ratio=object_miss,
        byte_miss_ratio=byte_miss,
    )


# ---------------------------------------------------------------------------
# Inverse curve
# ---------------------------------------------------------------------------

def _invert_one(
    cap_pts: np.ndarray, miss_pts: np.ndarray, target: float
) -> float:
    """Smallest cap_pts value such that miss_pts(cap) <= target.

    cap_pts is monotonically non-decreasing. miss_pts is monotonically
    non-increasing. Linear interpolation between adjacent points. NaN if
    target is unreachable.
    """
    if miss_pts.size == 0:
        return float("nan")
    if miss_pts[-1] > target + 1e-12:
        return float("nan")
    if miss_pts[0] <= target:
        return float(cap_pts[0])
    # First index where miss <= target.
    mask = miss_pts <= target
    i = int(np.argmax(mask))
    m0 = float(miss_pts[i - 1])
    m1 = float(miss_pts[i])
    c0 = float(cap_pts[i - 1])
    c1 = float(cap_pts[i])
    if m0 == m1:
        return c1
    return c0 + (target - m0) * (c1 - c0) / (m1 - m0)


def compute_inverse_curve(
    mrc: TraceMRC,
    target_percent_grid: np.ndarray | None = None,
) -> dict:
    """Invert a forward MRC into target-miss -> required-capacity.

    Returns a dict of arrays suitable for building a DataFrame row.
    """
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
