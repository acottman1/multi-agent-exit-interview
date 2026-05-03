"""
Interactive interview CLI.

  python run_interview.py --name "Alex Miller" --role "Data Analyst"
  python run_interview.py --name "Alex Miller" --role "Data Analyst" --config exit_interview
  python run_interview.py --name "Alex Miller" --role "Data Analyst" --new-config
  python run_interview.py --name "Alex Miller" --role "Data Analyst" --max-turns 20 --out runs/my_session
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

# ── Named project registry (graph engine) ────────────────────────────────────

_SEEDS_DIR = Path(__file__).parent / "tests" / "fixtures" / "seeds"

_PROJECTS: dict[str, Path] = {
    "falcon":     _SEEDS_DIR / "initial_state.json",
    "erp":        _SEEDS_DIR / "erp_modernization_seed.json",
    "cloud":      _SEEDS_DIR / "cloud_migration_seed.json",
    "data":       _SEEDS_DIR / "data_platform_seed.json",
    "soc2":       _SEEDS_DIR / "cybersecurity_seed.json",
    "onboarding": _SEEDS_DIR / "client_onboarding_seed.json",
}

# ── Shared formatting helpers ─────────────────────────────────────────────────

WIDTH = 70

def _divider(char: str = "=") -> None:
    print(char * WIDTH)

def _wrap(text: str, indent: int = 2) -> str:
    prefix = " " * indent
    return textwrap.fill(text, width=WIDTH, initial_indent=prefix, subsequent_indent=prefix)

# ── Shared question menu ──────────────────────────────────────────────────────

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
        prefix = f"  [{i}]{default_tag} "
        subsequent = " " * len(prefix)
        q_wrapped = textwrap.fill(c.next_question, width=WIDTH,
                                  initial_indent=prefix, subsequent_indent=subsequent)
        r_wrapped = textwrap.fill(c.rationale, width=WIDTH,
                                  initial_indent="       Why: ", subsequent_indent="            ")
        print(q_wrapped)
        print(r_wrapped)

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


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def _print_graph_turn_summary(result: TurnResult, initial_nodes: int, current_nodes: int) -> None:
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


def _prompt_resume_graph(state_path: Path) -> bool:
    """Show a summary of the previous graph session and ask whether to resume it."""
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


async def run_graph(args: argparse.Namespace) -> None:
    slug = re.sub(r"[^a-z0-9]+", "_", args.name.lower()).strip("_")
    out_dir = Path(args.out) if args.out else Path("runs") / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "final_state.json"

    resumed = False
    if state_path.exists() and _prompt_resume_graph(state_path):
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

    _divider()
    print(f"  EXIT INTERVIEW {'(RESUMED)' if resumed else ''}— GRAPH ENGINE")
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

    turn_count = 0
    for _ in range(args.max_turns):
        candidates = select_next_questions(state, n=5)
        chosen, done = _show_question_menu(candidates)
        if done:
            break

        answer, done = _prompt_for_answer(chosen.next_question)
        if done:
            break

        result = await run_turn(state, _captured_provider(answer), selected_question=chosen)
        turn_count += 1

        if not args.quiet:
            _print_graph_turn_summary(result, initial_nodes, len(state.graph.nodes))

    print()
    _divider()
    print("  INTERVIEW COMPLETE — GRAPH ENGINE")
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

    save_final_state(state, state_path)
    vault_path = out_dir / "exit_interview_vault"
    compile_vault(state, vault_path)

    print()
    print(f"  Final state saved : {state_path}")
    print(f"  Obsidian vault    : {vault_path}/")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# BRIEF ENGINE
# ══════════════════════════════════════════════════════════════════════════════

async def _select_config_interactively(new_config: bool) -> "DomainConfig":  # noqa: F821
    """
    Let the user pick an existing DomainConfig from the store or create a new
    one via the meta-loop.

    If new_config=True, skip the picker and go straight to meta-loop.
    """
    from app.config.config_store import list_domain_configs, load_domain_config
    from app.meta.meta_loop import run_meta_loop

    if not new_config:
        summaries = list_domain_configs()
        if summaries:
            print()
            print("  Available domain configs:")
            for i, s in enumerate(summaries, 1):
                print(f"  [{i}] {s.display_name} ({s.slug})")
                if s.description:
                    print(_wrap(s.description, indent=6))
            print(f"  [0] Create a new config (meta-interview)")
            print()

            try:
                raw = input(f"  Pick [0-{len(summaries)}]: ").strip()
            except (EOFError, KeyboardInterrupt):
                sys.exit(0)

            try:
                idx = int(raw)
                if 1 <= idx <= len(summaries):
                    return load_domain_config(summaries[idx - 1].slug)
                # 0 or anything else falls through to meta-loop
            except ValueError:
                pass
        else:
            print()
            print("  No existing configs found. Starting meta-interview to create one.")

    # Meta-loop — hardcoded 8-question interview to generate a DomainConfig
    print()
    _divider()
    print("  DOMAIN CONFIG CREATION — META-INTERVIEW")
    _divider()
    print()
    print("  I'll ask you 8 questions about the type of interview you want")
    print("  to conduct. Your answers will generate a custom domain config.")
    print()

    def _meta_answer_provider(question: str) -> str:
        print()
        print(_wrap(question, indent=0))
        print()
        try:
            ans = input("  Your answer: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)
        return ans or "(no answer given)"

    def _meta_confirm_provider(review_text: str) -> str:
        print()
        print(review_text)
        print()
        try:
            ans = input("  Response (or 'approve' to save): ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)
        return ans or "approve"

    result = await run_meta_loop(
        answer_provider=_meta_answer_provider,
        confirm_provider=_meta_confirm_provider,
    )
    print()
    print(f"  Config created and saved: {result.naming.display_name} ({result.naming.slug})")
    print(f"  Saved to: {result.config_path}")
    print()
    return result.config


def _prompt_resume_brief(state_path: Path) -> bool:
    """Show a summary of the previous brief session and ask whether to resume it."""
    from app.vault.vault_compiler import load_brief_state

    prev = load_brief_state(state_path)
    turns_done = len(prev.turns)
    completeness = prev.weighted_completeness()

    print()
    print("  Previous brief session found:")
    print(f"    Turns completed : {turns_done}")
    print(f"    Completeness    : {completeness:.0%}")
    print("    Coverage:")
    for cat in prev.domain_config.coverage_categories:
        val = prev.coverage.get(cat.name, 0.0)
        filled = int(val * 20)
        bar = "#" * filled + "." * (20 - filled)
        mand = "*" if cat.mandatory else " "
        print(f"      {mand} {cat.display_name:<28} {val:.2f}  [{bar}]")
    print()

    try:
        raw = input("  Resume this session? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    return raw in {"", "y", "yes"}


def _print_brief_turn_summary(result: "BriefTurnResult", state: "BriefSessionState") -> None:  # noqa: F821
    ur = result.update_result
    print()
    _divider("-")
    print("  EXTRACTED THIS TURN")

    total = ur.total_changes
    if total:
        for section, count in ur.added.items():
            if count:
                print(f"    + {count} {section.replace('_', ' ')} added")
        for section, count in ur.updated.items():
            if count:
                print(f"    ~ {count} {section.replace('_', ' ')} updated")
    else:
        print("    (no new items extracted)")

    print()
    print("  Coverage:")
    completeness = state.weighted_completeness()
    for cat in state.domain_config.coverage_categories:
        val = state.coverage.get(cat.name, 0.0)
        filled = int(val * 20)
        bar = "#" * filled + "." * (20 - filled)
        mand = "*" if cat.mandatory else " "
        threshold = f" (need {cat.min_score:.0%})" if cat.mandatory and val < cat.min_score else ""
        print(f"    {mand} {cat.display_name:<28} {val:.2f}  [{bar}]{threshold}")
    print(f"  Overall: {completeness:.0%}")
    _divider("-")


async def run_brief(args: argparse.Namespace) -> None:
    from app.agents.brief_orchestrator import select_brief_questions
    from app.brief.schema import BriefMeta, RoleBrief
    from app.brief.session import BriefSessionState
    from app.config.config_store import load_domain_config
    from app.interview.brief_turn_loop import run_brief_turn
    from app.vault.vault_compiler import compile_brief_vault, load_brief_state, save_brief_state

    slug = re.sub(r"[^a-z0-9]+", "_", args.name.lower()).strip("_")
    out_dir = Path(args.out) if args.out else Path("runs") / f"brief_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "brief_state.json"

    # Resume or start fresh
    resumed = False
    if state_path.exists() and _prompt_resume_brief(state_path):
        state = load_brief_state(state_path)
        config_label = state.domain_config.display_name
        resumed = True
    else:
        # Select or create domain config
        if args.config:
            config = load_domain_config(args.config)
        else:
            config = await _select_config_interactively(new_config=getattr(args, "new_config", False))

        config_label = config.display_name

        meta = BriefMeta(
            session_id=f"sess_{slug}",
            domain_name=config.domain_name,
            interviewee_name=args.name,
            role_title=args.role,
        )
        brief = RoleBrief(meta=meta)
        state = BriefSessionState(domain_config=config, brief=brief)

    # Show header
    _divider()
    print(f"  INTERVIEW {'(RESUMED)' if resumed else ''}— BRIEF ENGINE")
    print(f"  Interviewee : {args.name}")
    print(f"  Role        : {args.role}")
    print(f"  Config      : {config_label}")
    print(f"  Max turns   : {args.max_turns}")
    print(f"  Output      : {out_dir}/")
    _divider()
    print()
    print("  At each turn, pick a question from the menu or press Enter")
    print("  to accept the default. Type 'done' at any prompt to finish.")
    print()

    turn_count = 0
    for _ in range(args.max_turns):
        if state.mandatory_coverage_met():
            print()
            print("  ✓ Mandatory coverage complete — interview can finish.")
            print("  Type 'done' at the next prompt to save, or continue for depth.")

        candidates = select_brief_questions(state, n=5)
        chosen, done = _show_question_menu(candidates)
        if done:
            break

        answer, done = _prompt_for_answer(chosen.next_question)
        if done:
            break

        result = await run_brief_turn(state, _captured_provider(answer), selected_question=chosen)
        turn_count += 1

        if not args.quiet:
            _print_brief_turn_summary(result, state)

        # Auto-save after each turn
        save_brief_state(state, state_path)

    # Final summary
    completeness = state.weighted_completeness()
    print()
    _divider()
    print("  INTERVIEW COMPLETE — BRIEF ENGINE")
    print(f"  Turns completed : {turn_count}")
    print(f"  Completeness    : {completeness:.0%}")
    print("  Coverage:")
    for cat in state.domain_config.coverage_categories:
        val = state.coverage.get(cat.name, 0.0)
        filled = int(val * 20)
        bar = "#" * filled + "." * (20 - filled)
        mand = "*" if cat.mandatory else " "
        print(f"    {mand} {cat.display_name:<28} {val:.2f}  [{bar}]")
    _divider()

    # Finalize and compile vault
    state.brief.finalized = True
    save_brief_state(state, state_path)

    vault_path = out_dir / "brief_vault"
    compile_brief_vault(state.brief, state.domain_config, vault_path, turns=state.turns)

    print()
    print(f"  Brief state saved : {state_path}")
    print(f"  Obsidian vault    : {vault_path}/")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an interactive exit interview and produce a Role Brief.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--name", required=True, help="Interviewee full name")
    parser.add_argument("--role", required=True, help="Interviewee role or title")
    parser.add_argument(
        "--config",
        default=None,
        metavar="SLUG",
        help="Domain config slug to use (omit to pick interactively).",
    )
    parser.add_argument(
        "--new-config",
        action="store_true",
        help="Skip config picker and create a new config via meta-interview.",
    )

    # Shared options
    parser.add_argument(
        "--max-turns", type=int, default=12,
        help="Maximum number of interview turns (default: 12)",
    )
    parser.add_argument(
        "--out", default=None, metavar="DIR",
        help="Output directory for state and vault (default: runs/<name-slug>/)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-turn summaries; only show final report",
    )

    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set. Add it to your .env file.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_brief(args))


if __name__ == "__main__":
    main()
