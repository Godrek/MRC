"""End-to-end pipeline: traces -> LRU MRCs -> CSVs -> plots."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import lru, plot, traces
from .config import HarnessConfig


FORWARD_CSV_NAME = "lru_warmed_object_and_byte_mrc_curves.csv"
INVERSE_CSV_NAME = "lru_warmed_inverse_mrc_curves.csv"

POLICY_LABEL = "lru_warmed_cyclic"


def _trace_path_to_workload(path: Path) -> str:
    return path.stem


def compute_lru_for_traces(
    trace_paths: list[Path],
    out_dir: Path,
    capacity_points: int,
    progress: bool = True,
) -> tuple[Path, Path]:
    """Compute warmed/cyclic LRU MRCs and inverse curves for a set of traces.

    Writes two CSVs to out_dir and returns their paths.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    forward_rows: list[dict] = []
    inverse_rows: list[dict] = []

    for path in trace_paths:
        workload = _trace_path_to_workload(path)
        if progress:
            print(f"  [{workload}] loading {path}")
        df = traces.load_trace(path)
        keys = df["key"].to_numpy(dtype="int64", copy=False)
        sizes = df["value_size"].to_numpy(dtype="int64", copy=False)

        if progress:
            print(
                f"  [{workload}] computing exact warmed/cyclic LRU "
                f"(events={len(df)}, capacity_points={capacity_points})"
            )
        mrc = lru.compute_mrc(
            keys=keys,
            sizes=sizes,
            capacity_points=capacity_points,
            workload=workload,
            workload_file=str(path),
        )

        for i in range(mrc.capacity_fractions.size):
            forward_rows.append(
                {
                    "workload_file": mrc.workload_file,
                    "workload": mrc.workload,
                    "policy": POLICY_LABEL,
                    "capacity_fraction_of_unique_bytes": float(mrc.capacity_fractions[i]),
                    "capacity_bytes": int(mrc.capacity_bytes[i]),
                    "unique_objects_in_trace": int(mrc.unique_objects_in_trace),
                    "unique_value_bytes_in_trace": int(mrc.unique_value_bytes_in_trace),
                    "total_requested_bytes": int(mrc.total_requested_bytes),
                    "object_miss_ratio": float(mrc.object_miss_ratio[i]),
                    "byte_miss_ratio": float(mrc.byte_miss_ratio[i]),
                }
            )

        inv = lru.compute_inverse_curve(mrc)
        for i in range(inv["target_miss_ratio_percent"].size):
            inverse_rows.append(
                {
                    "workload": mrc.workload,
                    "policy": POLICY_LABEL,
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

        if progress:
            print(
                f"  [{workload}] unique_objects={mrc.unique_objects_in_trace} "
                f"unique_bytes={mrc.unique_value_bytes_in_trace} "
                f"miss@100%={mrc.object_miss_ratio[-1]:.4f}"
            )

    forward_df = pd.DataFrame(forward_rows)
    inverse_df = pd.DataFrame(inverse_rows)

    forward_csv = out_dir / FORWARD_CSV_NAME
    inverse_csv = out_dir / INVERSE_CSV_NAME
    forward_df.to_csv(forward_csv, index=False)
    inverse_df.to_csv(inverse_csv, index=False)
    if progress:
        print(f"Wrote {forward_csv}")
        print(f"Wrote {inverse_csv}")
    return forward_csv, inverse_csv


def run_all(
    cfg: HarnessConfig,
    out_dir: str | Path,
    progress: bool = True,
) -> dict:
    """Run the full pipeline: generate traces, compute MRCs, and plot."""
    out_dir = Path(out_dir)
    traces_dir = out_dir / "traces"
    results_dir = out_dir / "lru"
    plots_dir = results_dir / "plots"

    if progress:
        print(f"==> generate-traces -> {traces_dir}")
    trace_paths = traces.generate_all_traces(cfg, traces_dir, progress=progress)

    if progress:
        print(f"==> compute-lru -> {results_dir}")
    forward_csv, inverse_csv = compute_lru_for_traces(
        trace_paths,
        results_dir,
        capacity_points=cfg.global_.capacity_points,
        progress=progress,
    )

    if progress:
        print(f"==> plot -> {plots_dir}")
    plots = plot.plot_all(forward_csv, inverse_csv, plots_dir)
    return {
        "trace_paths": trace_paths,
        "forward_csv": forward_csv,
        "inverse_csv": inverse_csv,
        "plots": plots,
    }
