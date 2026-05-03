# Exit Interview Knowledge Elicitation Tool

Conducts structured exit interviews using a multi-agent LLM panel and produces a **Role Brief** — a single, readable document capturing what a departing employee owned, who they worked with, what systems they ran, what they knew that isn't written down, and what will break when they leave.

**Course:** BIT 5544 · VT Spring 2026

---

## Documentation Index

| Question | Document |
|---|---|
| How do I run an interview? | [Quickstart](#quickstart) and [Running an Interview](#running-an-interview) below |
| What are all the CLI flags? | [Command Reference](#command-reference) below |
| How does the system work? | [How It Works](#how-it-works) below |
| What files does the tool produce? | [Output Reference](#output-reference) below |
| How does a turn work step by step? | [How a Turn Works](#how-a-turn-works) below |
| Something went wrong — help | [Troubleshooting](#troubleshooting) below |
| Graph engine (v1.0 comparison mode) | [docs/graph_engine.md](docs/graph_engine.md) |
| Why did the project pivot from graph to brief? | [docs/project_narrative.md](docs/project_narrative.md) |
| Known bugs and limitations | [docs/dev_notes.md](docs/dev_notes.md) |
| Full technical specification | [knowledge_graph_exit_interview_project_spec.md](knowledge_graph_exit_interview_project_spec.md) |
| Codebase map for developers | [CLAUDE.md](CLAUDE.md) |

---

## The Problem

When a contractor or key employee leaves a project, critical knowledge leaves with them — undocumented workflows, system ownership, relationship context, informal approval chains. Exit interviews capture some of this, but the output is usually a transcript that nobody reads.

This tool turns that conversation into a structured **Role Brief** a manager can immediately act on: a handoff document, a backfill job description, a 30/60/90-day watchlist for the successor.

---

## How It Works

Each interview turn is one question → one answer → six parallel LLM extractions → state commit. The loop runs until `max_turns` is reached or you type `done`.

```
              ┌────────────────────────────────┐
              │         BriefSessionState        │
              │  brief · turns · coverage · cfg  │
              └──────────────┬─────────────────┘
                             │
               ┌─────────────▼─────────────┐
               │      Brief Orchestrator     │
               │  priority ladder:           │
               │  1. Resolve ambiguities     │
               │  2. Pre-seeded questions    │
               │  3. Mandatory coverage gaps │
               │  4. General coverage gaps   │
               └─────────────┬─────────────┘
                             │  next question
               ┌─────────────▼─────────────┐
               │         You type           │
               │      the answer            │
               └─────────────┬─────────────┘
                             │  answer text
      ┌──────────────────────▼──────────────────────┐
      │           Six Agents  (run in parallel)       │
      │                                              │
      │  Responsibility Extractor  →  what they own  │
      │  People Extractor          →  collaborators  │
      │  Systems Extractor         →  tools & infra  │
      │  Implicit Knowledge Extractor  →  undocu-    │
      │                                  mented know │
      │  Risk Extractor            →  single points  │
      │                               of failure     │
      │  Clarification Detector    →  follow-up q's  │
      └──────────────────────┬──────────────────────┘
                             │  typed structured outputs
               ┌─────────────▼─────────────┐
               │        Brief Updater        │
               │  deduplicates and merges    │
               │  extracted items into the   │
               │  Role Brief sections        │
               └─────────────────────────────┘
```

The Role Brief accumulates across turns. When all mandatory coverage categories reach their minimum thresholds, the tool signals completion and writes the output to disk.

---

## Quickstart

### 1. Install

```bash
pip install -e ".[dev]"
```

### 2. Set your API key

Copy `.env.example` to `.env` in the project root and add your key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

The app loads this automatically on startup. `.env` is gitignored.

### 3. Verify the install (no API key needed)

```bash
pytest -m "unit or integration"   # ~80 tests, no LLM calls, ~2s
```

### 4. Run your first interview

```bash
python run_interview.py --engine brief --name "Jordan Kim" --role "Senior Data Engineer"
```

The tool shows a config picker. Select `exit_interview` (the built-in option) and follow the prompts.

---

## Running an Interview

### Scenario 1: Standard Exit Interview

**Situation:** A data engineer named Jordan Kim is leaving. You want to capture what they know and produce a Role Brief for the handoff.

#### Start the session

```bash
python run_interview.py --engine brief --name "Jordan Kim" --role "Senior Data Engineer" --config exit_interview
```

The tool prints a header confirming the session:

```
======================================================================
  INTERVIEW — BRIEF ENGINE
  Interviewee : Jordan Kim
  Role        : Senior Data Engineer
  Config      : Employee Exit Interview
  Max turns   : 12
  Output      : runs/brief_jordan_kim/
======================================================================

  At each turn, pick a question from the menu or press Enter
  to accept the default. Type 'done' at any prompt to finish.
```

#### Work through the question menu

Each turn opens with a ranked menu of up to 5 candidate questions:

```
  Available questions:
  [1] (default) Walk me through what you actually own day-to-day — not
       what's in your job description, but what you actually spend time on.
       Why: Role Summary is mandatory (0.00 — target 0.70).

  [2] Who are the people you work with most closely?
       Why: Key People & Relationships is mandatory (0.00 — target 0.70).

  [3] What systems or tools are you the primary owner of?
       Why: Systems & Tools is mandatory (0.00 — target 0.70).

  [4] What's something you know that isn't written down anywhere?
       Why: Implicit & Undocumented Knowledge is mandatory (0.00 — target 0.65).

  [5] What would keep you up at night after you've left?
       Why: Risks & Single Points of Failure is mandatory (0.00 — target 0.65).

  Pick [1-5] or Enter for default (or 'done' to finish):
```

Press Enter to accept the default, or type a number to choose a different question. There is no wrong choice — the tool will cover every mandatory category across turns regardless of order.

#### Read the turn summary

After each answer, the six agents extract in parallel and a summary appears:

```
----------------------------------------------------------------------
  EXTRACTED THIS TURN
    + 3 responsibilities added
    + 2 people added
    + 1 system added

  Coverage:
  * Role Summary                    0.68  [#############.........]  (need 70%)
  * Responsibilities & Ownership    0.44  [########...............]  (need 75%)
  * Key People & Relationships      0.35  [#######................]  (need 70%)
  * Systems & Tools                 0.28  [#####..................]  (need 70%)
  * Implicit & Undocumented Knowl.  0.00  [......................]  (need 65%)
  * Risks & Single Points of Fail.  0.00  [......................]  (need 65%)
    Hiring Profile for Successor    0.00  [......................]
  Overall: 31%
----------------------------------------------------------------------
```

Categories marked `*` are mandatory. The bars fill as the interview progresses.

#### Finish and save

When all mandatory categories reach their targets, the tool signals:

```
  ✓ Mandatory coverage complete — interview can finish.
  Type 'done' at the next prompt to save, or continue for depth.
```

Type `done` to end. The tool saves two artifacts:

```
  Brief state saved : runs/brief_jordan_kim/brief_state.json
  Obsidian vault    : runs/brief_jordan_kim/brief_vault/
```

**`brief_state.json`** — full session state, resumable later.  
**`brief_vault/`** — the Role Brief as a Markdown document. Open in Obsidian or any text editor.

#### Resuming an interrupted session

Run the exact same command again:

```bash
python run_interview.py --engine brief --name "Jordan Kim" --role "Senior Data Engineer" --config exit_interview
```

The tool finds the saved state and prompts:

```
  Previous brief session found:
    Turns completed : 5
    Completeness    : 48%

  Resume this session? [Y/n]:
```

Press Enter to pick up exactly where you left off.

---

### Scenario 2: Creating a New Domain Config

**Situation:** You want to use the tool for a consultant project retrospective. The standard exit interview config asks about responsibilities and systems, but you need categories for client relationships, deliverables, and lessons learned instead.

#### Start the meta-interview

```bash
python run_interview.py --engine brief --name "Priya Sharma" --role "Senior Consultant" --new-config
```

The tool enters an 8-question session where you describe the kind of interview you want to conduct:

```
======================================================================
  DOMAIN CONFIG CREATION — META-INTERVIEW
======================================================================

  I'll ask you 8 questions about the type of interview you want
  to conduct. Your answers will generate a custom domain config.
```

Answer in plain language:

```
What type of interview are you trying to conduct?

  Your answer: A project retrospective with a departing consultant who
  worked on a client engagement for 18 months. We want to capture the
  relationship history, deliverables, and what the next account team
  needs to know.
```

After 8 questions, the system generates a full config — coverage categories, question banks, and output templates — and shows you a preview:

```
  Generated config: Consultant Project Retrospective (consultant_retrospective)

  Categories:
  * Client Relationships (mandatory, target: 70%)
  * Deliverables & Outputs (mandatory, target: 70%)
  * Lessons Learned (mandatory, target: 65%)
  * Commitments & Open Items (mandatory, target: 70%)
    Team Dynamics (optional)

  Response (or 'approve' to save):
```

Type `approve` to save the config, or describe changes and the tool regenerates. Once saved, reference it directly in future sessions:

```bash
python run_interview.py --engine brief --name "Priya Sharma" --role "Senior Consultant" --config consultant_retrospective
```

---

## How a Turn Works

1. **Question menu** — Up to 5 candidate questions ranked by priority (resolve ambiguities first, then pre-seeded questions, then mandatory coverage gaps, then general gaps). Each candidate shows a one-line rationale.

2. **Pick or accept** — Press Enter for the default (question 1), type a number to choose a different one, or type `done` to finish early.

3. **Type the answer** — Free text, no length limit. Longer, more detailed answers produce richer extractions. One-sentence answers give the agents little to work with.

4. **Extraction and summary** — All six agents run in parallel on the answer. After a few seconds, a turn summary shows what was extracted and the current coverage state for each category.

5. **Auto-save** — The session is written to disk after every turn. Interrupting the process loses no data.

---

## Command Reference

```bash
python run_interview.py --engine brief [flags]
```

| Flag | Description | Default |
|---|---|---|
| `--name` | Interviewee's full name | required |
| `--role` | Interviewee's job title or role | required |
| `--engine brief` | Use the brief engine (this doc) | — |
| `--config` | Domain config slug (e.g. `exit_interview`) | interactive picker |
| `--new-config` | Create a new config via meta-interview instead of picking | — |
| `--max-turns` | Maximum turns before auto-close | `12` |
| `--out` | Output directory | `runs/<name-slug>/` |
| `--quiet` | Suppress per-turn extraction summaries | — |

> For the graph engine (`--engine graph`), see [docs/graph_engine.md](docs/graph_engine.md).

---

## Output Reference

Both output files are written to `runs/<name-slug>/` by default. Override with `--out <path>`.

| File / Directory | Contents |
|---|---|
| `brief_state.json` | Full session state: all turns, all extracted items, coverage scores. Resumable. |
| `brief_vault/` | The Role Brief as a Markdown document. Organized into sections: role summary, responsibilities, people, systems, implicit knowledge, risks, hiring profile. Open in Obsidian or any text editor. |

---

## Project Structure

```
app/
  agents/
    llm_client.py                    # Shared instructor-wrapped Anthropic client
    brief_orchestrator.py            # Config-driven question selector
    responsibility_extractor.py      # Extracts responsibilities
    people_extractor.py              # Extracts people & relationships
    systems_extractor.py             # Extracts systems & tools
    implicit_knowledge_extractor.py  # Extracts undocumented knowledge
    risk_extractor.py                # Extracts risks & single points of failure
    clarification_detector.py        # Detects ambiguities, generates follow-up questions
    stubs.py                         # Fast no-LLM stubs for CI tests
    prompts/                         # Versioned system prompts (.md files, one per agent)

  brief/
    schema.py            # RoleBrief, Responsibility, BriefPerson, BriefSystem, BriefRisk, etc.
    extraction_models.py # Pydantic I/O wrappers for each extraction agent
    session.py           # BriefSessionState (runtime container)
    updater.py           # merge_into_brief() — the only place that writes to RoleBrief sections

  config/
    domain_config.py     # DomainConfig schema: coverage categories, question banks, targets
    context_briefing.py  # ContextBriefing (lightweight preload context)
    config_store.py      # save / load / list domain configs
    instances/
      exit_interview.json  # Built-in exit interview config

  core/
    models.py            # Shared Pydantic models: Interviewee, InterviewTurn, Ambiguity, etc.

  ingestion/
    loaders.py           # load_context_briefing() and load_initial_state()
    dummy_data/
      context_briefing.json  # Brief engine preload context

  interview/
    brief_turn_loop.py   # run_brief_turn() and run_brief_interview() — main loop

  meta/
    meta_interview.py    # Entry point for --new-config flow
    meta_loop.py         # The 8-question meta-interview loop
    config_generator.py  # LLM: generate DomainConfig from meta-answers
    config_reviewer.py   # LLM: critique and refine the generated config
    config_validator.py  # LLM: validate config coherence before saving
    meta_questions.json  # The 8 meta-questions

  vault/
    vault_compiler.py    # compile_brief_vault() — writes the Role Brief Markdown after the interview

tests/
  unit/        # Pure logic, no I/O
  contracts/   # Agent output schema validation (mocked LLM)
  integration/ # Full pipeline with stub agents (no API key needed)
  golden/      # Live LLM evaluation — requires ANTHROPIC_API_KEY
  fixtures/
    golden_interviews/  # Scripted transcripts + expected assertions

eval/
  run_golden_eval.py    # Standalone eval script — runs scripted interviews and prints a report

docs/
  graph_engine.md       # Graph engine (v1.0) reference — how to run, output format, known issues
  project_narrative.md  # Design history — why the project pivoted from graph to brief
  dev_notes.md          # Raw dev observations: known issues, failure modes
```

---

## Status

| Component | Status | Notes |
|---|---|---|
| Brief schema & updater | ✅ Complete | Dedup, merge, provenance tracking |
| Config-driven orchestrator | ✅ Complete | Reads DomainConfig, 4-tier priority ladder |
| Brief engine turn loop | ✅ Complete | 6 agents in parallel via asyncio.gather |
| LLM extraction agents (×5) | ✅ Complete | Responsibility, people, systems, implicit knowledge, risk |
| Clarification detector | ✅ Complete | Shared with graph engine |
| Domain config system | ✅ Complete | save/load/list, built-in exit_interview config |
| Interactive CLI | ✅ Complete | Question menu, session resume, per-turn summaries |
| Meta-interview (config creation) | ⚠️ Beta | Config generation, validation, and persistence |
| Vault compiler (brief) | ⚠️ Partial | Single-document Markdown output, not fully tested |
| Unit + integration tests | ✅ ~159 passing | CI runs without API key |
| Golden eval framework | ✅ Complete | 7 scripted scenarios, eval report script |

---

## Troubleshooting

**"ANTHROPIC_API_KEY is not set"**  
Create `.env` in the project root containing `ANTHROPIC_API_KEY=sk-ant-...your-key...`. The tool loads this file automatically on startup.

**"No config found for slug 'exit_interview'"**  
The built-in configs live in `app/config/instances/`. Check that `exit_interview.json` exists there.

**The tool extracted nothing from a turn**  
Short or vague answers produce sparse extractions. One-sentence answers give the agents little to work with. Encourage detailed, narrative responses — prompts like "walk me through exactly how that works" tend to produce much richer output.

**The interview ended before all mandatory categories were covered**  
The default `--max-turns` is 12. Use `--max-turns 20` for longer interviews, or resume the saved session by running the same command again.

**Unicode or box-drawing characters appear garbled on Windows**  
The CLI sets UTF-8 output mode automatically. If you still see garbled characters, ensure your terminal uses UTF-8 (Windows Terminal: Settings → Defaults → Appearance → Text → UTF-8).
