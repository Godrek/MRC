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
    cfg = apply_overrides(cfg, events=1_000, keyspace=1_000, seed=11, capacity_points=51)
    result = run_all(cfg, tmp_path / "smoke", policies=["lru"], progress=False)

    forward_csv = result["lru_forward_csv"]
    inverse_csv = result["lru_inverse_csv"]

    assert forward_csv.exists()
    assert inverse_csv.exists()
    assert forward_csv.name == FORWARD_CSV_NAME
    assert inverse_csv.name == INVERSE_CSV_NAME

    fwd = pd.read_csv(forward_csv)
    inv = pd.read_csv(inverse_csv)
    assert set(fwd["measurement_mode"]) == {"exclude_first_touch"}
    assert set(inv["measurement_mode"]) == {"exclude_first_touch"}

    for wl, sub in fwd.groupby("workload"):
        sub = sub.sort_values("capacity_fraction_of_unique_bytes")
        last = sub.iloc[-1]
        if int(last["measured_accesses"]) > 0:
            assert last["object_miss_ratio"] == 0.0, wl
            assert last["byte_miss_ratio"] == 0.0, wl


def test_run_all_lru_and_true_lfu_smoke(tmp_path: Path):
    cfg = load_config(_config_path())
    cfg = apply_overrides(cfg, events=500, keyspace=500, seed=13, capacity_points=21)
    result = run_all(
        cfg,
        tmp_path / "both",
        policies=["lru", "true_lfu"],
        measurement_mode="exclude_first_touch",
        progress=False,
    )

    lfu_fwd = result["lfu_forward_csv"]
    lfu_inv = result["lfu_inverse_csv"]
    assert lfu_fwd.exists()
    assert lfu_inv.exists()
    assert lfu_fwd.name == "true_lfu_exclude_first_touch_object_and_byte_mrc_curves.csv"
    assert lfu_inv.name == "true_lfu_exclude_first_touch_inverse_mrc_curves.csv"

    inverse_sheet_named = lfu_fwd.parent / "plots" / "true_lfu_exclude_first_touch_inverse_contact_sheet.png"
    assert inverse_sheet_named.exists()

    lfu_df = pd.read_csv(lfu_fwd)
    assert set(lfu_df["measurement_mode"]) == {"exclude_first_touch"}
    for wl, sub in lfu_df.groupby("workload"):
        sub = sub.sort_values("capacity_fraction_of_unique_bytes")
        last = sub.iloc[-1]
        if int(last["measured_accesses"]) > 0:
            assert last["object_miss_ratio"] == 0.0, wl
            assert last["byte_miss_ratio"] == 0.0, wl
