"""Smoke tests for the run-all pipeline (LRU only and LRU+true-LFU)."""

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


def test_run_all_lru_smoke(tmp_path: Path):
    cfg = load_config(_config_path())
    cfg = apply_overrides(cfg, events=1_000, keyspace=1_000, seed=11, capacity_points=101)
    result = run_all(cfg, tmp_path / "smoke", policies=["lru"], progress=False)

    forward_csv = result["lru_forward_csv"]
    inverse_csv = result["lru_inverse_csv"]
    plots = result["lru_plots"]

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

    for wl, sub in fwd.groupby("workload"):
        sub = sub.sort_values("capacity_fraction_of_unique_bytes")
        last = sub.iloc[-1]
        assert last["capacity_fraction_of_unique_bytes"] == 1.0, wl
        assert last["object_miss_ratio"] == 0.0, wl
        assert last["byte_miss_ratio"] == 0.0, wl

    for wl, sub in inv.groupby("workload"):
        zero = sub[sub["target_miss_ratio_percent"] == 0.0].iloc[0]
        assert zero["required_capacity_percent_of_unique_bytes_for_request_miss"] >= 99.0, wl
        assert zero["required_capacity_percent_of_unique_bytes_for_byte_miss"] >= 99.0, wl


def test_run_all_lru_and_true_lfu_smoke(tmp_path: Path):
    cfg = load_config(_config_path())
    # Keep this small -- LFU does a full replay per capacity point.
    cfg = apply_overrides(cfg, events=500, keyspace=500, seed=13, capacity_points=21)
    result = run_all(
        cfg, tmp_path / "both",
        policies=["lru", "true_lfu"], progress=False,
    )

    # LRU outputs.
    assert result["lru_forward_csv"].exists()
    assert result["lru_inverse_csv"].exists()

    # LFU outputs.
    lfu_fwd = result["lfu_forward_csv"]
    lfu_inv = result["lfu_inverse_csv"]
    assert lfu_fwd.exists()
    assert lfu_inv.exists()
    assert lfu_fwd.name == "true_lfu_warmed_object_and_byte_mrc_curves.csv"
    assert lfu_inv.name == "true_lfu_warmed_inverse_mrc_curves.csv"

    # LFU per-workload plots and dedicated inverse sheet.
    lfu_plots = result["lfu_plots"]
    assert lfu_plots["forward_sheet"].exists()
    assert lfu_plots["inverse_sheet"].exists()
    inverse_sheet_named = lfu_fwd.parent / "plots" / "true_lfu_warmed_inverse_contact_sheet.png"
    assert inverse_sheet_named.exists()

    # Comparison plots and contact sheets.
    cmp = result["compare_plots"]
    assert cmp["object_sheet"].exists()
    assert cmp["byte_sheet"].exists()
    assert cmp["combined_sheet"].exists()
    assert cmp["inverse_object_sheet"].exists()
    assert cmp["inverse_byte_sheet"].exists()

    lfu_df = pd.read_csv(lfu_fwd)
    expected = set(cfg.enabled_workloads)
    assert set(lfu_df["workload"]) == expected
    # Warmed/cyclic invariant for LFU as well.
    for wl, sub in lfu_df.groupby("workload"):
        sub = sub.sort_values("capacity_fraction_of_unique_bytes")
        last = sub.iloc[-1]
        assert last["capacity_fraction_of_unique_bytes"] == 1.0, wl
        assert last["object_miss_ratio"] == 0.0, wl
        assert last["byte_miss_ratio"] == 0.0, wl
