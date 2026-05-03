# Exit Interview Knowledge Elicitation Tool — Codebase Guide

**For:** Claude Code sessions and new developers  
**Start here:** [README.md](README.md) for user-facing docs and quickstart. This file covers the architecture and where things live.

---

## Project Summary

A research prototype conducting structured exit interviews using a multi-agent LLM panel. Two parallel engines ship together:

- **Brief Engine (v2.0, primary)** — extracts to a `RoleBrief`: structured sections for responsibilities, people, systems, implicit knowledge, risks, and hiring profile. Config-driven; adaptable to any knowledge-elicitation domain.
- **Graph Engine (v1.0, preserved for comparison)** — extracts to a `KnowledgeGraph` of typed nodes and edges. Used for academic comparison study.

Both engines share the same turn-loop infrastructure, LLM client, and Obsidian vault compiler.

**Authoritative spec:** `knowledge_graph_exit_interview_project_spec.md` Section 22.  
**Course:** BIT 5544 · VT Spring 2026

---

## 🛑 Architectural Constraints (CRITICAL — Tests Enforce These)

<rules>
1. **Never write code ahead of the current Phase.** We are building strictly phase-by-phase (see `knowledge_graph_exit_interview_project_spec.md` Section 22).
2. **Enforce Async Parallelism:** All specialist agents MUST be called concurrently via `asyncio.gather` in the turn loop. Never sequential. Brief engine: 6 agents. Graph engine: 5 agents.
3. **Restrict the Ingestion Layer:** Do not build a complex document parser for dummy data. Use static `initial_state.json` / `context_briefing.json` that already conform to the Pydantic models.
4. **Limit Token Payloads:** Do not pass the entire `SharedInterviewState` or `BriefSessionState` to every agent. Pass only the specific slices each agent needs.
5. **Strict Pydantic Enforcement:** Use the `instructor` library to enforce structured Pydantic model outputs from the LLM. Prompt engineering alone is insufficient.
6. **Obsidian as Post-Processing Only:** `vault_compiler.py` MUST run after the interview ends. Do not read/write Markdown files during the live turn loop.
7. **Graph Mutations:** Graph agents propose updates into `proposed_updates`. ONLY `app/graph/updater.py` may promote items to `confirmed`. ONLY `app/brief/updater.py` may write to `RoleBrief` sections.
</rules>

---

## Common Commands

```bash
# Install
pip install -e ".[dev]"

# Brief engine (primary)
python run_interview.py --engine brief --name "Jordan Kim" --role "Data Engineer"
python run_interview.py --engine brief --name "Jordan Kim" --role "Data Engineer" --config exit_interview
python run_interview.py --engine brief --name "Jordan Kim" --role "Data Engineer" --new-config

# Graph engine (comparison)
python run_interview.py --engine graph --name "Alex Miller" --role "Contractor" --project falcon
python run_interview.py --engine graph --name "Alex Miller" --role "Contractor" --max-turns 20

# Tests
pytest                          # all ~159 tests
pytest -m unit                  # pure logic, no I/O
pytest -m contract              # agent schema validation (mocked LLM)
pytest -m integration           # full pipeline with stub agents
pytest -m eval                  # live LLM — requires ANTHROPIC_API_KEY

# Golden evaluation
python -m eval.run_golden_eval

# Merge graph engine runs (fix duplicate Obsidian nodes)
python merge_graphs.py runs/session1/final_state.json runs/session2/final_state.json \
  --name "Project Falcon" --out runs/merged/
```

---

## Architecture Map

### Entry Point

**`run_interview.py`** — CLI. Parses flags, picks engine, loads interviewee, routes to `run_brief_interview()` or `run_interview()`.

### Brief Engine (v2.0) — Primary

