"""
Golden-interview evaluation script.

Runs both golden transcripts through the full pipeline with real LLM agents
and prints a structured report answering the research question:

    Does this multi-agent panel actually capture knowledge accurately?

Usage:
    python -m eval.run_golden_eval                    # run all scenarios
    python -m eval.run_golden_eval --only helpful     # original fixtures
    python -m eval.run_golden_eval --only lena        # ERP modernization
    python -m eval.run_golden_eval --only noah        # cloud migration
    python -m eval.run_golden_eval --only victor      # data platform
    python -m eval.run_golden_eval --only aisha       # cybersecurity
    python -m eval.run_golden_eval --only sofia       # client onboarding
    python -m eval.run_golden_eval --no-seed          # all scenarios, blank graph start

Requires: ANTHROPIC_API_KEY environment variable.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure the project root is on the path when run as __main__.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.models import SharedInterviewState
from app.graph.schema import KnowledgeGraph
from app.ingestion.loaders import load_initial_state
from app.interview.turn_loop import TurnResult, run_interview
from app.vault.vault_compiler import compile_vault, save_final_state

_DEFAULT_SEED = Path(__file__).parent.parent / "app" / "ingestion" / "dummy_data" / "initial_state.json"


# ── Report data structures ────────────────────────────────────────────────────

@dataclass
class TurnSummary:
    turn_number: int
    question: str
    answer_preview: str
    entities_extracted: list[str]
    relationships_extracted: list[str]
    clarifications: list[str]
    coverage_delta: dict[str, float]
    nodes_created: int
    nodes_updated: int


@dataclass
class EvalReport:
    scenario_name: str
    interviewee_name: str
    turn_summaries: list[TurnSummary] = field(default_factory=list)
    assertions_passed: list[str] = field(default_factory=list)
    assertions_failed: list[str] = field(default_factory=list)
    final_node_count: int = 0
    initial_node_count: int = 0
    final_coverage: dict[str, float] = field(default_factory=dict)
    total_clarifications: int = 0
    richard_ambiguity_resolved: bool = False


# ── Runner ────────────────────────────────────────────────────────────────────

def _scripted(answers: list[str]):
    it = iter(answers)
    def provider(_question: str) -> str:
        return next(it, "(no further answer)")
    return provider


def _summarise_turn(
    result: TurnResult,
    prev_coverage: dict[str, float],
) -> TurnSummary:
    entity_out = result.proposed_update.entity_extraction
    rel_out = result.proposed_update.relationship_extraction
    clar_out = result.proposed_update.clarifications

    entities = []
    if entity_out:
        for e in entity_out.entities:
            flag = " [AMBIGUOUS]" if e.is_ambiguous else ""
            entities.append(f"{e.label} ({e.type}, conf={e.confidence:.2f}){flag}")

    relationships = []
    if rel_out:
        for r in rel_out.relationships:
            relationships.append(f"{r.source_ref} --{r.type}--> {r.target_ref}")

    clarifications = []
    if clar_out:
        for c in clar_out.clarifications:
            clarifications.append(f"[{c.priority.upper()}] {c.suggested_question}")

    # Compute coverage delta
    apply = result.apply_result
    created = apply.created_count
    updated = apply.promoted_count + len([
        c for c in apply.node_changes if c.op == "updated"
    ])

    return TurnSummary(
        turn_number=result.turn.turn_number,
        question=result.turn.question,
        answer_preview=result.turn.answer[:120] + ("…" if len(result.turn.answer) > 120 else ""),
        entities_extracted=entities,
        relationships_extracted=relationships,
        clarifications=clarifications,
        coverage_delta={},   # filled by caller who has before/after
        nodes_created=created,
        nodes_updated=updated,
    )


async def run_scenario(
    scenario_name: str,
    fixture_module,
    no_seed: bool = False,
) -> EvalReport:
    if no_seed:
        state = SharedInterviewState(
            interviewee=fixture_module.INTERVIEWEE,
            graph=KnowledgeGraph(nodes=[], edges=[]),
        )
    else:
        seed_path = getattr(fixture_module, "SEED_PATH", _DEFAULT_SEED)
        state = load_initial_state(fixture_module.INTERVIEWEE, path=seed_path)
    initial_count = len(state.graph.nodes)
    prev_cov = {f: 0.0 for f in state.coverage.model_fields}

    report = EvalReport(
        scenario_name=scenario_name,
        interviewee_name=fixture_module.INTERVIEWEE.name,
        initial_node_count=initial_count,
    )

    results = await run_interview(
        state,
        _scripted(fixture_module.SCRIPTED_ANSWERS),
        max_turns=len(fixture_module.SCRIPTED_ANSWERS),
    )

    for result in results:
        turn_sum = _summarise_turn(result, prev_cov)
        prev_cov = {f: getattr(state.coverage, f) for f in state.coverage.model_fields}
        report.turn_summaries.append(turn_sum)
        report.total_clarifications += len(turn_sum.clarifications)

    report.final_node_count = len(state.graph.nodes)
    report.final_coverage = {f: getattr(state.coverage, f) for f in state.coverage.model_fields}

    richard_amb = next(
        (a for a in state.ambiguities if a.ambiguity_id == "amb_seed_001"), None
    )
    report.richard_ambiguity_resolved = richard_amb.resolved if richard_amb else False

    # Persist state and compile vault
    slug = scenario_name.split()[0].lower()          # e.g. "helpful", "vague"
    runs_dir = Path("runs") / slug
    save_final_state(state, runs_dir / "final_state.json")
    compile_vault(state, runs_dir / "exit_interview_vault")

    # Run assertions from fixture
    _check_assertions(report, state, fixture_module)

    return report


def _check_assertions(report: EvalReport, state, fixture_module) -> None:
    labels = {n.label for n in state.graph.nodes}

    # Helpful scenario assertions
    if hasattr(fixture_module, "REQUIRED_NODE_LABELS"):
        for required in fixture_module.REQUIRED_NODE_LABELS:
            found = any(required.lower() in label.lower() for label in labels)
            msg = f"Node '{required}' {'found' if found else 'MISSING'} in graph"
            (report.assertions_passed if found else report.assertions_failed).append(msg)

    if hasattr(fixture_module, "EXPECTED_COVERAGE_ABOVE_ZERO"):
        for cat in fixture_module.EXPECTED_COVERAGE_ABOVE_ZERO:
            score = report.final_coverage.get(cat, 0.0)
            ok = score > 0.0
            msg = f"Coverage[{cat}] = {score:.2f} ({'✓ > 0' if ok else '✗ still 0'})"
            (report.assertions_passed if ok else report.assertions_failed).append(msg)

    if hasattr(fixture_module, "MIN_NEW_NODES"):
        new_nodes = report.final_node_count - report.initial_node_count
        ok = new_nodes >= fixture_module.MIN_NEW_NODES
        msg = f"New nodes: {new_nodes} ({'✓' if ok else '✗'} ≥{fixture_module.MIN_NEW_NODES} required)"
        (report.assertions_passed if ok else report.assertions_failed).append(msg)

    # Vague scenario assertions
    if hasattr(fixture_module, "LABELS_THAT_MUST_NOT_EXIST"):
        for bad_label in fixture_module.LABELS_THAT_MUST_NOT_EXIST:
            found = any(bad_label.lower() in label.lower() for label in labels)
            ok = not found
            msg = f"Hallucination check '{bad_label}': {'✓ NOT in graph' if ok else '✗ HALLUCINATED'}"
            (report.assertions_passed if ok else report.assertions_failed).append(msg)

    if hasattr(fixture_module, "MIN_TOTAL_CLARIFICATIONS"):
        ok = report.total_clarifications >= fixture_module.MIN_TOTAL_CLARIFICATIONS
        msg = (
            f"Clarifications: {report.total_clarifications} "
            f"({'✓' if ok else '✗'} ≥{fixture_module.MIN_TOTAL_CLARIFICATIONS} required)"
        )
        (report.assertions_passed if ok else report.assertions_failed).append(msg)

    if hasattr(fixture_module, "MAX_COVERAGE_SCORE"):
        threshold = fixture_module.MAX_COVERAGE_SCORE
        for cat, score in report.final_coverage.items():
            ok = score <= threshold
            msg = f"Coverage[{cat}] = {score:.2f} ({'✓' if ok else '✗'} ≤{threshold})"
            (report.assertions_passed if ok else report.assertions_failed).append(msg)

    if hasattr(fixture_module, "MAX_NEW_NODES"):
        new_nodes = report.final_node_count - report.initial_node_count
        ok = new_nodes <= fixture_module.MAX_NEW_NODES
        msg = f"New nodes: {new_nodes} ({'✓' if ok else '✗'} ≤{fixture_module.MAX_NEW_NODES})"
        (report.assertions_passed if ok else report.assertions_failed).append(msg)

    # Universal ambiguity check
    ok = report.richard_ambiguity_resolved
    if hasattr(fixture_module, "AMBIGUITY_MUST_REMAIN_UNRESOLVED"):
        ok = not report.richard_ambiguity_resolved
        msg = f"Richard ambiguity unresolved: {'✓' if ok else '✗'}"
    else:
        msg = f"Richard ambiguity resolved: {'✓' if ok else '✗'}"
    (report.assertions_passed if ok else report.assertions_failed).append(msg)


# ── Printer ───────────────────────────────────────────────────────────────────

def print_report(report: EvalReport) -> None:
    width = 72
    divider = "─" * width

    print(f"\n{'═' * width}")
    print(f"  GOLDEN EVAL: {report.scenario_name.upper()}")
    print(f"  Interviewee: {report.interviewee_name}")
    print(f"{'═' * width}")

    for ts in report.turn_summaries:
        print(f"\n  TURN {ts.turn_number}")
        print(f"  Q: {textwrap.shorten(ts.question, 68)}")
        print(f"  A: {ts.answer_preview}")

        if ts.entities_extracted:
            print("  Entities extracted:")
            for e in ts.entities_extracted:
                print(f"    • {e}")
        else:
            print("  Entities extracted: (none)")

        if ts.relationships_extracted:
            print("  Relationships:")
            for r in ts.relationships_extracted:
                print(f"    • {r}")

        if ts.clarifications:
            print("  Clarifications generated:")
            for c in ts.clarifications:
                print(f"    ⚠ {c}")

        created_label = f"{ts.nodes_created} created" if ts.nodes_created else "none created"
        print(f"  Graph ops: {created_label}, {ts.nodes_updated} updated")

    print(f"\n{divider}")
    print("  FINAL STATE")
    print(f"  Nodes: {report.initial_node_count} → {report.final_node_count} "
          f"(+{report.final_node_count - report.initial_node_count})")
    print(f"  Total clarifications generated: {report.total_clarifications}")
    print(f"  Richard ambiguity resolved: {report.richard_ambiguity_resolved}")
    print("  Coverage scores:")
    for cat, score in report.final_coverage.items():
        bar = "█" * int(score * 20)
        print(f"    {cat:<25} {score:.2f}  {bar}")

    print(f"\n{divider}")
    print(f"  ASSERTIONS ({len(report.assertions_passed)} passed, "
          f"{len(report.assertions_failed)} failed)")
    for msg in report.assertions_passed:
        print(f"    ✓ {msg}")
    for msg in report.assertions_failed:
        print(f"    ✗ {msg}")

    status = "PASS" if not report.assertions_failed else "FAIL"
    print(f"\n  RESULT: {status}")
    print(f"{'═' * width}\n")


# ── Scenario registry ─────────────────────────────────────────────────────────

_SCENARIO_REGISTRY: dict[str, tuple[str, str]] = {
    "helpful":    ("Helpful Alex — clear cooperative answers",          "helpful_alex"),
    "vague":      ("Vague Jordan — evasive contradictory answers",      "vague_jordan"),
    "lena":       ("Cooperative Lena — ERP modernization handoff",      "cooperative_lena"),
    "noah":       ("Timid Noah — cloud migration support rollover",     "timid_noah"),
    "victor":     ("Negative Victor — data platform contractor exit",   "negative_victor"),
    "aisha":      ("Technical Aisha — cybersecurity compliance",        "technical_aisha"),
    "sofia":      ("Vague Sofia — client onboarding operations",        "vague_sofia"),
}


# ── Entry point ───────────────────────────────────────────────────────────────

async def main(only: str | None = None, no_seed: bool = False) -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 1

    import importlib
    import tests.fixtures.golden_interviews  # ensure package is importable

    keys = [only] if only else list(_SCENARIO_REGISTRY)
    scenarios = []
    for key in keys:
        label, module_name = _SCENARIO_REGISTRY[key]
        mod = importlib.import_module(f"tests.fixtures.golden_interviews.{module_name}")
        scenarios.append((label, mod))

    if no_seed:
        print("  ⚠  --no-seed active: starting each scenario with an empty graph.\n")

    all_passed = True
    for name, fixture in scenarios:
        print(f"\nRunning scenario: {name} …")
        report = await run_scenario(name, fixture, no_seed=no_seed)
        print_report(report)
        if report.assertions_failed:
            all_passed = False

    return 0 if all_passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run golden interview evaluations.")
    parser.add_argument(
        "--only",
        choices=list(_SCENARIO_REGISTRY),
        help="Run only one scenario by key.",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help=(
            "Start each scenario with a blank graph (no seeded nodes, questions, "
            "or ambiguities). Useful for measuring raw extraction quality without "
            "pre-primed context. Note: scripted golden tests pin answers against "
            "seed-derived question order; use with live LLM responses for best results."
        ),
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.only, no_seed=args.no_seed)))
