"""Smoke test for the run-all pipeline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from valkey_tiering_mrc.config import apply_overrides, load_config
from valkey_tiering_mrc.pipeline import (
    FORWARD_CSV_NAME,
    INVERSE_CSV_NAME,
    run_all,
)


def _config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "examples" / "default_config.yaml"


def test_run_all_smoke(tmp_path: Path):
    cfg = load_config(_config_path())
    cfg = apply_overrides(cfg, events=1_000, keyspace=1_000, seed=11, capacity_points=101)
    result = run_all(cfg, tmp_path / "smoke", progress=False)

    forward_csv = result["forward_csv"]
    inverse_csv = result["inverse_csv"]
    plots = result["plots"]

    assert forward_csv.exists()
    assert inverse_csv.exists()
    assert forward_csv.name == FORWARD_CSV_NAME
    assert inverse_csv.name == INVERSE_CSV_NAME
    assert plots["forward_sheet"].exists()
    assert plots["inverse_sheet"].exists()
    assert len(plots["forward_plots"]) == len(cfg.enabled_workloads)
    assert len(plots["inverse_plots"]) == len(cfg.enabled_workloads)

    fwd = pd.read_csv(forward_csv)
    inv = pd.read_csv(inverse_csv)
    expected_workloads = set(cfg.enabled_workloads)

    assert set(fwd["workload"]) == expected_workloads
    assert set(inv["workload"]) == expected_workloads

    # At 100% capacity (last row per workload by capacity), miss must be 0 for
    # both object miss and byte miss under warmed/cyclic LRU.
    for wl, sub in fwd.groupby("workload"):
        sub = sub.sort_values("capacity_fraction_of_unique_bytes")
        last = sub.iloc[-1]
        assert last["capacity_fraction_of_unique_bytes"] == 1.0, wl
        assert last["object_miss_ratio"] == 0.0, wl
        assert last["byte_miss_ratio"] == 0.0, wl

    # Inverse: target=0% must map to 100% capacity (or close to it).
    for wl, sub in inv.groupby("workload"):
        zero = sub[sub["target_miss_ratio_percent"] == 0.0].iloc[0]
        assert zero["required_capacity_percent_of_unique_bytes_for_request_miss"] >= 99.0, wl
        assert zero["required_capacity_percent_of_unique_bytes_for_byte_miss"] >= 99.0, wl
