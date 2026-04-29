"""
Side-by-side comparison of multi-agent vs. single-LLM baseline on §25 metrics.

Usage:
    python -m eval.compare_results runs/helpful runs/baseline_helpful
"""
from __future__ import annotations

import argparse
from pathlib import Path

from app.core.models import SharedInterviewState
from app.vault.vault_compiler import load_final_state

_W = 30  # label column width


def _pct(v: float) -> str:
    return f"{v:.0%}"


def _count(state: SharedInterviewState, kind: str, status: str) -> int:
    collection = state.graph.nodes if kind == "node" else state.graph.edges
    return sum(1 for item in collection if item.status == status)


def _row(label: str, multi_val: object, base_val: object, note: str = "") -> None:
    note_str = f"  {note}" if note else ""
    print(f"  {label:{_W}} {str(multi_val):>14}   {str(base_val):>12}{note_str}")


def _header() -> None:
    print(f"  {'':30} {'Multi-agent':>14}   {'Baseline':>12}")
    print(f"  {'-'*30} {'-'*14}   {'-'*12}")


def compare(multi: SharedInterviewState, base: SharedInterviewState) -> None:
    # ── Entity coverage ───────────────────────────────────────────────────────
    print()
    print("ENTITY COVERAGE")
    _header()
    _row("Total nodes", len(multi.graph.nodes), len(base.graph.nodes))
    _row("  Confirmed", _count(multi, "node", "confirmed"), _count(base, "node", "confirmed"))
    _row("  Provisional", _count(multi, "node", "provisional"), _count(base, "node", "provisional"))
    _row("  Superseded", _count(multi, "node", "superseded"), _count(base, "node", "superseded"))

    # ── Relationship precision ─────────────────────────────────────────────────
    print()
    print("RELATIONSHIP PRECISION")
    _header()
    _row("Total edges", len(multi.graph.edges), len(base.graph.edges))
    _row("  Confirmed", _count(multi, "edge", "confirmed"), _count(base, "edge", "confirmed"))
    _row("  Provisional", _count(multi, "edge", "provisional"), _count(base, "edge", "provisional"))
    base_dangling = base.final_outputs.get("dangling_edges_excluded", "n/a")
    _row("  Dangling refs (excluded)", 0, base_dangling, "(multi enforced by updater)")

    # ── Ambiguity handling ─────────────────────────────────────────────────────
    print()
    print("AMBIGUITY HANDLING")
    _header()
    unresolved = sum(1 for a in multi.ambiguities if not a.resolved)
    resolved = len(multi.ambiguities) - unresolved
    _row("Ambiguities detected", len(multi.ambiguities), "0", "(no detection)")
    _row("  Resolved", resolved, "n/a")
    _row("  Unresolved", unresolved, "n/a")

    # ── Coverage scores ────────────────────────────────────────────────────────
    print()
    print("HANDOFF COVERAGE SCORES  (tracked by coverage-updater agent)")
    _header()
    cov_m = multi.coverage
    cov_b = base.coverage
    for field in type(cov_m).model_fields:
        label = field.replace("_", " ").title()
        score_m = getattr(cov_m, field)
        score_b = getattr(cov_b, field)
        note = "(not tracked)" if score_b == 0.0 else ""
        _row(label, _pct(score_m), _pct(score_b), note)

    # ── Malformed / unsupported updates ────────────────────────────────────────
    print()
    print("MALFORMED / UNSUPPORTED GRAPH UPDATES")
    _header()
    _row("Dangling edge refs", 0, base_dangling)
    print()
    print("  Multi-agent: updater rejects dangling edges at commit time (invariant 12).")
    print("  Baseline: dangling edges detected post-hoc and excluded before vault compile.")

    # ── Naive approach failure (paper finding) ─────────────────────────────────
    print()
    print("=" * 70)
    print("  NAIVE APPROACH FAILURE  (paper §25 finding)")
    print("=" * 70)
    if base.final_outputs.get("naive_token_limit_hit"):
        note = base.final_outputs.get("naive_token_limit_note", "")
        print()
        print("  The original single-prompt baseline FAILED before any results were")
        print("  produced. The LLM was asked to return the complete updated knowledge")
        print("  graph (seeded nodes + extracted nodes) in one response.")
        print()
        print("  Error: instructor.IncompleteOutputException")
        print("         stop_reason = max_tokens")
        print("         The model exhausted its output token budget mid-JSON,")
        print("         before it finished the node list for a 4-turn / 13-node scenario.")
        print()
        print("  This is itself a §25 finding: the naive approach cannot reliably")
        print("  return a complete knowledge graph due to output token constraints,")
        print("  even for a small interview. The multi-agent system avoids this by")
        print("  scoping each agent to a narrow output type (entities only, relationships")
        print("  only, attributes only) and accumulating the graph incrementally.")
        print()
        print("  Workaround applied: redesigned baseline to extract NEW items only,")
        print("  then merge with seed graph in Python. Results above reflect this")
        print("  workaround — the failure itself is the more telling comparison point.")
    else:
        print("  (No token-limit failure recorded for this baseline run.)")

    print()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Compare multi-agent vs. baseline on §25 metrics",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("multi", type=Path, help="Multi-agent run directory")
    ap.add_argument("baseline", type=Path, help="Baseline run directory")
    args = ap.parse_args()

    for path in (args.multi, args.baseline):
        if not (path / "final_state.json").exists():
            raise FileNotFoundError(f"No final_state.json in {path}")

    multi = load_final_state(args.multi / "final_state.json")
    base = load_final_state(args.baseline / "final_state.json")

    print()
    print("=" * 70)
    print("  §25 BASELINE COMPARISON")
    print(f"  Multi-agent : {args.multi}")
    print(f"  Baseline    : {args.baseline}")
    print("=" * 70)

    compare(multi, base)

    print("=" * 70)


if __name__ == "__main__":
    main()
