# Exit Interview → Knowledge Graph

A research prototype that conducts structured exit interviews with departing contractors using a multi-agent LLM panel, then builds a queryable knowledge graph from the results.

**Course:** BIT 5544 · VT Spring 2026  
**Status:** Phases 1–6 complete. Phase 7 (output / Obsidian vault) and live UI not yet built.

---

## The Problem

When a contractor or key employee leaves a project, critical knowledge leaves with them — undocumented workflows, system ownership, relationship context, informal approval chains. Structured exit interviews capture some of this, but the output is usually a transcript that nobody reads.

This prototype turns that transcript into a **living knowledge graph** that can be queried, visualized, and handed to the next person.

---

## How It Works

```
                  ┌─────────────────────────────────────────┐
                  │           SharedInterviewState           │
                  │  graph · turns · coverage · ambiguities  │
                  └────────────────┬────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │        Orchestrator          │
                    │  (rule-based priority ladder)│
                    │  1. Resolve ambiguities      │
                    │  2. Ask seeded questions     │
                    │  3. Probe low-conf nodes     │
                    │  4. Fill coverage gaps       │
                    └──────────────┬──────────────┘
                                   │  next question
                    ┌──────────────▼──────────────┐
                    │       Answer Provider        │
                    │  (human · scripted · future  │
                    │   WebSocket / FastAPI)        │
                    └──────────────┬──────────────┘
                                   │  answer text
          ┌────────────────────────▼────────────────────────┐
          │           Five Agents  (asyncio.gather)          │
          │                                                  │
          │  Entity Extractor    →  who / what was mentioned │
          │  Relationship Extractor  →  edges between them   │
          │  Attribute Extractor  →  facts about entities    │
          │  Clarification Detector  →  follow-up questions  │
          │  Coverage Updater     →  scores per category     │
          └────────────────────────┬────────────────────────┘
                                   │  structured Pydantic outputs
                    ┌──────────────▼──────────────┐
                    │         Graph Mapper         │
                    │  (Python, no LLM)            │
                    │  temp_ids → stable node IDs  │
                    │  skip ambiguous entities     │
                    └──────────────┬──────────────┘
                                   │  NodeUpdateOp / EdgeUpdateOp
                    ┌──────────────▼──────────────┐
                    │      Graph Updater           │
                    │  ONLY module that writes     │
                    │  to the canonical graph      │
                    │  provisional → confirmed     │
                    └─────────────────────────────┘
```

Each turn is one question → one answer → five parallel LLM analyses → graph commit. The loop runs until `max_turns` is reached or a `should_stop` condition fires.

---

## Project Structure

```
app/
  agents/
    llm_client.py           # Shared instructor-wrapped Anthropic client
    orchestrator.py         # Rule-based question selector (no LLM)
    entity_extractor.py     # LLM agent: extract named entities
    relationship_extractor.py  # LLM agent: extract relationships
    attribute_extractor.py  # LLM agent: extract factual attributes
    clarification_detector.py  # LLM agent: flag gaps & ambiguities
    coverage_updater.py     # LLM agent: score knowledge coverage
    graph_mapper.py         # Python: translate extractions → graph ops
    stubs.py                # Fast no-LLM stubs (used in CI tests)
    prompts/                # Versioned system prompts (.md files)
  core/
    models.py               # All Pydantic models: state, agent I/O
  graph/
    schema.py               # GraphNode, GraphEdge, KnowledgeGraph
    updater.py              # The only module allowed to mutate the graph
  ingestion/
    loaders.py              # Loads initial_state.json into SharedInterviewState
    dummy_data/
      initial_state.json    # Seeded Project Falcon scenario
  interview/
    turn_loop.py            # run_turn() and run_interview() entry points

tests/
  unit/                     # Pure logic, no I/O (models, loader, updater, orchestrator)
  contracts/                # Agent output schema validation (mocked LLM)
  integration/              # Full pipeline with stub agents (no API key needed)
  golden/                   # Live LLM evaluation — requires ANTHROPIC_API_KEY
  fixtures/
    golden_interviews/      # Scripted transcripts + expected graph assertions

eval/
  run_golden_eval.py        # Standalone evaluation script with human-readable report
```

---

## Quickstart

### 1. Install

```bash
pip install -e ".[dev]"
```

### 2. Set your API key

Copy `.env` (already in the repo root) and paste your key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

