# Multi-Agent Exit Interview to Knowledge Graph

## Project specification

## 1. Purpose

Build a research-oriented prototype that uses LLMs to conduct turn-based exit interviews, extract operational project knowledge, and update a graph-shaped knowledge base over the course of the conversation.

This is **not** an enterprise workflow tool and it is **not** a polished production app. The focus is on whether a small panel of specialized LLM agents can do a better job of eliciting, structuring, and validating handoff knowledge than a single generic interviewer.

The core research question is:

> Can a turn-based, multi-agent interview system capture and structure project transition knowledge from departing contractors into a usable graph representation with better coverage and clearer follow-up behavior than a simple single-agent assistant?

---

## 2. Primary outcome

At the end of an interview, the system should produce:

1. an **updated knowledge graph state** or graph-shaped JSON representation
2. a **list of newly discovered or clarified entities and relationships**
3. a **list of unresolved ambiguities and open questions**
4. an **interactive, human-readable handoff summary generated as a local Obsidian Vault** (a directory of linked Markdown files representing the final graph).

---

## 3. Scope and non-goals

### In scope

- loading a hardcoded initial_state.json file representing dummy company project data.
- initializing a partial knowledge graph from that data
- running a turn-based exit interview with one visible interviewer
- using multiple hidden specialist agents to analyze each answer
- updating graph state as the interview progresses
- asking targeted follow-up questions when knowledge is unclear, ambiguous, or graph-incomplete
- tracking provenance and confidence for extracted facts
- producing graph output and a handoff summary

### Out of scope

- voice input or real-time speech transcription
- full enterprise auth, permissions, or audit logging
- real Jira, Git, or email integrations for v1
- polished frontend UX
- advanced database scaling
- full ontology engineering
- broad open-domain knowledge graph construction

### Recommended scope discipline

Build a **small but coherent prototype**. Prefer a simple interface with clear internal logic over a fancy app with shallow reasoning.

---

## 4. Design principles

1. **One visible interviewer, many hidden agents**  
   The interviewee interacts with one assistant. Specialist agents work behind the scenes.

2. **Graph-first validation**  
   A statement is not "good enough" just because it sounds complete in conversation. It must be structured enough to be usable in the graph.

3. **Provisional before confirmed**  
   New facts should first enter the system as candidate graph updates. They become confirmed only after validation or clarifying follow-up.

4. **Every fact has provenance**  
   Each entity, relationship, or property must be traceable to its source, such as an input document or interview turn.

5. **Shared state, not agent chaos**  
   Agents do not maintain separate private versions of reality. They read from and write structured outputs into shared interview state.

6. **Constrained schema over open-ended extraction**  
   A smaller, explicit graph schema is better than an ambitious but vague ontology.

7. **Research over product polish**  
   Time should be spent on agent reasoning, state transitions, graph updates, and evaluation.

---

## 5. System overview

The system has three phases.

### Phase A: Pre-interview ingestion

Input sources such as dummy Jira tickets, commit comments, meeting notes, and documents are processed into an initial project context state.

Output:
- candidate entities
- candidate relationships
- candidate attributes
- confidence scores
- unresolved ambiguities
- initial graph state

### Phase B: Turn-based interview

A visible interviewer asks questions. After each answer, specialist agents analyze the turn, propose structured updates, detect missing details, and recommend follow-up questions.

### Phase C: Post-interview outputs

The final system state is rendered into:
- graph JSON or graph database entries
- unresolved issue list
- onboarding or handoff brief (exported as an Obsidian Vault folder)


---

## 6. Recommended implementation stack

### Preferred stack

- **Python**
- **FastAPI** for backend API
- **Pydantic** for typed models and validation
- **simple HTML/JS frontend** or a minimal React frontend
- **JSON or SQLite-backed graph state** for v1
- optional **Neo4j** only after the JSON graph loop works
- **pytest** for tests

### Why this stack

Python makes it easy to:
- orchestrate prompts and state transitions
- define structured data contracts
- test graph updates
- run repeatable interview fixtures
- keep the implementation readable

### Do not start with

- a full graph database
- a complex frontend framework if the team is not already using it comfortably
- external integrations that increase setup complexity before the core loop works

