"""Command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import pipeline, plot, traces
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="valkey-tiering-mrc",
        description="Synthetic MRC experiment harness (warmed/cyclic exact LRU).",
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

    # plot
    p_plot = sub.add_parser("plot", help="Generate per-workload charts and contact sheets.")
    p_plot.add_argument("--curves", required=True, type=Path,
                        help="Forward MRC CSV.")
    p_plot.add_argument("--inverse", required=True, type=Path,
                        help="Inverse MRC CSV.")
    p_plot.add_argument("--out", required=True, type=Path)
    p_plot.add_argument("--cols", type=int, default=3,
                        help="Columns in the contact sheet grid.")

    # run-all
    p_run = sub.add_parser("run-all", help="Generate traces, compute MRCs, and plot.")
    p_run.add_argument("--config", required=True, type=Path)
    p_run.add_argument("--out", required=True, type=Path)
    _add_overrides(p_run)

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


def cmd_run_all(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    cfg = apply_overrides(
        cfg,
        events=args.events,
        keyspace=args.keyspace,
        seed=args.seed,
        capacity_points=args.capacity_points,
    )
    pipeline.run_all(cfg, Path(args.out), progress=True)
    return 0


COMMANDS = {
    "generate-traces": cmd_generate_traces,
    "compute-lru": cmd_compute_lru,
    "plot": cmd_plot,
    "run-all": cmd_run_all,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return COMMANDS[args.cmd](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