The app loads this automatically. The `.env` file is gitignored — it will never be committed.

### 3. Run the test suite (no API key needed)

```bash
pytest                        # 159 tests, ~2.7s
pytest -m unit                # pure logic only
pytest -m integration         # full pipeline with stub agents
pytest -m contract            # agent schema validation
```

### 4. Run the live evaluation (API key required)

```bash
python -m eval.run_golden_eval
```

This runs two scripted interviews through the real LLM agents and prints a turn-by-turn extraction report plus pass/fail assertions against expected graph outcomes.

---

## The Knowledge Graph

### Node types
`Person · Role · Team · Project · Client · System · Document · Workflow · Task · Decision · Risk · Issue`

### Relationship types
`WORKS_ON · REPORTS_TO · COMMUNICATES_WITH · OWNS · SUPPORTS · USES · DEPENDS_ON · APPROVES · DOCUMENTS · ESCALATES_TO · BLOCKED_BY · AFFECTS · RELATED_TO`

### Node lifecycle
```
provisional  →  confirmed   (confidence ≥ 0.80, via updater only)
confirmed    →  superseded  (on contradiction; history preserved)
```

Nodes below confidence 0.50 are rejected outright. Everything between 0.50 and 0.80 stays provisional until corroborated.

### Coverage categories
The system tracks how thoroughly six knowledge areas have been covered:
`people · stakeholders · systems · workflows · risks · undocumented_knowledge`

---

## The Seeded Scenario (Project Falcon)

The `initial_state.json` file provides a realistic starting point:

- **13 nodes** already in the graph (6 confirmed, 7 provisional)
- **9 edges** representing known relationships
- **1 seeded ambiguity**: two people share the alias "Richard" — the orchestrator's first question always resolves this
- **3 seeded open questions** targeting the three biggest known gaps (workflow approval path, pipeline ownership, escalation procedure)
- **0 coverage** on all six categories — everything needs to be earned through the interview

The scenario is a data analytics contractor (Alex Miller) departing a project with NorthStar Corp as the client.

---

## What's Working

| Component | Status | Notes |
|---|---|---|
| Pydantic data models | ✅ Complete | All agent I/O contracts enforced |
| Static initial state loader | ✅ Complete | JSON → SharedInterviewState |
| Graph updater | ✅ Complete | Confidence thresholds, provenance, supersede logic |
| Rule-based orchestrator | ✅ Complete | 4-tier priority ladder, deterministic question IDs |
| Async turn loop | ✅ Complete | 5 agents in parallel via asyncio.gather |
| LLM specialist agents | ✅ Complete | instructor + Anthropic, structured Pydantic outputs |
| Ambiguity resolution | ✅ Complete | Auto-resolves when interviewee names a candidate |
| Graph mapper | ✅ Complete | Deterministic Python, skips ambiguous entities |
| Golden eval framework | ✅ Complete | 2 scenarios, 11 live tests, eval report script |
| Unit + integration tests | ✅ 159 passing | CI runs without API key |

---

## What Needs Work

This is a research prototype. The following areas need team input before it could be considered production-ready.

### Phase 7 — Output Layer (not built)

The spec calls for a `vault_compiler.py` that runs *after* the interview ends and writes the knowledge graph to an Obsidian vault as interlinked Markdown files. Nothing is currently persisted to disk — the final `SharedInterviewState` only lives in memory. At minimum we need:

- JSON export of the final graph and transcript after each session
- A simple report (coverage scores, new nodes created, unresolved ambiguities)
- The Obsidian compiler (post-processing only — must not run during the live turn loop)

### Tuning — Thresholds and Prompts

Several values are hardcoded that should be validated against real interview data:

| Parameter | Current value | File | Question |
|---|---|---|---|
| `CONFIRMED_THRESHOLD` | 0.80 | `updater.py` | Is 80% the right bar? |
| `INSUFFICIENT_THRESHOLD` | 0.50 | `updater.py` | Should weak nodes be kept longer? |
| `STUB_DELAY_SECONDS` | 0.02s | `stubs.py` | Calibrate against real LLM latency |
| LLM model | `claude-haiku-4-5` | `llm_client.py` | Haiku vs Sonnet tradeoff on extraction quality |
| Max turns default | 12 | `turn_loop.py` | Too few? Too many? |
| Coverage increment size | 0.05–0.20 | `prompts/coverage_updater.md` | LLM decides — validate against ground truth |

