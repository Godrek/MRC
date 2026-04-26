"""End-to-end pipeline: traces -> LRU/LFU MRCs -> CSVs -> plots."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import lru, plot, simulate, traces
from .config import HarnessConfig


DEFAULT_MEASUREMENT_MODE = "exclude_first_touch"
FORWARD_CSV_NAME = f"lru_{DEFAULT_MEASUREMENT_MODE}_object_and_byte_mrc_curves.csv"
INVERSE_CSV_NAME = f"lru_{DEFAULT_MEASUREMENT_MODE}_inverse_mrc_curves.csv"


def _trace_path_to_workload(path: Path) -> str:
    return path.stem


def compute_lru_for_traces(
    trace_paths: list[Path],
    out_dir: Path,
    capacity_points: int,
    measurement_mode: str = DEFAULT_MEASUREMENT_MODE,
    progress: bool = True,
) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    forward_rows: list[dict] = []
    inverse_rows: list[dict] = []

    for path in trace_paths:
        workload = _trace_path_to_workload(path)
        df = traces.load_trace(path)
        keys = df["key"].to_numpy(dtype="int64", copy=False)
        sizes = df["value_size"].to_numpy(dtype="int64", copy=False)

        mrc = lru.compute_mrc(
            keys=keys,
            sizes=sizes,
            capacity_points=capacity_points,
            workload=workload,
            workload_file=str(path),
            measurement_mode=measurement_mode,
        )

        for i in range(mrc.capacity_fractions.size):
            forward_rows.append(
                {
                    "workload_file": mrc.workload_file,
                    "workload": mrc.workload,
                    "policy": f"lru_{measurement_mode}",
                    "measurement_mode": mrc.measurement_mode,
                    "capacity_fraction_of_unique_bytes": float(mrc.capacity_fractions[i]),
                    "capacity_bytes": int(mrc.capacity_bytes[i]),
                    "unique_objects_in_trace": int(mrc.unique_objects_in_trace),
                    "unique_value_bytes_in_trace": int(mrc.unique_value_bytes_in_trace),
                    "total_accesses": int(mrc.total_accesses),
                    "measured_accesses": int(mrc.measured_accesses),
                    "first_touch_accesses": int(mrc.first_touch_accesses),
                    "total_requested_bytes": int(mrc.total_requested_bytes),
                    "measured_requested_bytes": int(mrc.measured_requested_bytes),
                    "object_miss_ratio": float(mrc.object_miss_ratio[i]),
                    "byte_miss_ratio": float(mrc.byte_miss_ratio[i]),
                }
            )

        inv = lru.compute_inverse_curve(mrc)
        for i in range(inv["target_miss_ratio_percent"].size):
            inverse_rows.append(
                {
                    "workload": mrc.workload,
                    "policy": f"lru_{measurement_mode}",
                    "measurement_mode": mrc.measurement_mode,
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

    forward_df = pd.DataFrame(forward_rows)
    inverse_df = pd.DataFrame(inverse_rows)

    forward_csv = out_dir / f"lru_{measurement_mode}_object_and_byte_mrc_curves.csv"
    inverse_csv = out_dir / f"lru_{measurement_mode}_inverse_mrc_curves.csv"
    forward_df.to_csv(forward_csv, index=False)
    inverse_df.to_csv(inverse_csv, index=False)
    return forward_csv, inverse_csv


def run_all(
    cfg: HarnessConfig,
    out_dir: str | Path,
    policies: list[str] | None = None,
    measurement_mode: str = DEFAULT_MEASUREMENT_MODE,
    progress: bool = True,
) -> dict:
    out_dir = Path(out_dir)
    if not policies:
        policies = ["lru"]
    requested = set(policies)
    unknown = requested - {"lru", "true_lfu"}
    if unknown:
        raise ValueError(f"unknown policies: {sorted(unknown)}")

    traces_dir = out_dir / "traces"
    trace_paths = traces.generate_all_traces(cfg, traces_dir, progress=progress)

    result: dict = {"trace_paths": trace_paths}

    lru_forward_csv = lru_inverse_csv = None
    if "lru" in requested:
        lru_dir = out_dir / "lru"
        plots_dir = lru_dir / "plots"
        lru_forward_csv, lru_inverse_csv = compute_lru_for_traces(
            trace_paths,
            lru_dir,
            capacity_points=cfg.global_.capacity_points,
            measurement_mode=measurement_mode,
            progress=progress,
        )
        lru_plots = plot.plot_all(lru_forward_csv, lru_inverse_csv, plots_dir)
        result["lru_forward_csv"] = lru_forward_csv
        result["lru_inverse_csv"] = lru_inverse_csv
        result["lru_plots"] = lru_plots

    lfu_forward_csv = lfu_inverse_csv = None
    if "true_lfu" in requested:
        lfu_dir = out_dir / "lfu"
        plots_dir = lfu_dir / "plots"
        lfu_forward_csv, lfu_inverse_csv = simulate.simulate_true_lfu_for_traces(
            trace_paths,
            lfu_dir,
            capacity_points=cfg.global_.capacity_points,
            measurement_mode=measurement_mode,
            progress=progress,
        )
        lfu_plots = plot.plot_all(lfu_forward_csv, lfu_inverse_csv, plots_dir)
        plot.plot_policy_inverse_sheet(
            lfu_inverse_csv,
            plots_dir,
            sheet_name=f"true_lfu_{measurement_mode}_inverse_contact_sheet.png",
        )
        result["lfu_forward_csv"] = lfu_forward_csv
        result["lfu_inverse_csv"] = lfu_inverse_csv
        result["lfu_plots"] = lfu_plots

    if lru_forward_csv is not None and lfu_forward_csv is not None:
        compare_dir = out_dir / "compare"
        result["compare_plots"] = plot.plot_compare_policies(
            lru_csv=lru_forward_csv,
            lfu_csv=lfu_forward_csv,
            out_dir=compare_dir,
            lru_inverse_csv=lru_inverse_csv,
            lfu_inverse_csv=lfu_inverse_csv,
        )

    return result