---

## 7. Minimum viable graph schema

Keep the schema intentionally small.

### Node types

- `Person`
- `Role`
- `Team`
- `Project`
- `Client`
- `System`
- `Document`
- `Workflow`
- `Task`
- `Decision`
- `Risk`
- `Issue`

### Relationship types

- `WORKS_ON`
- `REPORTS_TO`
- `COMMUNICATES_WITH`
- `OWNS`
- `SUPPORTS`
- `USES`
- `DEPENDS_ON`
- `APPROVES`
- `DOCUMENTS`
- `ESCALATES_TO`
- `BLOCKED_BY`
- `AFFECTS`
- `RELATED_TO`

### Required graph metadata

Each node and edge should support:
- `id`
- `type`
- `label` or canonical name
- `status` (`provisional` or `confirmed`)
- `confidence` (0.0 to 1.0)
- `provenance` (source doc or interview turn)
- `created_at`
- `updated_at`

---

## 8. Core invariants

These invariants should guide implementation and testing.

### Conversation invariants

1. There is only **one visible interviewer**.
2. The system asks **one primary question per turn**.
3. A follow-up question must be justified by either ambiguity, contradiction, missing graph fields, or insufficient coverage.
4. The system should avoid repeating a question unless new evidence justifies it.
5. Every asked question should be attributable to a reason in state, such as unresolved entity identity or missing workflow ownership.

### State invariants

6. Shared interview state is the **single source of truth** for the live session.
7. Specialist agents do **not** directly mutate the canonical graph.
8. Only the graph update layer may promote provisional items to confirmed items.
9. Every proposed update must include provenance.
10. Every proposed update must either map to the schema or be rejected with a reason.

### Graph invariants

11. No node or edge can exist without a valid type.
12. No relationship can be committed unless both endpoints exist or are created in the same atomic update.
13. Duplicate entities must be resolved through an explicit entity resolution step, not silently merged.
14. Ambiguous references, such as “Richard,” cannot be auto-confirmed if more than one plausible match exists above a defined threshold.
15. A confirmed fact must have either high confidence or explicit confirmation from the interviewee.
16. Deletions or corrections must preserve prior provenance so the system can explain why a fact changed.

### Evaluation invariants

17. The system must be testable with deterministic fixtures.
18. Prompts should return structured JSON, not free-form paragraphs, for machine-consumed steps.
19. If an agent output fails schema validation, the system should fail gracefully and log the issue instead of corrupting graph state.
20. The system should always be able to produce a final output, even if some facts remain unresolved.

---

## 9. High-level architecture

```text
Dummy company data
    -> ingestion pipeline
    -> initial graph state + unresolved questions
    -> orchestrator asks interview question
    -> interviewee answers
    -> specialist agents analyze turn
    -> candidate graph updates + ambiguity flags + coverage updates
    -> validation and entity resolution
    -> graph commit or follow-up question
    -> repeat until coverage goals met
    -> final graph + handoff summary
```

### Main components

1. **Ingestion layer**
2. **Shared interview state**
3. **Orchestrator**
4. **Specialist agents**
5. **Entity resolution and validation layer**
6. **Graph update service**
7. **Summary generator**

---

## 10. Shared interview state

Use a typed shared state object. This is more important than the UI.
Note: **Token Limit Warning:** Agents should only receive the subset of this state strictly necessary for their function, not the entire graph on every turn.

### Suggested state model

```json
{
  "session_id": "sess_001",
  "interviewee": {
    "name": "Alex Miller",
    "role": "Contractor - Data Analyst",
    "project_ids": ["project_falcon"]
  },
  "graph": {
    "nodes": [],
    "edges": []
  },
  "proposed_updates": [],
  "open_questions": [],
  "ambiguities": [],
  "coverage": {
    "people": 0.0,
    "systems": 0.0,
    "workflows": 0.0,
    "stakeholders": 0.0,
    "risks": 0.0,
    "undocumented_knowledge": 0.0
  },
  "asked_question_ids": [],
  "turns": [],
  "final_outputs": {}
}
```

### Notes

