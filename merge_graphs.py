"""
Hierarchical graph merge CLI.

Combines two or more saved interview states into a single merged graph,
compiles an Obsidian vault from the result, and writes a human-readable
conflict report.

The same operation works at any level of hierarchy:

  Project-level  (multiple witnesses on the same project):
    python merge_graphs.py \\
      runs/alex_miller/final_state.json \\
      runs/jordan_lee/final_state.json \\
      --name "Project Falcon" \\
      --out runs/merged/falcon/

  Company-level  (multiple already-merged project graphs):
    python merge_graphs.py \\
      runs/merged/falcon/final_state.json \\
      runs/merged/erp/final_state.json \\
      --name "Company Overview" \\
      --out runs/merged/company/

Output
------
  <out>/final_state.json        merged SharedInterviewState (usable as seed)
  <out>/exit_interview_vault/   Obsidian vault for the merged graph
  <out>/merge_report.txt        node/edge stats + full conflict log
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# UTF-8 output so box-drawing chars survive Windows terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))

from app.graph.merger import merge_states
from app.vault.vault_compiler import compile_vault, load_final_state, save_final_state

WIDTH = 70


def _divider(char: str = "=") -> None:
    print(char * WIDTH)


def _write_report(
    states_meta: list[tuple[str, int, int]],
    merged_nodes: int,
    merged_edges: int,
    conflict_log: list[str],
    path: Path,
) -> None:
    """Write a human-readable merge report to *path*."""
    lines: list[str] = [
        "MERGE REPORT",
        "=" * WIDTH,
        "",
        "Sources merged:",
    ]
    for name, nodes, edges in states_meta:
        lines.append(f"  {name:<36}  {nodes:>4} nodes   {edges:>4} edges")

    lines += [
        "",
        f"Merged graph:  {merged_nodes} nodes   {merged_edges} edges",
        "",
    ]

    if conflict_log:
        lines += [
            "=" * WIDTH,
            f"CONFLICTS DETECTED ({len(conflict_log)})",
            "=" * WIDTH,
            "",
        ]
        for i, msg in enumerate(conflict_log, 1):
            lines.append(f"[{i:02d}] {msg}")
            lines.append("")
    else:
        lines += [
            "=" * WIDTH,
            "No attribute conflicts detected.",
            "=" * WIDTH,
        ]

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge multiple exit interview graphs into one.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "states",
        nargs="+",
        metavar="FINAL_STATE_JSON",
        help="Two or more final_state.json files to merge (order affects provenance ordering).",
    )
    parser.add_argument(
        "--name",
        required=True,
        metavar="MERGED_NAME",
        help='Human-readable name for the merged graph, e.g. "Project Falcon".',
    )
    parser.add_argument(
        "--out",
        required=True,
        metavar="DIR",
        help="Output directory for merged state, vault, and report.",
    )

    args = parser.parse_args()

    # ── Validate and load input states ────────────────────────────────────────
    state_paths = [Path(p) for p in args.states]
    for p in state_paths:
        if not p.exists():
            print(f"ERROR: State file not found: {p}", file=sys.stderr)
            sys.exit(1)

    if len(state_paths) < 2:
        print("ERROR: At least two state files are required for a merge.", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    _divider()
    print(f"  GRAPH MERGE")
    print(f"  Merged name : {args.name}")
    print(f"  Sources     : {len(state_paths)}")
    print(f"  Output      : {out_dir}/")
    _divider()

    print()
    print("  Loading states...")
    loaded = []
    states_meta: list[tuple[str, int, int]] = []
    for p in state_paths:
        state = load_final_state(p)
        active_nodes = len([n for n in state.graph.nodes if n.status != "superseded"])
        active_edges = len([e for e in state.graph.edges if e.status != "superseded"])
        print(f"    {state.interviewee.name:<30}  {active_nodes:>4} nodes   {active_edges:>4} edges")
        loaded.append(state)
        states_meta.append((state.interviewee.name, active_nodes, active_edges))

    # ── Merge ─────────────────────────────────────────────────────────────────
    print()
    print("  Merging...")
    merged_state, conflict_log = merge_states(loaded, args.name)

    merged_nodes = len([n for n in merged_state.graph.nodes if n.status != "superseded"])
    merged_edges = len([e for e in merged_state.graph.edges if e.status != "superseded"])
    total_nodes = len(merged_state.graph.nodes)
    total_edges = len(merged_state.graph.edges)

    # ── Save outputs ──────────────────────────────────────────────────────────
    state_path = out_dir / "final_state.json"
    vault_path = out_dir / "exit_interview_vault"
    report_path = out_dir / "merge_report.txt"

    save_final_state(merged_state, state_path)
    compile_vault(merged_state, vault_path)
    _write_report(states_meta, merged_nodes, merged_edges, conflict_log, report_path)

    # ── Summary ───────────────────────────────────────────────────────────────
    _divider()
    print("  MERGE COMPLETE")
    print(f"  Active nodes   : {merged_nodes}  (total incl. superseded: {total_nodes})")
    print(f"  Active edges   : {merged_edges}  (total incl. superseded: {total_edges})")
    print(f"  Conflicts      : {len(conflict_log)}")
    print()
    print(f"  Final state    : {state_path}")
    print(f"  Obsidian vault : {vault_path}/")
    print(f"  Merge report   : {report_path}")
    _divider()

    if conflict_log:
        print()
        print(f"  {len(conflict_log)} attribute conflict(s) found — see merge_report.txt")
        for msg in conflict_log:
            print(f"    ! {msg}")
        print()


if __name__ == "__main__":
    main()
