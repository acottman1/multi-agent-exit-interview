"""
Baseline comparison runner for §25.

Feeds the same Q&A transcript as a multi-agent run to a single LLM call and
extracts a knowledge graph in one shot — no specialist agents, no turn-by-turn
adaptation, no ambiguity detection, no coverage tracking.

Usage:
    python -m eval.run_baseline --run runs/helpful --output runs/baseline_helpful
    python -m eval.run_baseline --run runs/helpful   # output defaults to runs/baseline_helpful

─── DESIGN DISCOVERY (important for paper §25) ──────────────────────────────

The first implementation asked the LLM to return the COMPLETE updated graph —
seeded nodes + all newly extracted nodes and edges — in a single response.

This failed immediately with:
    instructor.core.exceptions.IncompleteOutputException:
    The output is incomplete due to a max_tokens length limit.

The model (claude-haiku-4-5-20251001) hit the output token ceiling before it
could finish generating even the node list for a 4-turn interview with only 13
seeded nodes. The response was truncated mid-JSON with stop_reason='max_tokens'.

This is itself a paper finding: the naive single-prompt approach cannot reliably
return a complete knowledge graph due to output token constraints, even for a
small scenario. The multi-agent system sidesteps this entirely — each specialist
agent returns a narrow, bounded output type (just entities, just relationships,
just attributes), and the graph is built incrementally across turns.

Revised approach: ask the LLM to return ONLY new items discovered in the
transcript, then merge with the seeded graph in Python (_merge_with_seed).
This is recorded in final_outputs["naive_token_limit_hit"] = True so the
compare_results script can surface it.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.agents.llm_client import MODEL, get_client
from app.core.models import SharedInterviewState
from app.graph.schema import KnowledgeGraph
from app.ingestion.loaders import load_initial_state
from app.vault.vault_compiler import compile_vault, load_final_state, save_final_state

_PROMPT_PATH = Path(__file__).parent / "baseline_prompt.md"
_BASELINE_MAX_TOKENS = 4096


# ── Transcript and graph formatting ──────────────────────────────────────────

def _build_transcript(state: SharedInterviewState) -> str:
    lines: list[str] = []
    for turn in state.turns:
        lines.append(f"Q{turn.turn_number}: {turn.question}")
        lines.append(f"A{turn.turn_number}: {turn.answer}")
        lines.append("")
    return "\n".join(lines).strip()


def _seeded_graph_json(state: SharedInterviewState) -> str:
    nodes = [
        {
            "id": n.id,
            "type": n.type,
            "label": n.label,
            "aliases": n.aliases,
            "attributes": n.attributes,
            "status": n.status,
            "confidence": n.confidence,
            "provenance": n.provenance,
        }
        for n in state.graph.nodes
    ]
    edges = [
        {
            "id": e.id,
            "type": e.type,
            "source_id": e.source_id,
            "target_id": e.target_id,
            "attributes": e.attributes,
            "status": e.status,
            "confidence": e.confidence,
            "provenance": e.provenance,
        }
        for e in state.graph.edges
    ]
    return json.dumps({"nodes": nodes, "edges": edges}, indent=2)


def _merge_with_seed(
    seed: KnowledgeGraph,
    extracted: KnowledgeGraph,
) -> tuple[KnowledgeGraph, int]:
    """Merge newly extracted items into the seeded graph; return (merged, dangling_count)."""
    existing_node_ids = {n.id for n in seed.nodes}
    existing_edge_ids = {e.id for e in seed.edges}

    merged_nodes = list(seed.nodes)
    for node in extracted.nodes:
        if node.id not in existing_node_ids:
            merged_nodes.append(node)

    all_valid_ids = {n.id for n in merged_nodes}
    merged_edges = list(seed.edges)
    dangling = 0
    for edge in extracted.edges:
        if edge.id in existing_edge_ids:
            continue
        if edge.source_id not in all_valid_ids or edge.target_id not in all_valid_ids:
            dangling += 1
            continue
        merged_edges.append(edge)

    return KnowledgeGraph(nodes=merged_nodes, edges=merged_edges), dangling


# ── LLM call ─────────────────────────────────────────────────────────────────

async def _extract(
    run_state: SharedInterviewState,
    seed_state: SharedInterviewState,
) -> tuple[KnowledgeGraph, int]:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        template
        .replace("{{SEEDED_GRAPH}}", _seeded_graph_json(seed_state))
        .replace("{{TRANSCRIPT}}", _build_transcript(run_state))
    )
    client = get_client()
    extracted: KnowledgeGraph = await client.chat.completions.create(
        model=MODEL,
        max_tokens=_BASELINE_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        response_model=KnowledgeGraph,
    )
    return _merge_with_seed(seed_state.graph, extracted)


# ── Main runner ───────────────────────────────────────────────────────────────

async def run_baseline(run_path: Path, output_path: Path) -> SharedInterviewState:
    """Extract a knowledge graph from a multi-agent run's transcript in one LLM call."""
    run_state = load_final_state(run_path / "final_state.json")
    seed_state = load_initial_state(run_state.interviewee)

    print(f"Transcript   : {len(run_state.turns)} turns")
    print(f"Seeded graph : {len(seed_state.graph.nodes)} nodes, "
          f"{len(seed_state.graph.edges)} edges")
    print(f"Model        : {MODEL}")
    print("Running single-LLM extraction …")

    graph, dangling_count = await _extract(run_state, seed_state)

    confirmed_nodes = sum(1 for n in graph.nodes if n.status == "confirmed")
    confirmed_edges = sum(1 for e in graph.edges if e.status == "confirmed")
    print(f"Extracted    : {len(graph.nodes)} nodes ({confirmed_nodes} confirmed), "
          f"{len(graph.edges)} edges ({confirmed_edges} confirmed)")
    if dangling_count:
        print(f"Excluded     : {dangling_count} dangling edge(s) with non-existent node refs")

    baseline_state = SharedInterviewState(
        interviewee=run_state.interviewee,
        graph=graph,
        turns=run_state.turns,
        final_outputs={
            "baseline": True,
            "dangling_edges_excluded": dangling_count,
            # Recorded for paper §25: the naive single-prompt "return full graph"
            # approach failed with IncompleteOutputException (output token limit
            # exhausted before completing node list on a 4-turn / 13-node scenario).
            # The approach was redesigned to return new items only, then merge.
            "naive_token_limit_hit": True,
            "naive_token_limit_note": (
                "Original prompt asked LLM to reproduce full graph (seeded + extracted). "
                "Failed: stop_reason=max_tokens before node list was complete. "
                "Redesigned to extract new items only and merge with seed in Python."
            ),
        },
    )

    output_path.mkdir(parents=True, exist_ok=True)
    save_final_state(baseline_state, output_path / "final_state.json")
    vault_path = output_path / "exit_interview_vault"
    summary = compile_vault(baseline_state, vault_path)
    print(f"Saved        : {output_path}/final_state.json")
    print(f"Vault        : {vault_path}/ ({summary['files_written']} files, "
          f"{summary['categories']} categories)")

    return baseline_state


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Single-LLM baseline for §25 comparison",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--run", type=Path, default=Path("runs/helpful"),
        help="Multi-agent run directory (must contain final_state.json)",
    )
    ap.add_argument(
        "--output", type=Path, default=None,
        help="Output directory (defaults to runs/baseline_<run-name>)",
    )
    args = ap.parse_args()

    output = args.output or Path("runs") / f"baseline_{args.run.name}"

    if not (args.run / "final_state.json").exists():
        raise FileNotFoundError(f"No final_state.json found in {args.run}")

    print(f"Run    : {args.run}")
    print(f"Output : {output}")
    asyncio.run(run_baseline(args.run, output))


if __name__ == "__main__":
    main()