- `proposed_updates` should exist separately from the canonical graph.
- `ambiguities` should have their own explicit structure.
- `coverage` should be estimated with simple heuristics at first.

---

## 11. Specialist agents

Use a small number of agents with narrow responsibilities.

### 11.1 Orchestrator agent

**Purpose:** choose the next best question and manage interview flow.

**Inputs:**
- shared interview state
- current graph
- ambiguities
- coverage scores
- recent conversation history

**Outputs:**
- next question
- rationale for the question
- targeted knowledge category

### 11.2 Entity extraction agent

**Purpose:** identify entities mentioned in the new answer.

**Outputs:**
- candidate entities
- candidate aliases
- supporting evidence spans
- confidence values

### 11.3 Relationship extraction agent

**Purpose:** identify connections between entities.

**Outputs:**
- candidate edges
- source and target references
- relationship type
- confidence
- evidence

### 11.4 Attribute extraction agent

**Purpose:** identify properties of entities or relationships.

**Examples:**
- a person’s role
- system ownership
- workflow frequency
- risk severity

### 11.5 Clarification agent

**Purpose:** detect underspecified, ambiguous, or graph-incomplete statements.

**Examples:**
- ambiguous names
- vague verbs like “handled” or “did stuff with”
- unclear workflow ownership
- missing artifact identity

**Outputs:**
- clarification needs
- suggested follow-up questions
- rationale

### 11.6 Coverage and priority agent

**Purpose:** decide what is worth asking next and what categories remain thin.

**Outputs:**
- priority topics
- low-value details to ignore
- missing categories

### 11.7 Graph mapping agent

**Purpose:** convert extracted information into graph-compatible updates.

**Outputs:**
- node and edge update proposals
- status recommendation (`provisional` or `confirmed`)
- schema mapping rationale

---

## 12. Agent contracts

Each agent should return **strict JSON** matching a typed schema.

### Example entity extraction output

```json
{
  "entities": [
    {
      "temp_id": "ent_tmp_01",
      "type": "Person",
      "label": "Richard",
      "aliases": [],
      "confidence": 0.71,
      "evidence": "I worked with Richard on the client side whenever data definitions changed."
    }
  ]
}
```

### Example clarification output

```json
{
  "clarifications": [
    {
      "kind": "ambiguous_entity",
      "target": "Richard",
      "reason": "Multiple plausible matches exist in current graph state",
      "suggested_question": "You mentioned Richard on the client side. Was that Richard Jones or Richard Smith?",
      "priority": "high"
    }
  ]
}
```

### Example graph mapping output

```json
{
  "node_updates": [
    {
      "op": "upsert",
      "node": {
        "id": "person_richard_jones",
        "type": "Person",
        "label": "Richard Jones",
        "status": "provisional",
        "confidence": 0.82,
        "provenance": ["turn_04"]
      }
    }
  ],
  "edge_updates": [
    {
      "op": "upsert",
      "edge": {
        "id": "edge_001",
        "type": "COMMUNICATES_WITH",
        "source_id": "person_alex_miller",
        "target_id": "person_richard_jones",
        "status": "provisional",
        "confidence": 0.77,
        "provenance": ["turn_04"]
      }
    }
  ]
}
```

---

## 13. Turn processing loop

Each interview turn should follow a fixed lifecycle.

### Turn lifecycle

1. Orchestrator selects next question.
2. Question is shown to the interviewee.
3. Interviewee answer is stored as a new turn.
4. Specialist agents analyze the new answer **asynchronously and in parallel**.
5. Candidate graph updates are generated.
6. Entity resolution checks are performed.
7. Schema validation checks are performed.
8. If critical ambiguities remain, a targeted follow-up is queued.
9. If updates are sufficient, provisional updates are committed.
10. Coverage scores are updated.
11. Interview ends when coverage goals or turn limits are met.

### End conditions

Stop the interview when one or more of these is true:
- core knowledge categories are sufficiently covered
- no high-priority ambiguities remain
- maximum interview turn limit is reached
- marginal value of additional questions falls below a threshold

---

## 14. Entity resolution strategy

Entity resolution is a major source of failure. Keep it explicit.

### Entity resolution rules

