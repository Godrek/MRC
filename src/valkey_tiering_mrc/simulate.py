"""Per-capacity policy simulation (LFU and other replay-based policies).

Unlike LRU, true LFU cannot be derived from a single stack-distance pass --
each capacity point requires its own full replay because the eviction
choice depends on the live resident set under that capacity. This module
runs warmed/cyclic replays with a numba-jitted kernel and emits the same
CSV schema as the LRU pipeline.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

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

from . import lru, traces


TRUE_LFU_POLICY_LABEL = "true_lfu_global_frequency_lru_tiebreak_warmed_cyclic"


# ---------------------------------------------------------------------------
# Numba kernel: simulate one capacity point of warmed/cyclic true LFU.
#
# The eviction picker is an O(resident_count) linear scan -- intentional
# for experiment correctness over production performance.
# ---------------------------------------------------------------------------

@njit(cache=True)
def _simulate_true_lfu_one_capacity(
    dense_keys: np.ndarray,
    key_size: np.ndarray,
    capacity_bytes: int,
    n_unique: int,
    n: int,
) -> tuple[int, int]:
    """Return (object_misses_in_2nd_pass, byte_misses_in_2nd_pass)."""
    freq = np.zeros(n_unique, dtype=np.int64)
    last_access = np.full(n_unique, -1, dtype=np.int64)
    is_resident = np.zeros(n_unique, dtype=np.uint8)
    position = np.full(n_unique, -1, dtype=np.int64)  # idx in resident_indices
    resident_indices = np.empty(n_unique, dtype=np.int64)
    n_resident = 0
    resident_bytes = np.int64(0)

    obj_miss = np.int64(0)
    byte_miss = np.int64(0)

    total_pos = 2 * n
    for j in range(total_pos):
        i = j % n
        k = dense_keys[i]
        sz = key_size[k]

        # Increment global frequency before any eviction decision.
        freq[k] += 1
        last_access[k] = j

        measured = j >= n

        if is_resident[k] == 1:
            # Hit: nothing else to do.
            continue

        # Miss.
        if measured:
            obj_miss += 1
            byte_miss += sz

        # Cannot remain resident if it doesn't fit even alone.
        if capacity_bytes <= 0 or sz > capacity_bytes:
            continue

        # Admit.
        is_resident[k] = 1
        position[k] = n_resident
        resident_indices[n_resident] = k
        n_resident += 1
        resident_bytes += sz

        # Evict while over capacity. O(resident_count) scan per eviction.
        while resident_bytes > capacity_bytes:
            best = -1
            best_f = np.int64(0)
            best_la = np.int64(0)
            for r in range(n_resident):
                rk = resident_indices[r]
                rf = freq[rk]
                rla = last_access[rk]
                if best < 0 or rf < best_f or (rf == best_f and rla < best_la):
                    best = rk
                    best_f = rf
                    best_la = rla
            # Swap-pop best from resident_indices.
            pos = position[best]
            last_idx = n_resident - 1
            if pos != last_idx:
                swap_key = resident_indices[last_idx]
                resident_indices[pos] = swap_key
                position[swap_key] = pos
            position[best] = -1
            is_resident[best] = 0
            n_resident -= 1
            resident_bytes -= key_size[best]

    return int(obj_miss), int(byte_miss)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_true_lfu_mrc(
    keys: np.ndarray,
    sizes: np.ndarray,
    capacity_points: int,
    workload: str,
    workload_file: str,
    progress: bool = False,
) -> lru.TraceMRC:
    """Compute the warmed/cyclic true-LFU forward MRC for a single trace."""
    keys = np.ascontiguousarray(keys, dtype=np.int64)
    sizes = np.ascontiguousarray(sizes, dtype=np.int64)
    if keys.size == 0:
        raise ValueError("empty trace")
    n = int(keys.size)

    # Dense-encode keys into [0, n_unique).
    unique_keys, first_idx, inverse = np.unique(
        keys, return_index=True, return_inverse=True
    )
    n_unique = int(unique_keys.size)
    key_size = np.ascontiguousarray(sizes[first_idx], dtype=np.int64)
    dense_keys = np.ascontiguousarray(inverse, dtype=np.int64)

    unique_value_bytes = int(key_size.sum())
    total_requested_bytes = int(sizes.sum())

    fractions, bytes_grid = lru._capacity_grid(unique_value_bytes, capacity_points)

    obj_miss_arr = np.empty(fractions.size, dtype=np.float64)
    byte_miss_arr = np.empty(fractions.size, dtype=np.float64)

    progress_step = max(1, fractions.size // 10)
    for idx, cap in enumerate(bytes_grid):
        if progress and (idx == 0 or (idx + 1) % progress_step == 0 or idx == fractions.size - 1):
            print(
                f"    [{workload}] LFU capacity {idx + 1}/{fractions.size} "
                f"(cap_bytes={int(cap)})"
            )
        om, bm = _simulate_true_lfu_one_capacity(
            dense_keys, key_size, int(cap), n_unique, n
        )
        obj_miss_arr[idx] = om / n
        byte_miss_arr[idx] = bm / max(total_requested_bytes, 1)

    return lru.TraceMRC(
        workload=workload,
        workload_file=workload_file,
        unique_objects_in_trace=n_unique,
        unique_value_bytes_in_trace=unique_value_bytes,
        total_requested_bytes=total_requested_bytes,
        capacity_fractions=fractions,
        capacity_bytes=bytes_grid,
        object_miss_ratio=obj_miss_arr,
        byte_miss_ratio=byte_miss_arr,
    )


def _mrc_to_forward_rows(mrc: lru.TraceMRC, policy_label: str) -> list[dict]:
    rows = []
    for i in range(mrc.capacity_fractions.size):
        rows.append(
            {
                "workload_file": mrc.workload_file,
                "workload": mrc.workload,
                "policy": policy_label,
                "capacity_fraction_of_unique_bytes": float(mrc.capacity_fractions[i]),
                "capacity_bytes": int(mrc.capacity_bytes[i]),
                "unique_objects_in_trace": int(mrc.unique_objects_in_trace),
                "unique_value_bytes_in_trace": int(mrc.unique_value_bytes_in_trace),
                "total_requested_bytes": int(mrc.total_requested_bytes),
                "object_miss_ratio": float(mrc.object_miss_ratio[i]),
                "byte_miss_ratio": float(mrc.byte_miss_ratio[i]),
            }
        )
    return rows


def _mrc_to_inverse_rows(mrc: lru.TraceMRC, policy_label: str) -> list[dict]:
    inv = lru.compute_inverse_curve(mrc)
    rows = []
    for i in range(inv["target_miss_ratio_percent"].size):
        rows.append(
            {
                "workload": mrc.workload,
                "policy": policy_label,
                "target_miss_ratio_percent": float(inv["target_miss_ratio_percent"][i]),
                "required_capacity_percent_of_unique_bytes_for_request_miss": float(
                    inv["required_capacity_percent_of_unique_bytes_for_request_miss"][i]
                ),
                "required_capacity_percent_of_unique_bytes_for_byte_miss": float(
                    inv["required_capacity_percent_of_unique_bytes_for_byte_miss"][i]
                ),
                "required_capacity_bytes_for_request_miss": float(
                    inv["required_capacity_bytes_for_request_miss"][i]
                ),
                "required_capacity_bytes_for_byte_miss": float(
                    inv["required_capacity_bytes_for_byte_miss"][i]
                ),
                "unique_value_bytes_in_trace": int(mrc.unique_value_bytes_in_trace),
            }
        )
    return rows


def simulate_policy_mrc_for_trace(
    trace_path: Path,
    policy_name: str,
    capacity_points: int = 1001,
    progress: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate a policy on a single trace and return (forward_df, inverse_df).

    Both DataFrames use the same column schemas as the LRU pipeline.
    """
    if policy_name != "true_lfu":
        raise ValueError(f"unsupported policy: {policy_name}")
    trace_path = Path(trace_path)
    df = traces.load_trace(trace_path)
    keys = df["key"].to_numpy(dtype="int64", copy=False)
    sizes = df["value_size"].to_numpy(dtype="int64", copy=False)

    workload = trace_path.stem
    mrc = compute_true_lfu_mrc(
        keys=keys,
        sizes=sizes,
        capacity_points=capacity_points,
        workload=workload,
        workload_file=str(trace_path),
        progress=progress,
    )

    forward = pd.DataFrame(_mrc_to_forward_rows(mrc, TRUE_LFU_POLICY_LABEL))
    inverse = pd.DataFrame(_mrc_to_inverse_rows(mrc, TRUE_LFU_POLICY_LABEL))
    return forward, inverse


