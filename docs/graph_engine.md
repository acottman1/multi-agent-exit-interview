# Graph Engine Reference (v1.0)

The graph engine is the original implementation of this tool. It is preserved alongside the brief engine for academic comparison purposes — both engines run on the same interview infrastructure but produce different output artifacts.

For the current version of the tool, see the [main README](../README.md).  
For the design rationale behind the pivot to the brief engine, see [project_narrative.md](project_narrative.md).

---

## What the Graph Engine Does

The graph engine conducts the same structured interview as the brief engine, but instead of producing a Role Brief document, it builds a **knowledge graph** — a network of typed nodes and edges extracted from the conversation. The output is an Obsidian vault containing one Markdown file per graph node, linked together so a reader can navigate from a person to the systems they owned to the workflows that depended on those systems.

The graph answers *what entities and relationships exist in this domain.* The brief engine answers *what does this specific person do, and what will break when they leave.* See [project_narrative.md](project_narrative.md) for a full explanation of why the brief engine was developed.

---

## Running the Graph Engine

```bash
python run_interview.py --engine graph --name "Alex Rivera" --role "Data Engineer" --project falcon
```

The `--project` flag loads a pre-seeded scenario with an existing partial graph and open questions. Available seed projects:

| Slug | Description |
|---|---|
| `falcon` | Project Falcon — data analytics contractor (NorthStar Corp client) |
| `erp` | ERP modernization |
| `cloud` | Cloud migration support |
| `data` | Data platform (Airflow / dbt) |
| `soc2` | SOC 2 cybersecurity compliance |
| `onboarding` | Client onboarding operations |

If you omit `--project`, the interview starts with an empty graph.

---

## The Seeded Scenario (Project Falcon)

The `falcon` project is the primary development and evaluation scenario. The seed (`app/ingestion/dummy_data/initial_state.json`) contains:

- **13 nodes** pre-loaded (6 confirmed, 7 provisional)
- **9 edges** representing known relationships
- **1 seeded ambiguity**: two people share the alias "Richard" — the orchestrator's first question always resolves this
- **3 seeded open questions** targeting the three biggest known gaps (workflow approval path, pipeline ownership, escalation procedure)
- **0 coverage** on all six categories — everything must be earned through the interview

---

## How It Works

```
              ┌──────────────────────────────────────┐
              │          SharedInterviewState          │
              │  graph · turns · coverage · ambig.    │
              └───────────────┬──────────────────────┘
                              │
                ┌─────────────▼────────────┐
                │        Orchestrator        │
                │  rule-based priority:      │
                │  1. Resolve ambiguities    │
                │  2. Seeded open questions  │
                │  3. Probe low-conf nodes   │
                │  4. Coverage gap fallback  │
                └─────────────┬────────────┘
                              │  next question
        ┌─────────────────────▼───────────────────┐
        │          Five Agents  (run in parallel)   │
        │                                          │
        │  Entity Extractor    →  who / what        │
        │  Relationship Extractor  →  edges         │
        │  Attribute Extractor  →  facts on nodes   │
        │  Clarification Detector  →  follow-ups    │
        │  Coverage Updater     →  category scores  │
        └─────────────────────┬───────────────────┘
                              │  structured outputs
                ┌─────────────▼────────────┐
                │       Graph Mapper         │
                │  (pure Python, no LLM)     │
                │  temp IDs → stable IDs     │
                │  skips ambiguous entities  │
                └─────────────┬────────────┘
                ┌─────────────▼────────────┐
                │      Graph Updater         │
                │  the only module that      │
                │  writes to the graph       │
                │  provisional → confirmed   │
                └──────────────────────────┘
```

---

## Graph Vocabulary

### Node types
`Person · Role · Team · Project · Client · System · Document · Workflow · Task · Decision · Risk · Issue`

### Relationship types
`WORKS_ON · REPORTS_TO · COMMUNICATES_WITH · OWNS · SUPPORTS · USES · DEPENDS_ON · APPROVES · DOCUMENTS · ESCALATES_TO · BLOCKED_BY · AFFECTS · RELATED_TO`

### Node lifecycle

```
provisional  →  confirmed   (confidence ≥ 0.80, via updater only)
confirmed    →  superseded  (on contradiction; history preserved)
```

Nodes below 0.50 confidence are rejected outright. Nodes between 0.50 and 0.80 stay provisional until corroborated by a later turn.

### Coverage categories (fixed — not configurable)
`people · stakeholders · systems · workflows · risks · undocumented_knowledge`

---

## Output

The graph engine writes output to `runs/<name-slug>/` by default.