1. Prefer exact identifier matches first.
2. Then use canonical name and alias matching.
3. Then use contextual clues such as project membership, role, team, or company side versus client side.
4. If multiple candidates remain plausible, keep the entity provisional and ask a follow-up.
5. Never silently merge ambiguous people.

### Example

If the graph contains:
- Richard Jones, Client Product Owner
- Richard Smith, Internal Program Manager

and the interviewee says:
- “Richard approved the change request.”

then the system must either:
- resolve based on surrounding context with high confidence, or
- ask which Richard is being referenced

---

## 15. Confidence and confirmation model

Use a simple confidence model at first.

### Suggested confidence bands

- `0.00 - 0.49`: insufficient, do not commit without follow-up
- `0.50 - 0.79`: provisional, commit as candidate only
- `0.80 - 1.00`: can be committed as confirmed if not contradicted

### Promotion rules

A fact can move from `provisional` to `confirmed` if:
- the interviewee explicitly confirms it, or
- multiple consistent sources support it, or
- agent confidence is high and no conflicts exist

### Correction rules

If a later turn contradicts a confirmed fact:
- preserve the original provenance
- mark the fact as corrected or superseded
- attach the newer evidence

---

## 16. Interview strategy

The interview should be guided by graph gaps, not by a static questionnaire.

### Core knowledge categories

1. role and responsibilities
2. stakeholders and communication paths
3. systems and artifacts used
4. workflows and real operating procedures
5. dependencies and bottlenecks
6. risks and fragile points
7. undocumented or tacit knowledge
8. transition advice for the next person

### Example question sequence

1. “What were you actually responsible for day to day on Project Falcon?”
2. “Who did you rely on most often on the company side and on the client side?”
3. “Which systems or documents were essential for doing your work?”
4. “What did the actual workflow look like when a requirement changed?”
5. “What usually broke or caused delays?”
6. “What important things were never written down?”

---

## 17. Data fixtures for the prototype

Do not wait for real company data. Create a realistic dummy project space.

### Dummy data package should include

- project roster
- org chart fragment
- a few Jira-like tickets
- a few Git or PR comments
- one short handoff doc
- one short meeting note
- one email-like exchange summary
(Note: For Phase 1 & 2, do not attempt to build a raw text parser for these documents. Hardcode their extracted contents directly into an initial_state.json file that matches the graph schema to simulate the result of a pre-built ingestion pipeline).

### Why

This gives the ingestion layer enough material to:
- seed the graph
- introduce ambiguity
- test entity resolution
- create missing-context follow-up opportunities

---

## 18. Testing strategy

Testing matters because this project will otherwise drift into prompt-only intuition.

### 18.1 Unit tests

Test pure logic and validators.

Examples:
- graph schema validation
- node and edge upsert rules
- confidence band behavior
- entity resolution decision logic
- turn lifecycle transitions
- duplicate detection rules

### 18.2 Contract tests

Test that each agent returns valid structured JSON.

Examples:
- missing required fields should fail validation
- unsupported node types should be rejected
- malformed relationship objects should not enter state

### 18.3 Integration tests

Run end-to-end tests with deterministic transcript fixtures.

Example scenarios:
- clear interview with easy confirmations
- ambiguous person references requiring follow-up
- contradictory statements across turns
- low-value chatter that should be ignored
- missing workflow documentation discovered during interview

### 18.4 Golden-path evaluation tests

Create a few “golden interview” scenarios with expected outputs.

Check whether the system:
- identifies the right major entities
- asks sensible follow-up questions
- avoids obvious duplicate nodes
- produces a usable handoff summary

### 18.5 Manual review rubric

Use a small evaluation rubric for research purposes.

Rate the system on:
- coverage
- precision
- follow-up usefulness
- ambiguity handling
- graph consistency
- handoff usefulness

---

## 19. Best practices to keep the project on track

### Use typed models everywhere

Every important object should have a Pydantic model:
- graph nodes
- graph edges
- agent outputs
- interview turns
- ambiguities
- final report objects

### Keep prompts versioned

Prompts should live in files and be versioned like code.

### Log agent inputs and outputs

Do not rely on memory. Save the JSON request and response for each agent call in dev mode.

