# From Knowledge Graph to Role Brief: The Arc of the Exit Interview Project

## The Original Problem We Were Trying to Solve

When someone leaves an organization — or transitions off a project — a significant amount of knowledge leaves with them. Not just the tasks they performed, but the unwritten rules, the informal relationships, the systems only they know how to restart, the history behind decisions that look arbitrary to a newcomer. Traditional offboarding processes capture almost none of this. Exit interviews, when they happen at all, are conversational and unstructured. The output is usually a typed summary that lives in a folder no one reads.

The original idea behind this project was to use a multi-agent AI system to conduct structured exit interviews and transform the conversation into a machine-readable knowledge base — specifically, a knowledge graph. The hypothesis was that if you could extract entities (people, systems, workflows, risks) and relationships between them from a natural conversation, you would end up with something navigable, queryable, and more durable than notes.

---

## What Was Actually Built

The first seven phases of the project built exactly that. The architecture was coherent and technically sound.

**The core data model** was a `KnowledgeGraph` containing typed nodes (`GraphNode`) and typed edges (`GraphEdge`). Nodes had to belong to one of twelve fixed categories — `Person`, `Role`, `Team`, `Project`, `Client`, `System`, `Document`, `Workflow`, `Task`, `Decision`, `Risk`, or `Issue`. Edges had to belong to one of thirteen typed relationships — `OWNS`, `REPORTS_TO`, `COMMUNICATES_WITH`, `DEPENDS_ON`, `SUPPORTS`, and others. Everything had a lifecycle: nodes and edges began as `provisional`, were promoted to `confirmed` once they met a confidence threshold, and could be marked `superseded` if later turns contradicted them.

**The extraction pipeline** ran five specialist agents in parallel on each interview turn, using Python's `asyncio.gather` so none of them blocked each other. One agent pulled out candidate entities, another mapped relationships, a third updated attributes on existing nodes, a fourth detected ambiguities that needed clarification, and a fifth updated a coverage score. All agents were constrained to receive only the slice of state they needed — a design rule that proved its worth by keeping the agents independent and testable.

**The interview loop** was driven by a rule-based orchestrator with a priority ladder: resolve ambiguities first, then ask pre-seeded open questions, then probe low-confidence graph nodes, then fall back to coverage-gap questions. The coverage-gap fallback relied on a hardcoded dictionary called `_FALLBACK_VARIANTS` — three question phrasings per category, with the selection deterministic based on a hash of the session ID so that replaying an interview would produce the same questions.

**Coverage tracking** used a `CoverageScores` model with exactly six fields: `people`, `systems`, `workflows`, `stakeholders`, `risks`, and `undocumented_knowledge`. These were updated after each turn by an agent that read the updated graph and estimated how thoroughly each category had been filled.

**The output** was an Obsidian vault — a directory of Markdown files, one per graph node, organized into subdirectories by node type. The idea was that a manager or HR professional could navigate the vault the same way they navigate a wiki, following links from a person to the systems they owned to the workflows that depended on those systems.

By the end of Phase 7, the system had a working interactive CLI, a golden evaluation suite with hand-authored interview scenarios, and over 80 passing tests.

---

## Why It Fell Short

Despite being technically functional, the system had a set of structural problems that became clearer as the implementation matured. None of these were bugs — they were design choices that turned out to be wrong.

### The graph answered the wrong question

A knowledge graph is a good answer to the question: *What entities and relationships exist in this domain?* It is a poor answer to the question: *What does this specific person do, and what will break when they leave?*

The difference matters. An exit interview is not a general domain survey — it is a focused investigation of one person's role. The downstream consumers — a hiring manager writing a job description, a team lead planning a handoff, a new hire in their first week — need a narrative document they can read, not a graph they have to traverse. The Obsidian vault produced one `.md` file per graph node. There was no single artifact that told the story of what the person did, why it mattered, and what the risks were. A reader had to assemble that picture themselves by following links.

### Coverage scores were disconnected from what mattered

The six-field `CoverageScores` model tracked progress, but the fields were not weighted or differentiated in any meaningful way. Mentioning a person's name in passing contributed to the `people` score the same as a detailed description of a critical collaborator. The coverage model had no concept of *mandatory* versus *incidental* — it could not tell you that a particular category absolutely had to be filled before the interview could be considered complete.

More fundamentally, coverage was measured against the graph itself: a coverage updater agent read the graph after each turn and estimated completeness. But this created a circular dependency — the graph only contained what had been extracted, so the system was measuring how much of its own output existed, not how much of the real knowledge had been captured.

### Hardcoded categories made the system one-domain-only

The six coverage categories were baked into the `CoverageScores` Pydantic model as fixed fields. The question banks in `_FALLBACK_VARIANTS` were authored for one specific domain — a software or data engineering exit interview. The node type vocabulary (`Person`, `Workflow`, `System`, etc.) was plausible for that domain but would have been meaningless or awkward applied to, say, a clinical role handoff, a client discovery session, or a project retrospective.

