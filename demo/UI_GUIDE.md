# Demo UI — Handoff Notes for Jessica

Your initial prototype is the right foundation — the step-through pattern, the scripted/live
toggle, the three-panel layout. This note covers what changed in the system so you have
enough context to take it from there.

---

## What changed between the two versions

The core shift: **one model call per turn became five parallel model calls**, and their
outputs now write to a growing knowledge graph instead of just producing text.

In the initial prototype, each step produced a cue, some follow-up questions, and a summary.

In this version, each step produces all of the following simultaneously:

| Agent | What it finds |
|---|---|
| Entity Extractor | People, systems, teams, documents mentioned — each with a confidence score |
| Relationship Extractor | Edges between those entities (e.g. "Alex OWNS Snowflake pipeline") |
| Attribute Extractor | Factual details about entities (e.g. "severity: high", "owner: unknown") |
| Clarification Detector | Follow-up questions the system wants to ask, with priority |
| Coverage Updater | How much the answer moved the needle on six knowledge categories |

Then a sixth step (the Graph Updater) decides which findings are strong enough to commit to
the knowledge graph, and which stay provisional until corroborated by a later turn.

---

## The new thing: a knowledge graph that builds up over turns

The interview starts with 13 nodes and 9 edges already loaded from a pre-built scenario
("Project Falcon" — a contractor named Alex Miller leaving a data analytics project). Each
turn adds more. Nodes are either `confirmed` (confidence ≥ 80%) or `provisional` (waiting).

There is a built-in ambiguity baked into the starting state: two people share the name
"Richard" and the system has to resolve which one is being referenced in a ticket comment.
The orchestrator's first question always targets this. It is a good moment to highlight in
the demo.

---

## What the demo should make visible

These are the four things the class needs to see to understand what the system is doing:

1. The orchestrator picks questions strategically and can say why — every question comes with
   a `rationale` and a `target_category`
2. Five agents fire on the same answer and each produces a different structured output
3. The graph accumulates knowledge across turns and confidence levels vary node by node
4. Six coverage scores (people, systems, workflows, stakeholders, risks, undocumented
   knowledge) start at zero and move as the interview progresses

---

## The key files and what they contain

These are the data structures the UI will be working with:

- **`app/interview/turn_loop.py`** — the `TurnResult` class is what the system returns after
  each step. It contains the orchestrator's question selection, the full Q&A turn, all five
  agent outputs, and the graph updater's commit result. Everything the UI would display is
  in here.

- **`app/core/models.py`** — the Pydantic shapes for each agent's output:
  `EntityExtractionOutput`, `RelationshipExtractionOutput`, `ClarificationOutput`,
  `CoverageOutput`, and others.

- **`app/ingestion/dummy_data/initial_state.json`** — the starting graph state, seeded
  questions, and the "Richard" ambiguity. Worth reading to understand what is already known
  before turn 1.

- **`tests/fixtures/golden_interviews/helpful_alex.py`** — a 4-turn scripted interview that
  can drive the demo's scripted mode.

---

## Open design questions

A few things that are genuinely up to you — there is no right answer:

- Should the five agent outputs be revealed progressively per step, or collapsed into an
  expandable accordion?
- Should the graph be a table or a visual network diagram?
- Before/after graph state per turn, or just the current running total?
- Use the `helpful_alex` scripted answers as-is, or write new ones that play better for
  the class?

---

## Phase 7 note

Phase 7 is an Obsidian vault export that runs after the interview and writes Markdown files
to disk — it is not built yet. The demo does not need to surface it. A brief "what's next"
note at the end of the session is enough to set that up for the class discussion.