### Separate pure logic from LLM calls

All schema validation, graph updates, entity resolution rules, and promotion logic should be plain code, not buried inside prompts.

### Prefer deterministic tests over ad hoc demos

If a behavior matters, create a fixture for it.

### Start with a JSON graph

Only move to Neo4j after the turn loop and graph contracts are stable.

### Avoid overengineering

Do not build:
- plugin architecture
- multi-user session management
- real auth
- admin dashboards
- advanced caching

unless the prototype is already working and there is extra time.

---

## 20. Failure modes to expect

1. **Entity explosion**  
   Too many near-duplicate nodes for the same person or artifact.

2. **Vague verb mapping**  
   Words like “handled,” “worked on,” or “dealt with” do not cleanly map to graph edges.

3. **Over-questioning**  
   The system asks too many clarifications and becomes annoying.

4. **Under-questioning**  
   The system commits vague facts too early.

5. **Prompt drift**  
   Agent output format becomes unstable over time.

6. **Schema mismatch**  
   The interview reveals something useful that the graph cannot represent cleanly.

### Mitigation

- keep schema small but extensible
- track unclear mappings as explicit issues
- tune follow-up thresholds with fixtures
- validate every machine-consumed output

---

## 21. Suggested repository structure

```text
project-root/
  README.md
  pyproject.toml
  app/
    main.py
    api/
      routes_interview.py
      routes_graph.py
    core/
      config.py
      models.py
      state.py
      invariants.py
    graph/
      schema.py
      validators.py
      updater.py
      entity_resolution.py
    agents/
      orchestrator.py
      entity_extractor.py
      relationship_extractor.py
      attribute_extractor.py
      clarification.py
      coverage.py
      graph_mapper.py
      prompts/
        orchestrator.md
        entity_extractor.md
        relationship_extractor.md
        attribute_extractor.md
        clarification.md
        coverage.md
        graph_mapper.md
    ingestion/
      loaders.py
      synthesizer.py
      dummy_data/
    interview/
      turn_loop.py
      stopping.py
      summarizer.py
    utils/
      logging.py
      json_tools.py
  tests/
    unit/
    contracts/
    integration/
    fixtures/
  outputs/
    sample_sessions/
```

---

## 22. Development phases

### Phase 1: Skeleton and data contracts

Build:
- typed models
- JSON graph structure
- dummy data files
- ingestion stubs
- test skeleton

**Definition of done:** all models validate, test harness runs, dummy project data loads.

### Phase 2: Initial graph seeding

Build:
- dummy data ingestion
- candidate entity and relationship extraction from source docs
- initial graph state builder

**Definition of done:** system can create a partial graph from dummy documents.

### Phase 3: Turn loop with one orchestrator

Build:
- interview session state
- question selection loop
- transcript storage
- simple handoff summary

**Definition of done:** one visible assistant can conduct a basic turn-based interview.

### Phase 4: Add specialist agents

Build:
- entity extraction
- relationship extraction
- clarification detection
- graph mapping
- coverage tracking

**Definition of done:** each user answer produces structured proposals and potential follow-up reasons.

### Phase 5: Graph validation and promotion

Build:
- entity resolution
- provisional versus confirmed logic
- atomic graph update service
- contradiction handling

**Definition of done:** graph updates are validated and applied safely.

### Phase 6: Evaluation and tuning

Build:
- golden interview fixtures
- evaluation rubric
- output examples for report/demo

**Definition of done:** the team can demonstrate repeatable behavior and discuss strengths and limitations.

### Phase 7: The Vault Compiler (UI Shortcut)

Build:
- a standalone post-processing script (`vault_compiler.py`)

**Definition of done:** the script successfully parses `final_state.json` and outputs a folder of Markdown files using YAML frontmatter for attributes and `[[wikilinks]]` for relationships, readable by Obsidian.

---

## 23. Suggested acceptance criteria

A successful prototype should be able to:

1. load dummy company records and initialize a partial graph
2. conduct at least one coherent 8 to 15 turn interview
3. identify entities, relationships, and attributes from interview answers
4. detect at least one ambiguity and ask a sensible follow-up question
5. preserve provenance for graph updates
6. keep provisional and confirmed facts separate
7. output a final graph state and a handoff summary
8. pass unit, contract, and at least one end-to-end integration test

