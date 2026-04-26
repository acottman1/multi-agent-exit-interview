"""
Interactive exit interview CLI.

Runs the full multi-agent pipeline turn-by-turn, reading answers from stdin.
At each turn a numbered menu of candidate questions is shown; the user can
pick any one or press Enter to accept the default (highest-priority) choice.
After the session ends (user types 'done'/'exit', or max turns reached),
saves the final state and compiles the Obsidian vault.

Usage
-----
  # Start with no prior context (blank graph)
  python run_interview.py --name "Alex Miller" --role "Data Analyst"

  # Start from a named project context
  python run_interview.py --name "Alex Miller" --role "Data Analyst" --project falcon

  # Start from a custom JSON file
  python run_interview.py --name "Alex Miller" --role "Data Analyst" --project path/to/seed.json

  # Adjust turn limit and output directory
  python run_interview.py --name "Alex Miller" --role "Data Analyst" --max-turns 20 --out runs/my_session

Named projects
--------------
  falcon      Project Falcon (data analytics)
  erp         ERP modernization
  cloud       Cloud migration support
  data        Data platform (Airflow / dbt)
  soc2        SOC 2 cybersecurity compliance
  onboarding  Client onboarding operations
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import textwrap
from pathlib import Path

# UTF-8 output so box-drawing chars survive Windows terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Load .env before anything else.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.orchestrator import select_next_questions
from app.core.models import Interviewee, OrchestratorOutput, SharedInterviewState
from app.graph.schema import KnowledgeGraph
from app.ingestion.loaders import load_initial_state
from app.interview.turn_loop import TurnResult, run_turn
from app.vault.vault_compiler import compile_vault, load_final_state, save_final_state

# ── Named project registry ────────────────────────────────────────────────────

_SEEDS_DIR = Path(__file__).parent / "tests" / "fixtures" / "seeds"

_PROJECTS: dict[str, Path] = {
    "falcon":     _SEEDS_DIR / "initial_state.json",
    "erp":        _SEEDS_DIR / "erp_modernization_seed.json",
    "cloud":      _SEEDS_DIR / "cloud_migration_seed.json",
    "data":       _SEEDS_DIR / "data_platform_seed.json",
    "soc2":       _SEEDS_DIR / "cybersecurity_seed.json",
    "onboarding": _SEEDS_DIR / "client_onboarding_seed.json",
}

# ── Formatting helpers ────────────────────────────────────────────────────────

WIDTH = 70

def _divider(char: str = "=") -> None:
    print(char * WIDTH)

def _wrap(text: str, indent: int = 2) -> str:
    prefix = " " * indent
    return textwrap.fill(text, width=WIDTH, initial_indent=prefix, subsequent_indent=prefix)

def _print_turn_summary(result: TurnResult, initial_nodes: int, current_nodes: int) -> None:
    entity_out = result.proposed_update.entity_extraction
    clar_out = result.proposed_update.clarifications
    apply = result.apply_result

    created = apply.created_count
    updated = apply.promoted_count + len([c for c in apply.node_changes if c.op == "updated"])

    print()
    _divider("-")
    print("  EXTRACTED THIS TURN")

    if entity_out and entity_out.entities:
        print("  Entities:")
        for e in entity_out.entities:
            flag = " [ambiguous]" if e.is_ambiguous else ""
            print(f"    + {e.label} ({e.type}, {e.confidence:.0%}){flag}")
    else:
        print("  Entities: (none)")

    print(f"  Graph: {created} node(s) created, {updated} updated  "
          f"| Total nodes: {current_nodes}")

    if clar_out and clar_out.clarifications:
        print("  Follow-up questions queued:")
        for c in clar_out.clarifications:
            print(_wrap(f"[{c.priority.upper()}] {c.suggested_question}", indent=4))

    _divider("-")

# ── Question menu ─────────────────────────────────────────────────────────────

def _show_question_menu(
    candidates: list[OrchestratorOutput],
) -> tuple[OrchestratorOutput | None, bool]:
    """Display a numbered menu of candidate questions.

    Returns (chosen, done).  done=True means the user wants to exit.
    """
    print()
    print("  Available questions:")
    for i, c in enumerate(candidates, 1):
        default_tag = " (default)" if i == 1 else ""
        q_short = textwrap.shorten(c.next_question, width=60, placeholder="...")
        r_short = textwrap.shorten(c.rationale, width=58, placeholder="...")
        print(f"  [{i}]{default_tag} {q_short}")
        print(f"       Why: {r_short}")

    print()
    prompt = f"  Pick [1-{len(candidates)}] or Enter for default (or 'done' to finish): "
    try:
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None, True

    if raw.lower() in {"done", "exit", "quit", "q"}:
        return None, True

    if raw == "":
        return candidates[0], False

    try:
        idx = int(raw)
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1], False
    except ValueError:
        pass

    print(f"  Invalid choice — using question [1] by default.")
    return candidates[0], False


def _prompt_for_answer(question: str) -> tuple[str, bool]:
    """Display the selected question and read the interviewee's answer.

    Returns (answer, done).  done=True means the user wants to exit.
    """
    print()
    print(_wrap(question, indent=0))
    print()
    try:
        answer = input("  Your answer (or 'done' to finish): ").strip()
    except (EOFError, KeyboardInterrupt):
        return "", True

    if answer.lower() in {"done", "exit", "quit", "q"}:
        return "", True

    return answer or "(no answer given)", False


def _captured_provider(answer: str):
    """Wrap a pre-captured answer as an AnswerProvider callable."""
    def provider(_question: str) -> str:
        return answer
    return provider


def _prompt_resume(state_path: Path) -> bool:
    """Show a summary of the previous session and ask whether to resume it."""
    prev = load_final_state(state_path)
    turns_done = len(prev.turns)
    nodes = len([n for n in prev.graph.nodes if n.status != "superseded"])

    print()
    print("  Previous session found:")
    print(f"    Turns completed : {turns_done}")
    print(f"    Nodes in graph  : {nodes}")
    print("    Coverage scores:")
    for field in type(prev.coverage).model_fields:
        val = getattr(prev.coverage, field)
        filled = int(val * 20)
        bar = "#" * filled + "." * (20 - filled)
        print(f"      {field:<26} {val:.2f}  [{bar}]")
    print()

    try:
        raw = input("  Resume this session? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    return raw in {"", "y", "yes"}

# ── Main interview loop ───────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    # 1. Output directory — compute first so we can check for a previous session
    slug = re.sub(r"[^a-z0-9]+", "_", args.name.lower()).strip("_")
    out_dir = Path(args.out) if args.out else Path("runs") / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "final_state.json"

    # 2. Load state — resume previous session or start fresh
    resumed = False
    if state_path.exists() and _prompt_resume(state_path):
        state = load_final_state(state_path)
        project_label = f"resumed from {state_path}"
        resumed = True
    else:
        interviewee = Interviewee(name=args.name, role=args.role, project_ids=[])
        if args.project:
            project_path = _PROJECTS.get(args.project.lower()) or Path(args.project)
            if not project_path.exists():
                print(f"ERROR: Project file not found: {project_path}", file=sys.stderr)
                sys.exit(1)
            state = load_initial_state(interviewee, path=project_path)
            project_label = args.project
        else:
            state = SharedInterviewState(
                interviewee=interviewee,
                graph=KnowledgeGraph(nodes=[], edges=[]),
            )
            project_label = "blank (no prior context)"

    initial_nodes = len(state.graph.nodes)

    # 3. Header
    _divider()
    print(f"  EXIT INTERVIEW {'(RESUMED)' if resumed else ''}")
    print(f"  Interviewee : {args.name}")
    print(f"  Role        : {args.role}")
    print(f"  Project     : {project_label}")
    print(f"  Max turns   : {args.max_turns}")
    print(f"  Output      : {out_dir}/")
    _divider()
    print()
    print("  At each turn, pick a question from the menu or press Enter")
    print("  to accept the default. Type 'done' at any prompt to finish.")
    print()

    # 5. Turn loop
    turn_count = 0

    for _ in range(args.max_turns):
        # Get ranked candidates and let the user choose
        candidates = select_next_questions(state, n=5)
        chosen, done = _show_question_menu(candidates)
        if done:
            break

        # Get the answer for the chosen question
        answer, done = _prompt_for_answer(chosen.next_question)
        if done:
            break

        # Run the full agent pipeline with the pre-selected question
        result = await run_turn(
            state,
            _captured_provider(answer),
            selected_question=chosen,
        )
        turn_count += 1

        if not args.quiet:
            _print_turn_summary(result, initial_nodes, len(state.graph.nodes))

    # 6. Final summary
    print()
    _divider()
    print("  INTERVIEW COMPLETE")
    print(f"  Turns completed : {turn_count}")
    print(f"  Nodes in graph  : {initial_nodes} -> {len(state.graph.nodes)} "
          f"(+{len(state.graph.nodes) - initial_nodes})")
    print("  Coverage scores:")
    for field in type(state.coverage).model_fields:
        val = getattr(state.coverage, field)
        filled = int(val * 20)
        bar = "#" * filled + "." * (20 - filled)
        print(f"    {field:<28} {val:.2f}  [{bar}]")
    _divider()

    # 7. Save state and compile vault
    state_path = out_dir / "final_state.json"
    vault_path = out_dir / "exit_interview_vault"

    save_final_state(state, state_path)
    compile_vault(state, vault_path)

    print()
    print(f"  Final state saved : {state_path}")
    print(f"  Obsidian vault    : {vault_path}/")
    print()

# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an interactive exit interview.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join([
            "Named projects:",
            *[f"  {k:<12} {v.name}" for k, v in _PROJECTS.items()],
        ]),
    )
    parser.add_argument("--name",      required=True, help="Interviewee full name")
    parser.add_argument("--role",      required=True, help="Interviewee role or title")
    parser.add_argument(
        "--project",
        default=None,
        metavar="NAME_OR_PATH",
        help="Named project (falcon/erp/cloud/data/soc2/onboarding) or path to a seed JSON. "
             "Omit to start with a blank graph.",
    )
    parser.add_argument(
        "--max-turns", type=int, default=12,
        help="Maximum number of interview turns (default: 12)",
    )
    parser.add_argument(
        "--out", default=None, metavar="DIR",
        help="Output directory for final state and vault (default: runs/<name-slug>/)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-turn entity summaries; only show final report",
    )

    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set. Add it to your .env file.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