Every domain adaptation would have required modifying source code. There was no configuration layer between the intent ("I want to interview data engineers about what they own") and the implementation (a fixed schema with fixed question banks). This was a significant limitation for a tool that aspired to be general-purpose.

### The graph vocabulary was too abstract

The typed node and edge vocabulary — twelve node types, thirteen relationship types — was broad enough to represent almost anything, but that breadth was its weakness. When an interviewee mentioned "the monthly reporting pipeline," the entity extractor had to decide whether that was a `Workflow`, a `Task`, a `Document`, or a `System`. It could reasonably be any of them, depending on the context and the extractor's confidence. The resulting graph nodes were often technically valid but semantically thin: a node labeled "Monthly Reporting Pipeline" with type `Workflow` tells you less than a structured record that says *this is a responsibility the person owns, it runs monthly, it depends on Snowflake and Airflow, it is critical, and it is not documented anywhere*.

The graph's generality was a feature for a general-purpose knowledge tool. For an exit interview, it was friction.

---

## How the Decision to Refocus Was Made

The pivot was not triggered by a single failure. It emerged from stepping back and asking what the system would actually need to produce to be useful to the people who would use it.

The concrete test was simple: if a manager received the output of one of these interviews, what would they do with it? With the Obsidian vault, the answer was "navigate it" — which required them to understand the graph structure, follow links, and synthesize a narrative themselves. That was still too much work, and it put the burden of interpretation on the reader rather than on the system.

The more useful artifact would be something closer to a structured briefing document — one document per interview, organized around questions that mattered operationally: What did this person actually do? Who did they depend on? What systems did they own? What would break in the first month after they left? What would a replacement need to know in their first week?

Each of those questions mapped naturally to a section of a document, not to a category in a graph. That observation drove the redesign.

---

## What Changed and Why

**The primary output artifact changed** from a `KnowledgeGraph` to a `RoleBrief` — a structured JSON document with named sections that each served a specific downstream purpose. `role_summary` feeds onboarding materials. `responsibilities` supports delegation and handoff planning. `people` becomes a relationship map for warm introductions. `systems` drives access provisioning. `implicit_knowledge` captures what gets lost without this tool. `risks` becomes a 30/60/90-day watchlist for the successor. `hiring_profile` produces a backfill interview kit at the end of the session. Each section maps directly to something a real consumer would use, without requiring them to understand the underlying data structure.

**The extraction agents were reoriented** from graph-entity extraction to section-filling. Instead of asking "what entities and relationships does this turn contain?" each agent now asks a more targeted question: "what responsibilities did the interviewee describe?" or "what risks did they surface?" The outputs are typed Pydantic models — `ResponsibilityExtractionOutput`, `PeopleExtractionOutput`, and so on — that feed directly into their corresponding sections of the brief.

**Coverage became configuration-driven and meaningful**. The new `DomainConfig` object specifies which categories exist for a given domain, what question banks belong to each, and — critically — which categories are *mandatory* and what minimum coverage score they must reach before the interview can be considered complete. The orchestrator reads from this config at runtime, so the same code can drive an exit interview, a requirements elicitation session, or a client discovery call, each with entirely different categories and question banks.

**The merge logic became explicit**. The `BriefUpdater` tracks provenance (which interview turns contributed each item), deduplicates by a canonical key per section, unions list fields across turns, and preserves existing values when incoming data is empty. This makes the accumulated state across a multi-turn interview coherent and auditable.

**The vault output simplified**. Instead of one Markdown file per graph node, the vault compiler now generates a single Markdown document per interview using Mustache-style templates defined in the domain config. The output reads as a human document rather than a navigable database.

---

## What Was Preserved

The architectural decisions that had proven sound were kept intact.

The five-agent parallel execution pattern — running specialist agents concurrently via `asyncio.gather` — carried over unchanged. Agents still receive only the slice of state they need, not the full interview state. The `instructor` library still enforces structured Pydantic outputs from the LLM, eliminating prompt-engineering fragility. The clarification detection agent was unchanged, because identifying ambiguities and formulating follow-up questions is the same problem regardless of what the final output looks like.

The original graph engine was not deleted. It was tagged as `v1.0-graph-engine` in git and preserved intact alongside the new brief engine. This was a deliberate choice: the two engines run on the same interview turn loop infrastructure, and the ability to compare their outputs directly supports the academic comparison study that is one of the project's evaluation goals.

---

## Where the Project Now Stands

The project's center of gravity has shifted from *building a knowledge graph* to *building a configurable knowledge elicitation engine that produces structured role briefs*. The graph is still present as an alternative output and as an object of academic study, but it is no longer the primary artifact. The brief is.

This is a more grounded answer to the original problem. The knowledge that leaves with a departing employee is best preserved not as a network of abstract entities and relationships, but as a structured document that directly answers the questions a successor, a manager, and a hiring team actually have. The multi-agent AI system is still the means — parallel extraction, structured output, orchestrated questioning — but the end is now something a real person can read and act on the day after the interview concludes.