---

## 24. Suggested stretch goals

Only attempt these if the core loop is stable.

- simple graph visualization
- Neo4j export
- compare single-agent versus multi-agent behavior
- lightweight retrieval from the evolving graph during the interview
- confidence calibration dashboard for demo purposes

---

## 25. Suggested comparison experiment

To strengthen the academic story, compare:

### Baseline
One interviewer agent that asks questions and summarizes answers.

### Proposed system
One orchestrator plus specialist agents, shared state, graph validation, and follow-up logic.

### Compare on
- entity coverage
- relationship precision
- ambiguity handling
- usefulness of final handoff summary
- number of unsupported or malformed graph updates

This does not need to be a formal publication-grade experiment. Even a careful small comparison will make the project stronger.

---
## 26. Claude Implementation Directives

When using Claude Code, direct it to work in small, testable slices. Furthermore, you must adhere to the following architectural constraints to prevent latency, token bloat, and scope creep:

1. **Enforce Async Parallelism:** When implementing the specialist agents in `agents/` (specifically the `Entity`, `Relationship`, and `Attribute` extractors), they MUST be called asynchronously (e.g., using `asyncio.gather` in Python) so they do not block each other during the turn loop.
2. **Restrict the Ingestion Layer:** Do not build a complex document parser or ETL pipeline for the dummy data. Create a static `initial_state.json` file that already conforms to the Pydantic graph models to simulate ingestion.
3. **Limit Token Payloads:** Do not pass the entire `SharedInterviewState` to every agent. Pass only the specific slices of state (e.g., just the current transcript turn and a list of existing entity aliases) required for their specific task. 
4. **Strict Pydantic Enforcement:** Use native structured outputs or a library like `instructor` to guarantee the LLM returns valid JSON matching the Pydantic models. Do not rely on prompt engineering alone to format the JSON.
5. **Fuzzy Entity Resolution:** Do not attempt to write complex deterministic Python logic for fuzzy string matching in entity resolution. Allow the Entity Extractor agent to return an `is_ambiguous` flag and a list of `possible_matches`, leveraging the LLM for the fuzzy matching but using Pydantic to enforce the schema.
6. **Obsidian as Post-Processing Only:** The Obsidian Vault generation MUST be a standalone script that runs only after the interview is concluded. Do not manage Markdown files during the live conversational turn loop.

---
## 27. Implementation guidance for Claude Code

When using Claude Code, direct it to work in small, testable slices.

### Good prompts to use in Claude Code

- “Create the typed models for graph nodes, graph edges, interview turns, and agent outputs.”
- “Implement the shared interview state and write unit tests for state transitions.”
- “Build the graph update service with validation and provenance preservation.”
- “Implement the entity resolution module with tests for ambiguous person names.”
- “Add the turn loop that stores transcript turns and calls stubbed agents.”
- “Create contract tests that validate structured JSON returned by agent wrappers.”

### Do not ask Claude Code to do all of this at once

The team should implement in slices:
1. models
2. state
3. graph updater
4. turn loop
5. agent wrappers
6. evaluation fixtures

---

## 28. What success looks like for this class project

A good outcome is **not** a beautiful app.

A good outcome is:
- a clearly scoped multi-agent architecture
- explicit state transitions
- graph-aware follow-up logic
- repeatable tests and fixtures
- a convincing demo showing knowledge capture improving over the course of the interview

If the prototype can show that it starts with partial project knowledge, interviews a departing contractor, resolves a few ambiguities, and produces a richer graph plus a better handoff artifact, then the project is doing the right thing.

---

## 29. Final recommendation

Keep the project disciplined.

Treat the knowledge graph as a **structured target representation**, not the whole project.
Treat the interview as a **knowledge elicitation loop**, not just a chatbot.
Treat the specialist agents as **narrow reasoning modules**, not theatrical personalities.
Treat testing and invariants as **guardrails against drift**, not bureaucracy.

The strongest version of this project is a simple interface wrapped around a well-specified, graph-aware, multi-agent reasoning loop.
