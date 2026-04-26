"""Command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import pipeline, plot, simulate, traces
from .config import apply_overrides, load_config


def _add_overrides(p: argparse.ArgumentParser) -> None:
    p.add_argument("--events", type=int, default=None,
                   help="Override global.events")
    p.add_argument("--keyspace", type=int, default=None,
                   help="Override global.keyspace")
    p.add_argument("--seed", type=int, default=None,
                   help="Override global.seed")
    p.add_argument("--capacity-points", type=int, default=None,
                   help="Override global.capacity_points")


def _parse_policies(s: str) -> list[str]:
    items = [p.strip() for p in s.split(",") if p.strip()]
    valid = {"lru", "true_lfu"}
    bad = [p for p in items if p not in valid]
    if bad:
        raise argparse.ArgumentTypeError(
            f"unknown policies: {bad} (valid: {sorted(valid)})"
        )
    return items




def _parse_measurement_mode(s: str) -> str:
    valid = {"exclude_first_touch", "cyclic"}
    if s not in valid:
        raise argparse.ArgumentTypeError(f"unknown measurement mode: {s} (valid: {sorted(valid)})")
    return s

def _parse_workloads(s: str | None) -> list[str] | None:
    if not s:
        return None
    return [w.strip() for w in s.split(",") if w.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="valkey-tiering-mrc",
        description="Synthetic MRC experiment harness (exclude-first-touch LRU + true LFU).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # generate-traces
    p_gen = sub.add_parser("generate-traces", help="Generate synthetic GET-only traces.")
    p_gen.add_argument("--config", required=True, type=Path)
    p_gen.add_argument("--out", required=True, type=Path)
    _add_overrides(p_gen)

    # compute-lru
    p_lru = sub.add_parser(
        "compute-lru",
        help="Compute warmed/cyclic exact LRU MRCs from existing traces.",
    )
    p_lru.add_argument("--traces", required=True, type=Path,
                       help="Directory containing trace CSVs.")
    p_lru.add_argument("--out", required=True, type=Path)
    p_lru.add_argument("--capacity-points", type=int, default=1001)
    p_lru.add_argument("--measurement-mode", type=_parse_measurement_mode, default="exclude_first_touch")

    # compute-lfu
    p_lfu = sub.add_parser(
        "compute-lfu",
        help="Compute warmed/cyclic true-LFU MRCs by per-capacity replay.",
    )
    p_lfu.add_argument("--traces", required=True, type=Path,
                       help="Directory containing trace CSVs.")
    p_lfu.add_argument("--out", required=True, type=Path)
    p_lfu.add_argument("--capacity-points", type=int, default=1001)
    p_lfu.add_argument("--measurement-mode", type=_parse_measurement_mode, default="exclude_first_touch")
    p_lfu.add_argument(
        "--workload", type=str, default=None,
        help="Comma-separated workload names to filter (default: all in dir).",
    )

    # plot
    p_plot = sub.add_parser(
        "plot",
        help="Generate per-workload charts and contact sheets from any policy CSV.",
    )
    p_plot.add_argument("--curves", required=True, type=Path,
                        help="Forward MRC CSV (any policy).")
    p_plot.add_argument("--inverse", required=True, type=Path,
                        help="Inverse MRC CSV (any policy).")
    p_plot.add_argument("--out", required=True, type=Path)
    p_plot.add_argument("--cols", type=int, default=3,
                        help="Columns in the contact sheet grid.")

    # compare-policies
    p_cmp = sub.add_parser(
        "compare-policies",
        help="Generate LRU vs true-LFU comparison charts.",
    )
    p_cmp.add_argument("--lru-curves", required=True, type=Path)
    p_cmp.add_argument("--lfu-curves", required=True, type=Path)
    p_cmp.add_argument("--lru-inverse", type=Path, default=None,
                       help="Optional LRU inverse CSV (enables inverse comparisons).")
    p_cmp.add_argument("--lfu-inverse", type=Path, default=None,
                       help="Optional LFU inverse CSV (enables inverse comparisons).")
    p_cmp.add_argument("--out", required=True, type=Path)
    p_cmp.add_argument("--cols", type=int, default=3)

    # run-all
    p_run = sub.add_parser("run-all", help="Generate traces, compute MRCs, and plot.")
    p_run.add_argument("--config", required=True, type=Path)
    p_run.add_argument("--out", required=True, type=Path)
    p_run.add_argument(
        "--policies",
        type=_parse_policies,
        default=["lru"],
        help="Comma-separated subset of {lru,true_lfu}. Default: lru",
    )
    _add_overrides(p_run)
    p_run.add_argument("--measurement-mode", type=_parse_measurement_mode, default="exclude_first_touch")

    return parser


def cmd_generate_traces(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    cfg = apply_overrides(
        cfg,
        events=args.events,
        keyspace=args.keyspace,
        seed=args.seed,
        capacity_points=args.capacity_points,
    )
    traces.generate_all_traces(cfg, args.out, progress=True)
    return 0


def cmd_compute_lru(args: argparse.Namespace) -> int:
    traces_dir = Path(args.traces)
    if not traces_dir.exists():
        raise SystemExit(f"traces directory not found: {traces_dir}")
    trace_paths = sorted(p for p in traces_dir.glob("*.csv"))
    if not trace_paths:
        raise SystemExit(f"no trace CSVs found under {traces_dir}")
    pipeline.compute_lru_for_traces(
        trace_paths,
        Path(args.out),
        capacity_points=args.capacity_points,
        measurement_mode=args.measurement_mode,
        progress=True,
    )
    return 0


def cmd_compute_lfu(args: argparse.Namespace) -> int:
    traces_dir = Path(args.traces)
    if not traces_dir.exists():
        raise SystemExit(f"traces directory not found: {traces_dir}")
    trace_paths = sorted(p for p in traces_dir.glob("*.csv"))
    if not trace_paths:
        raise SystemExit(f"no trace CSVs found under {traces_dir}")
    workloads = _parse_workloads(args.workload)
    if workloads:
        keep = set(workloads)
        trace_paths = [p for p in trace_paths if p.stem in keep]
        if not trace_paths:
            raise SystemExit(f"no trace files match --workload {workloads}")
    simulate.simulate_true_lfu_for_traces(
        trace_paths,
        Path(args.out),
        capacity_points=args.capacity_points,
        measurement_mode=args.measurement_mode,
        progress=True,
    )
    return 0


def cmd_plot(args: argparse.Namespace) -> int:
    plot.plot_all(
        forward_csv=Path(args.curves),
        inverse_csv=Path(args.inverse),
        out_dir=Path(args.out),
        cols=args.cols,
    )
    return 0


def cmd_compare_policies(args: argparse.Namespace) -> int:
    plot.plot_compare_policies(
        lru_csv=Path(args.lru_curves),
        lfu_csv=Path(args.lfu_curves),
        out_dir=Path(args.out),
        lru_inverse_csv=Path(args.lru_inverse) if args.lru_inverse else None,
        lfu_inverse_csv=Path(args.lfu_inverse) if args.lfu_inverse else None,
        cols=args.cols,
    )
    return 0


def cmd_run_all(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    cfg = apply_overrides(
        cfg,
        events=args.events,
        keyspace=args.keyspace,
        seed=args.seed,
        capacity_points=args.capacity_points,
    )
    pipeline.run_all(
        cfg,
        Path(args.out),
        policies=args.policies,
        measurement_mode=args.measurement_mode,
        progress=True,
    )
    return 0


COMMANDS = {
    "generate-traces": cmd_generate_traces,
    "compute-lru": cmd_compute_lru,
    "compute-lfu": cmd_compute_lfu,
    "plot": cmd_plot,
    "compare-policies": cmd_compare_policies,
    "run-all": cmd_run_all,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return COMMANDS[args.cmd](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
