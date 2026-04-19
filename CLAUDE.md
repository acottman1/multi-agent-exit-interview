# Exit Interview Knowledge Graph Prototype

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Project Context
A research prototype using a multi-agent LLM system (FastAPI + Pydantic) to conduct turn-based exit interviews and update a graph-shaped knowledge base. 
**Authoritative Spec:** For the full project specification, always refer to `@knowledge_graph_exit_interview_project_spec.md`.

---

## 🛑 Architectural Constraints (CRITICAL)
<rules>
1. **Never write code ahead of the current Phase.** We are building strictly phase-by-phase (see `@knowledge_graph_exit_interview_project_spec.md` Section 22).
2. **Enforce Async Parallelism:** When implementing specialist agents (`agents/`), they MUST be called concurrently via `asyncio.gather` in `turn_loop.py`. They must never block each other.
3. **Restrict the Ingestion Layer:** Do not build a complex document parser for dummy data. Use a static `initial_state.json` file that already conforms to the Pydantic models.
4. **Limit Token Payloads:** Do not pass the entire `SharedInterviewState` to every agent. Pass only the specific slices of state required for their specific task.
5. **Strict Pydantic Enforcement:** Use the `instructor` library to enforce structured Pydantic model outputs from the LLM. Prompt engineering alone is insufficient.
6. **Obsidian as Post-Processing Only:** The Obsidian Vault generation (`vault_compiler.py`) MUST be a standalone script that runs *after* the interview ends. Do not read/write Markdown files during the live conversational turn loop.
7. **Graph Mutations:** Specialist agents propose updates into `proposed_updates`. ONLY the graph update layer (`updater.py`) may promote items from `provisional` to `confirmed`.
</rules>

---

## 🛠️ Common Commands

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the FastAPI server
uvicorn app.main:app --reload

# Run all tests
pytest

# Run tests by marker
pytest -m "unit"
pytest -m "contract"
pytest -m "integration"