The five system prompts in `app/agents/prompts/` are the primary levers for extraction quality. The golden eval framework (`eval/run_golden_eval.py`) is the right tool for measuring the effect of prompt changes — run it before and after any prompt edit.

### Live Turn-Based Interaction (not built)

The `run_interview()` function accepts any callable as `answer_provider`. The scripted provider used in tests just returns pre-written strings. A real session needs:

- A FastAPI WebSocket endpoint that drives `run_turn()` and streams the question to a human
- A simple CLI REPL for local testing (`input()` → `answer_provider`)
- Session persistence so an interview can be paused and resumed

### The Clarification Loop (partially working)

The clarification detector correctly identifies when answers are vague and generates follow-up questions. These are appended to `state.open_questions`. However:

- The orchestrator treats clarification questions identically to seeded questions — they compete on priority rather than being asked immediately
- There is no mechanism to interrupt the current question queue and surface a clarification right away
- Resolved ambiguities are detected heuristically (label substring match) — this will fail on nicknames and informal references

### Longer and More Varied Scenarios

The current golden fixtures cover 4-turn interviews. Real exit interviews run 30–60 minutes. We need:

- Longer scripted transcripts (10+ turns) to stress-test the orchestrator's question diversity
- Scenarios that introduce contradictions (interviewee corrects themselves between turns)
- Scenarios with multiple interviewees where graphs need to be merged
- Edge cases: interviewee mentions an entity already in the graph under a different name (fuzzy matching)

---

## Architecture Constraints (Do Not Break These)

These were defined upfront and the entire test suite enforces them:

1. **Agents never see the full state** — each agent receives only the slice of data it needs (`turn + existing_aliases`, not `SharedInterviewState`)
2. **Five agents always run concurrently** — `asyncio.gather` in `turn_loop.py`; never sequential
3. **Only `updater.py` writes to the graph** — agents propose, the updater commits
4. **`instructor` enforces structured output** — no prompt-only JSON, Pydantic validates every response
5. **No document parsing during the live loop** — `initial_state.json` is pre-built; the vault compiler runs after
6. **Obsidian output is post-processing only** — no Markdown I/O during a live session

---

## Running a Quick End-to-End Check

```bash
# No API key needed — uses fast stubs
python -c "
import asyncio
from app.core.models import Interviewee
from app.ingestion.loaders import load_initial_state
from app.interview.turn_loop import run_interview
from app.agents.stubs import (
    extract_entities, extract_relationships, extract_attributes,
    detect_clarifications, update_coverage, map_to_graph_updates,
)
import app.interview.turn_loop as tl

# Patch to stubs
tl.extract_entities = extract_entities
tl.extract_relationships = extract_relationships
tl.extract_attributes = extract_attributes
tl.detect_clarifications = detect_clarifications
tl.update_coverage = update_coverage
tl.map_to_graph_updates = map_to_graph_updates

interviewee = Interviewee(name='Alex Miller', role='Contractor', project_ids=['project_falcon'])
state = load_initial_state(interviewee)

answers = iter(['Richard Jones, client side.', 'Jordan approves, then Richard Jones signs off.', 'Sarah Chen owns the pipeline.', 'Risk: no runbook exists.'])
results = asyncio.run(run_interview(state, lambda _: next(answers), max_turns=4))

print(f'Turns completed: {len(results)}')
print(f'Nodes in graph: {len(state.graph.nodes)}')
print(f'Coverage: {state.coverage}')
print(f'Richard ambiguity resolved: {state.ambiguities[0].resolved}')
"
```

---

## Key Files to Read First

If you're new to the codebase, read these in order:

1. [`app/core/models.py`](app/core/models.py) — every data structure the system uses
2. [`app/graph/schema.py`](app/graph/schema.py) — the graph node/edge contracts
3. [`app/ingestion/dummy_data/initial_state.json`](app/ingestion/dummy_data/initial_state.json) — the concrete scenario we're working with
4. [`app/interview/turn_loop.py`](app/interview/turn_loop.py) — the main loop; ~200 lines
5. [`app/agents/orchestrator.py`](app/agents/orchestrator.py) — how questions are selected
6. [`app/graph/updater.py`](app/graph/updater.py) — how the graph is mutated safely

The test files mirror this structure and are the fastest way to understand what each component does and does not guarantee.
