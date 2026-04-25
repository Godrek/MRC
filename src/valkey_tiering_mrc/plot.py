"""Plotting utilities: per-workload MRC charts and contact sheets."""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # non-interactive backend for headless runs
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from PIL import Image  # noqa: E402


def _set_full_axes(ax) -> None:
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.grid(True, linestyle="--", alpha=0.4)


def plot_forward_mrc(
    df: pd.DataFrame, workload: str, out_path: Path
) -> Path:
    """Plot forward MRC for a single workload (object miss + byte miss vs capacity)."""
    sub = df[df["workload"] == workload].sort_values("capacity_fraction_of_unique_bytes")
    fig, ax = plt.subplots(figsize=(6, 4.5), dpi=120)
    cap_pct = sub["capacity_fraction_of_unique_bytes"].to_numpy() * 100.0
    obj = sub["object_miss_ratio"].to_numpy() * 100.0
    byt = sub["byte_miss_ratio"].to_numpy() * 100.0
    ax.plot(cap_pct, obj, label="object/request miss", linewidth=2, color="#1f77b4")
    ax.plot(cap_pct, byt, label="byte miss", linewidth=2, color="#d62728")
    ax.set_xlabel("DRAM capacity (% of unique value bytes)")
    ax.set_ylabel("miss ratio (%)")
    ax.set_title(f"Forward MRC — {workload}")
    ax.legend(loc="upper right")
    _set_full_axes(ax)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def plot_inverse_mrc(
    df: pd.DataFrame, workload: str, out_path: Path
) -> Path:
    """Plot inverse MRC for a single workload."""
    sub = df[df["workload"] == workload].sort_values("target_miss_ratio_percent")
    fig, ax = plt.subplots(figsize=(6, 4.5), dpi=120)
    targets = sub["target_miss_ratio_percent"].to_numpy()
    req_obj = sub["required_capacity_percent_of_unique_bytes_for_request_miss"].to_numpy()
    req_byte = sub["required_capacity_percent_of_unique_bytes_for_byte_miss"].to_numpy()
    ax.plot(targets, req_obj, label="request/object miss target", linewidth=2, color="#1f77b4")
    ax.plot(targets, req_byte, label="byte miss target", linewidth=2, color="#d62728")
    ax.set_xlabel("target miss ratio (%)")
    ax.set_ylabel("required DRAM capacity (% of unique value bytes)")
    ax.set_title(f"Inverse MRC — {workload}")
    ax.legend(loc="upper right")
    _set_full_axes(ax)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def make_contact_sheet(image_paths: list[Path], out_path: Path, cols: int = 3) -> Path:
    """Combine PNGs into a single grid image (contact sheet)."""
    if not image_paths:
        raise ValueError("no images to assemble")
    cols = max(1, int(cols))
    images = [Image.open(p).convert("RGB") for p in image_paths]
    w = max(im.width for im in images)
    h = max(im.height for im in images)
    rows = math.ceil(len(images) / cols)
    sheet = Image.new("RGB", (w * cols, h * rows), color="white")
    for idx, im in enumerate(images):
        r, c = divmod(idx, cols)
        sheet.paste(im, (c * w, r * h))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    for im in images:
        im.close()
    return out_path


def plot_all(
    forward_csv: Path,
    inverse_csv: Path,
    out_dir: Path,
    cols: int = 3,
) -> dict:
    """Generate per-workload forward/inverse plots plus contact sheets.

    Returns dict with keys: forward_plots, inverse_plots, forward_sheet, inverse_sheet.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fwd = pd.read_csv(forward_csv)
    inv = pd.read_csv(inverse_csv)

    workloads = sorted(fwd["workload"].unique().tolist())

    forward_plots: list[Path] = []
    inverse_plots: list[Path] = []
    for wl in workloads:
        fp = out_dir / f"forward_{wl}.png"
        ip = out_dir / f"inverse_{wl}.png"
        plot_forward_mrc(fwd, wl, fp)
        plot_inverse_mrc(inv, wl, ip)
        forward_plots.append(fp)
        inverse_plots.append(ip)

    fwd_sheet = make_contact_sheet(forward_plots, out_dir / "forward_contact_sheet.png", cols=cols)
    inv_sheet = make_contact_sheet(inverse_plots, out_dir / "inverse_contact_sheet.png", cols=cols)

    return {
        "forward_plots": forward_plots,
        "inverse_plots": inverse_plots,
        "forward_sheet": fwd_sheet,
        "inverse_sheet": inv_sheet,
    }