| File | Role |
|---|---|
| `app/brief/schema.py` | `RoleBrief`, `Responsibility`, `BriefPerson`, `BriefSystem`, `ImplicitKnowledgeItem`, `BriefRisk` |
| `app/brief/session.py` | `BriefSessionState` — runtime container (brief + coverage + turns + ambiguities + domain_config) |
| `app/brief/updater.py` | `merge_into_brief()` — ONLY function that writes to `RoleBrief`. Deduplicates by `dedup_key`, unions list fields |
| `app/brief/extraction_models.py` | Pydantic I/O wrappers for each extraction agent |
| `app/interview/brief_turn_loop.py` | `run_brief_turn()` and `run_brief_interview()` — 6 agents via `asyncio.gather` |
| `app/agents/brief_orchestrator.py` | `select_brief_question()` — config-driven priority: ambiguities → pre-seeded → mandatory gaps → general gaps |
| `app/agents/responsibility_extractor.py` | Extracts `Responsibility` items |
| `app/agents/people_extractor.py` | Extracts `BriefPerson` items |
| `app/agents/systems_extractor.py` | Extracts `BriefSystem` items |
| `app/agents/implicit_knowledge_extractor.py` | Extracts `ImplicitKnowledgeItem` items |
| `app/agents/risk_extractor.py` | Extracts `BriefRisk` items |
| `app/agents/clarification_detector.py` | Both engines — detects ambiguities, generates follow-up questions |

### Graph Engine (v1.0) — Comparison

| File | Role |
|---|---|
| `app/graph/schema.py` | `GraphNode`, `GraphEdge`, `KnowledgeGraph`, `NodeType` (12), `RelationshipType` (13), `NodeStatus` |
| `app/graph/updater.py` | `apply_proposed_update()` — ONLY graph mutation. Thresholds: reject <0.50, provisional 0.50–0.79, confirm ≥0.80 |
| `app/graph/merger.py` | Merge `KnowledgeGraph` objects from multiple sessions |
| `app/interview/turn_loop.py` | `run_turn()` and `run_interview()` — 5 agents via `asyncio.gather` |
| `app/agents/orchestrator.py` | `select_next_question()` — 4-tier rule-based ladder: ambiguities → seeded open_questions → low-confidence nodes → `_FALLBACK_VARIANTS` |
| `app/agents/entity_extractor.py` | Extracts `GraphNode` candidates |
| `app/agents/relationship_extractor.py` | Extracts `GraphEdge` candidates |
| `app/agents/attribute_extractor.py` | Updates attributes on existing nodes |
| `app/agents/coverage_updater.py` | Scores the six fixed coverage categories |
| `app/agents/graph_mapper.py` | Pure Python: translates extraction outputs → `NodeUpdateOp` / `EdgeUpdateOp`. No LLM. |

### Shared Infrastructure

| File | Role |
|---|---|
| `app/core/models.py` | All shared Pydantic models: `Interviewee`, `InterviewTurn`, `OpenQuestion`, `Ambiguity`, `CoverageScores`, `SharedInterviewState` |
| `app/agents/llm_client.py` | `instructor`-wrapped Anthropic client. Defaults to `claude-haiku-4-5-20251001`; override via `ANTHROPIC_MODEL` env var |
| `app/agents/stubs.py` | No-LLM stubs for CI — fast deterministic replacements for all agents |
| `app/ingestion/loaders.py` | `load_initial_state()` (graph seed) and `load_context_briefing()` (brief preload) |
| `app/vault/vault_compiler.py` | `compile_vault()` (graph → per-node Obsidian) and `compile_brief_vault()` (brief → single Markdown) |
| `app/agents/prompts/` | Versioned system prompts as `.md` files, one per agent. Edit here to tune extraction; measure with `eval.run_golden_eval` |

### Config System (Brief Engine)

| File | Role |
|---|---|
| `app/config/domain_config.py` | `DomainConfig` schema: `CoverageCategory` (name, mandatory, min_score, weight), `SectionTarget`, question banks |
| `app/config/context_briefing.py` | `ContextBriefing` — lightweight preload context |
| `app/config/config_store.py` | `save_domain_config()`, `load_domain_config()`, `list_domain_configs()` → JSON in `app/config/instances/` |
| `app/config/instances/exit_interview.json` | Built-in exit interview config (7 categories, question banks, extraction targets) |

### Meta-Interview (Config Generation)

| File | Role |
|---|---|
| `app/meta/meta_interview.py` | Entry point for `--new-config` flow |
| `app/meta/meta_loop.py` | Interactive 8-question loop |
| `app/meta/config_generator.py` | LLM: generate `DomainConfig` from meta-answers |
| `app/meta/config_reviewer.py` | LLM: critique and refine |
| `app/meta/config_validator.py` | LLM: validate coherence before saving |
| `app/meta/meta_questions.json` | The 8 meta-questions |

---

## Test Structure

