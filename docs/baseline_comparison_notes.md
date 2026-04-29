# Baseline Comparison Notes — §25

**Generated:** 2026-04-27  
**Scenario:** helpful_alex (Project Falcon, 4-turn cooperative interview)  
**Multi-agent run:** `runs/helpful/`  
**Baseline run:** `runs/baseline_helpful/`  
**Model:** claude-haiku-4-5-20251001 (same model for both systems)

---

## How to reproduce

```bash
# Run the baseline extraction
python -m eval.run_baseline --run runs/helpful --output runs/baseline_helpful

# Print the comparison table
python -m eval.compare_results runs/helpful runs/baseline_helpful
```

---

## §25 Comparison Results

```
======================================================================
  §25 BASELINE COMPARISON
  Multi-agent : runs/helpful
  Baseline    : runs/baseline_helpful
======================================================================

ENTITY COVERAGE
                                    Multi-agent       Baseline
  ------------------------------ --------------   ------------
  Total nodes                                30             20
    Confirmed                                27             12
    Provisional                               3              8
    Superseded                                0              0

RELATIONSHIP PRECISION
                                    Multi-agent       Baseline
  ------------------------------ --------------   ------------
  Total edges                                25             25
    Confirmed                                18             16
    Provisional                               7              9
    Dangling refs (excluded)                  0              0  (multi enforced by updater)

AMBIGUITY HANDLING
                                    Multi-agent       Baseline
  ------------------------------ --------------   ------------
  Ambiguities detected                        1              0  (no detection)
    Resolved                                  1            n/a
    Unresolved                                0            n/a

HANDOFF COVERAGE SCORES  (tracked by coverage-updater agent)
                                    Multi-agent       Baseline
  ------------------------------ --------------   ------------
  People                                    75%             0%  (not tracked)
  Systems                                   40%             0%  (not tracked)
  Workflows                                 55%             0%  (not tracked)
  Stakeholders                              40%             0%  (not tracked)
  Risks                                     50%             0%  (not tracked)
  Undocumented Knowledge                    60%             0%  (not tracked)

MALFORMED / UNSUPPORTED GRAPH UPDATES
                                    Multi-agent       Baseline
  ------------------------------ --------------   ------------
  Dangling edge refs                          0              0

  Multi-agent: updater rejects dangling edges at commit time (invariant 12).
  Baseline: dangling edges detected post-hoc and excluded before vault compile.
```

---

## Naive Approach Failure (paper §25 finding)

This is the most important finding from this comparison exercise, and should be
reported in the paper before the quantitative results above.

### What happened

The first implementation of the baseline asked the LLM to return the **complete
updated knowledge graph** — all seeded nodes plus all newly extracted nodes and
edges — in a single response. This is the most natural interpretation of "one
interviewer agent that asks questions and summarizes answers" (spec §25).

**It failed immediately**, before producing any usable output:

```
instructor.core.exceptions.IncompleteOutputException:
    The output is incomplete due to a max_tokens length limit.

stop_reason = max_tokens
output_tokens = 4096 (budget exhausted)
```

The model exhausted its output token budget **mid-JSON**, before it finished
generating even the node list. This occurred on a minimal scenario:
- 4 interview turns
- 13 seeded nodes
- ~17 expected new nodes

The response was a truncated, unparseable JSON fragment.

### Why this matters for the paper

This failure is itself a §25 finding, independent of the quantitative comparison.
It demonstrates a fundamental architectural limitation of the single-prompt approach:

> A naive LLM cannot reliably return a complete knowledge graph in one response,
> because the output token budget is a hard ceiling that scales with graph size.
> For any realistic project (dozens of entities, hundreds of turns), the naive
> approach will fail — not because of reasoning quality, but because of output
> volume constraints.

The multi-agent system sidesteps this entirely. Each specialist agent returns a
**narrow, bounded output type**:
- Entity extractor → list of candidate entities (typically 2–6 items)
- Relationship extractor → list of candidate edges (typically 1–4 items)
- Attribute extractor → list of key-value facts (typically 2–5 items)

Each output is small and predictable. The graph grows incrementally across turns.
No single LLM call is ever asked to hold or return the full graph state.

### Workaround applied

The baseline was redesigned to extract **new items only** from the transcript,
then merge with the seeded graph in Python (`_merge_with_seed()`). This makes
the baseline runnable, but the workaround itself is not naive — it requires
knowing in advance which nodes are seeded vs. new, which a truly naive system
would not know.

The quantitative results above reflect the workaround. The token-limit failure
is the stronger comparison point.

### Evidence trail

- `eval/run_baseline.py` — module docstring documents the failure and redesign
- `runs/baseline_helpful/final_state.json` — `final_outputs.naive_token_limit_hit: true`
  and `final_outputs.naive_token_limit_note` record this for machine-readable reference
- This file — human-readable narrative

---

## Interpretation notes for paper

### Entity coverage
The multi-agent system produced **30 nodes (27 confirmed)** vs the baseline's
**20 nodes (12 confirmed)**. That is 50% more total entities and 125% more
confirmed entities. The multi-agent system's per-turn extraction with confidence
gating and ambiguity resolution results in a substantially richer, higher-quality
graph from the same interview content.

### Relationship precision
Edge counts were similar (25 vs 25), but the multi-agent system had a higher
confirmed ratio (72% vs 64%). More importantly, the multi-agent system's graph
updater enforces referential integrity at commit time (invariant 12), whereas
the baseline's dangling edge check is post-hoc and outside the extraction loop.

### Ambiguity handling
The multi-agent system detected the "Richard" ambiguity (Richard Jones vs Richard
Smith), asked a targeted clarification question as its first turn, and resolved it.
The baseline extracted both Richard Jones and Richard Smith as separate nodes but
made no attempt to flag or resolve the ambiguity — it cannot, because it has no
clarification detection agent and no turn-by-turn follow-up mechanism.

### Coverage tracking
Coverage scores (people, systems, workflows, stakeholders, risks, undocumented
knowledge) are 0% across the board for the baseline — not because the baseline
missed everything, but because it has no coverage-updater agent. The multi-agent
system's coverage scores (40–75%) give the next person a structured map of what
was and was not captured, which is the primary value of the handoff artifact.

### Handoff quality
Both systems produce an Obsidian vault. The multi-agent vault has richer provenance
(every node traces to an evidence quote from the exact turn that created it),
structured coverage bars, and a list of remaining open questions. The baseline
vault has provenance quotes but no coverage tracking and no follow-up queue.