| File / Directory | Contents |
|---|---|
| `final_state.json` | Full session state: turns, complete knowledge graph, coverage scores. Resumable. |
| `exit_interview_vault/` | One Markdown file per graph node, organized into subdirectories by node type. Open in Obsidian for linked navigation. |

### Merging runs from the same project

If you ran multiple graph engine sessions that cover the same project, merge them before opening in Obsidian to avoid duplicate nodes:

```bash
python merge_graphs.py \
  runs/session1/final_state.json \
  runs/session2/final_state.json \
  --name "Project Falcon" \
  --out runs/merged/falcon/
```

See [dev_notes.md](dev_notes.md) for a detailed explanation of why duplicate nodes occur and how merging resolves them.

---

## Running a Quick End-to-End Check (no API key)

```bash
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

tl.extract_entities = extract_entities
tl.extract_relationships = extract_relationships
tl.extract_attributes = extract_attributes
tl.detect_clarifications = detect_clarifications
tl.update_coverage = update_coverage
tl.map_to_graph_updates = map_to_graph_updates

interviewee = Interviewee(name='Alex Miller', role='Contractor', project_ids=['project_falcon'])
state = load_initial_state(interviewee)
answers = iter(['Richard Jones, client side.', 'Jordan approves.', 'Sarah owns the pipeline.', 'No runbook exists.'])
results = asyncio.run(run_interview(state, lambda _: next(answers), max_turns=4))

print(f'Turns: {len(results)}, Nodes: {len(state.graph.nodes)}')
print(f'Coverage: {state.coverage}')
print(f'Richard ambiguity resolved: {state.ambiguities[0].resolved}')
"
```

---

## Key Source Files

| File | Role |
|---|---|
| `app/graph/schema.py` | `GraphNode`, `GraphEdge`, `KnowledgeGraph`, all node/relationship/status types |
| `app/graph/updater.py` | `apply_proposed_update()` — the only function that writes to the graph |
| `app/graph/merger.py` | Merges two `KnowledgeGraph` objects from separate sessions |
| `app/interview/turn_loop.py` | `run_turn()` and `run_interview()` |
| `app/agents/orchestrator.py` | `select_next_question()` — rule-based 4-tier priority ladder |
| `app/agents/entity_extractor.py` | Extracts `GraphNode` candidates |
| `app/agents/relationship_extractor.py` | Extracts `GraphEdge` candidates |
| `app/agents/attribute_extractor.py` | Updates attributes on existing nodes |
| `app/agents/coverage_updater.py` | Scores the six fixed coverage categories |
| `app/agents/graph_mapper.py` | Pure Python: translates extraction outputs → `NodeUpdateOp` / `EdgeUpdateOp` |
| `app/ingestion/dummy_data/initial_state.json` | The Project Falcon seed scenario |
| `merge_graphs.py` | CLI utility for merging graph output from multiple sessions |

---

## Status

| Component | Status | Notes |
|---|---|---|
| Graph schema | ✅ Complete | 12 node types, 13 relationship types, 3 lifecycle states |
| Graph updater | ✅ Complete | Confidence thresholds (0.50 / 0.80), provenance, supersede logic |
| Rule-based orchestrator | ✅ Complete | 4-tier priority ladder, deterministic question IDs |
| Graph engine turn loop | ✅ Complete | 5 agents in parallel via asyncio.gather |
| LLM extraction agents | ✅ Complete | Entity, relationship, attribute, clarification, coverage |
| Graph mapper | ✅ Complete | Deterministic Python, no LLM |
| Vault compiler (graph) | ✅ Complete | Per-node Obsidian output |
| Ambiguity resolution | ✅ Complete | Auto-resolves when interviewee names a candidate |
| Session resume | ✅ Complete | `final_state.json` → reload and continue |
| Graph merge utility | ✅ Complete | `merge_graphs.py` |

---

## Known Issues

See [dev_notes.md](dev_notes.md) for full details.

**Duplicate nodes within a single run** — the entity extractor sometimes creates separate nodes for the same real-world entity when it is referred to by different labels across turns (e.g., "Marcus Wright" in turn 1 vs "VP of Data" in turn 3). The graph mapper generates stable IDs from the label, so different labels produce different node IDs. The correct fix is to make the entity extractor check `existing_aliases` more aggressively before minting new nodes. Not yet applied.

**Multiple vault directories indexed by Obsidian** — if you open your Obsidian vault above `runs/`, all run subdirectories are indexed simultaneously, causing shared entities to appear once per run. Fix: use `merge_graphs.py` on same-project runs and open only the merged vault.