| Directory | Marker | What it tests | Needs API key |
|---|---|---|---|
| `tests/unit/` | `unit` | Pure logic, no I/O | No |
| `tests/contracts/` | `contract` | Agent Pydantic output contracts (mocked LLM) | No |
| `tests/integration/` | `integration` | Full turn-loop pipeline with stubs | No |
| `tests/golden/` | `eval` | Live LLM extraction against scripted fixtures | Yes |

**Golden fixtures** (`tests/fixtures/golden_interviews/`):  
`helpful_alex`, `vague_jordan`, `technical_aisha`, `timid_noah`, `cooperative_lena`, `negative_victor`, `vague_sofia`

Each fixture is a scripted interview (4+ turns) with expected graph/brief assertions. These are the primary regression test for extraction quality.

---

## Data Model Quick Reference

### Brief Engine State

```
BriefSessionState
├── domain_config: DomainConfig
├── brief: RoleBrief
│   ├── role_summary: str
│   ├── responsibilities: list[Responsibility]   ← dedup_key = title slug
│   ├── people: list[BriefPerson]                ← dedup_key = name slug
│   ├── systems: list[BriefSystem]               ← dedup_key = name slug
│   ├── implicit_knowledge: list[ImplicitKnowledgeItem]
│   ├── risks: list[BriefRisk]                   ← dedup_key = title slug
│   └── hiring_profile: str
├── coverage: dict[str, float]     ← keyed by DomainConfig category names
├── turns: list[InterviewTurn]
└── ambiguities: list[Ambiguity]
```

### Graph Engine State

```
SharedInterviewState
├── graph: KnowledgeGraph
│   ├── nodes: dict[str, GraphNode]   ← key = stable ID: "{type}_{label_slug}"
│   └── edges: dict[str, GraphEdge]
├── coverage: CoverageScores           ← 6 fixed float fields
├── turns: list[InterviewTurn]
├── open_questions: list[OpenQuestion]
└── ambiguities: list[Ambiguity]
```

---

## Key Invariants

- **Brief dedup keys** are slug-normalized (lowercase, spaces→underscores). The updater matches on these before inserting new items.
- **Graph stable IDs** are `{node_type_slug}_{label_slug}`. If the entity extractor uses different labels across turns, duplicate nodes are created — known limitation (see [docs/dev_notes.md](docs/dev_notes.md)).
- **Graph confidence thresholds** are in `app/graph/updater.py`: `INSUFFICIENT_THRESHOLD = 0.50`, `CONFIRMED_THRESHOLD = 0.80`.
- **Coverage is config-driven** in the brief engine. Categories, min scores, and mandatory flags come from `DomainConfig`, not hardcoded constants.
- **`_FALLBACK_VARIANTS`** in `app/agents/orchestrator.py` is the graph engine's hardcoded question bank. The brief engine replaces this with `DomainConfig.question_banks`.
- **System prompts** live in `app/agents/prompts/<agent_name>.md`. Tuning prompts is the primary lever for improving extraction quality.

---

## Known Issues

Full details in [docs/dev_notes.md](docs/dev_notes.md). Summary:

1. **Duplicate graph nodes** — same real-world entity extracted under different labels across turns (e.g., "Marcus Wright" vs "VP of Data"). Fix direction: tighten entity extractor prompt to check `existing_aliases` before minting new nodes.

2. **Multiple vault directories indexed by Obsidian** — opening Obsidian above `runs/` causes all run subdirectories to be indexed simultaneously. Fix: use `merge_graphs.py` on same-project runs.

3. **Clarification priority** — clarification questions compete with seeded questions rather than interrupting immediately.

4. **Coverage circularity (graph engine)** — coverage is measured against the graph itself, not ground truth.

---

## Documentation Index

| Document | What it contains |
|---|---|
| [README.md](README.md) | User guide, quickstart, scenarios, CLI reference, output reference, project structure (brief engine) |
| [CLAUDE.md](CLAUDE.md) | (this file) Architecture map, commands, data models, invariants |
| [docs/graph_engine.md](docs/graph_engine.md) | Graph engine (v1.0) reference: how to run, vocabulary, output format, known issues |
| [docs/project_narrative.md](docs/project_narrative.md) | Design history — why the project pivoted from graph to brief engine |
| [docs/dev_notes.md](docs/dev_notes.md) | Raw dev observations: duplicate nodes, failure modes |
| [knowledge_graph_exit_interview_project_spec.md](knowledge_graph_exit_interview_project_spec.md) | Full technical specification, all phases |