def simulate_true_lfu_for_traces(
    trace_paths: list[Path],
    out_dir: Path,
    capacity_points: int = 1001,
    progress: bool = True,
) -> tuple[Path, Path]:
    """Compute true-LFU MRCs for several traces and write the two CSVs.

    Returns the paths of the forward and inverse CSVs.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fwd_rows: list[dict] = []
    inv_rows: list[dict] = []

    for path in trace_paths:
        if progress:
            print(f"  [{path.stem}] simulating true LFU on {path}")
        fwd, inv = simulate_policy_mrc_for_trace(
            path, "true_lfu", capacity_points=capacity_points, progress=progress
        )
        fwd_rows.extend(fwd.to_dict("records"))
        inv_rows.extend(inv.to_dict("records"))
        last_obj = float(fwd["object_miss_ratio"].iloc[-1])
        last_byte = float(fwd["byte_miss_ratio"].iloc[-1])
        if progress:
            print(
                f"  [{path.stem}] LFU miss@100% object={last_obj:.4f} "
                f"byte={last_byte:.4f}"
            )

    fwd_df = pd.DataFrame(fwd_rows)
    inv_df = pd.DataFrame(inv_rows)

    fwd_csv = out_dir / "true_lfu_warmed_object_and_byte_mrc_curves.csv"
    inv_csv = out_dir / "true_lfu_warmed_inverse_mrc_curves.csv"
    fwd_df.to_csv(fwd_csv, index=False)
    inv_df.to_csv(inv_csv, index=False)
    if progress:
        print(f"Wrote {fwd_csv}")
        print(f"Wrote {inv_csv}")
    return fwd_csv, inv_csv
