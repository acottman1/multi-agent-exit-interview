"""
Obsidian Vault Compiler — Phase 7.

Constraint §26-6: This module runs AFTER the interview ends as a standalone
post-processing step.  It must never be imported or called during a live
turn loop.

Entry points
------------
compile_vault(state, output_dir)   — called programmatically
main()                             — CLI: reads final_state.json, writes vault

Output layout
-------------
exit_interview_vault/
  index.md                 # master index grouped by category
  People/
    Alex_Miller.md
    Richard_Jones.md
  Systems/
    Snowflake.md
  Workflows/
    Change_Request_Workflow.md
  ...  (one sub-folder per node type)

Each node file contains:
  - YAML frontmatter  (id, type, status, confidence, provenance, timestamps)
  - Human-readable body  (attributes, then edges as [[wikilinks]])
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.models import SharedInterviewState
from app.graph.schema import GraphEdge, GraphNode, KnowledgeGraph

# ── Node-type → vault sub-folder mapping ─────────────────────────────────────

_CATEGORY: dict[str, str] = {
    "Person":    "People",
    "Role":      "People",
    "Team":      "Teams",
    "Project":   "Projects",
    "Client":    "Clients",
    "System":    "Systems",
    "Document":  "Documents",
    "Workflow":  "Workflows",
    "Task":      "Tasks",
    "Decision":  "Decisions",
    "Risk":      "Risks",
    "Issue":     "Issues",
}


# ── Filename helpers ──────────────────────────────────────────────────────────

def _safe_filename(label: str) -> str:
    """Convert a node label to a safe filename stem (no extension)."""
    name = label.strip()
    name = re.sub(r"[^\w\s\-]", "", name)       # strip special chars
    name = re.sub(r"[\s\-]+", "_", name)         # spaces/hyphens → underscore
    return name


def _wikilink(node: GraphNode) -> str:
    """Return the Obsidian [[wikilink]] for a node."""
    stem = _safe_filename(node.label)
    category = _CATEGORY.get(node.type, node.type)
    return f"[[{category}/{stem}]]"


# ── Edge index ────────────────────────────────────────────────────────────────

def _build_edge_index(
    graph: KnowledgeGraph,
) -> dict[str, list[GraphEdge]]:
    """Return a mapping of node_id → all edges where the node is source OR target."""
    index: dict[str, list[GraphEdge]] = defaultdict(list)
    for edge in graph.edges:
        if edge.status == "superseded":
            continue
        index[edge.source_id].append(edge)
        index[edge.target_id].append(edge)
    return dict(index)


def _node_lookup(graph: KnowledgeGraph) -> dict[str, GraphNode]:
    return {n.id: n for n in graph.nodes}


# ── Individual node file renderer ─────────────────────────────────────────────

def _render_node_file(
    node: GraphNode,
    edges: list[GraphEdge],
    lookup: dict[str, GraphNode],
) -> str:
    lines: list[str] = []

    # YAML frontmatter
    lines += [
        "---",
        f"id: {node.id}",
        f"type: {node.type}",
        f"status: {node.status}",
        f"confidence: {node.confidence:.2f}",
        "provenance:",
    ]
    for p in node.provenance:
        lines.append(f"  - {p}")
    lines += [
        f"created_at: {node.created_at.isoformat()}",
        f"updated_at: {node.updated_at.isoformat()}",
    ]
    if node.superseded_by:
        lines.append(f"superseded_by: {node.superseded_by}")
    if node.aliases:
        lines.append("aliases:")
        for a in node.aliases:
            lines.append(f"  - {a}")
    lines.append("---")
    lines.append("")

    # Title and status badge
    status_badge = {"confirmed": "✅", "provisional": "🔶", "superseded": "❌"}.get(
        node.status, ""
    )
    lines.append(f"# {node.label}  {status_badge}")
    lines.append("")
    lines.append(f"**Type:** {node.type}  ")
    lines.append(f"**Confidence:** {node.confidence:.0%}  ")
    lines.append(f"**Status:** {node.status}  ")
    lines.append("")

    # Attributes
    if node.attributes:
        lines.append("## Attributes")
        lines.append("")
        for key, val in node.attributes.items():
            display_key = key.replace("_", " ").title()
            lines.append(f"- **{display_key}:** {val}")
        lines.append("")

    # Relationships (bidirectional)
    if edges:
        lines.append("## Relationships")
        lines.append("")
        for edge in sorted(edges, key=lambda e: e.type):
            if edge.source_id == node.id:
                # outgoing
                target = lookup.get(edge.target_id)
                if target:
                    link = _wikilink(target)
                    conf = f"  *(conf: {edge.confidence:.0%})*"
                    lines.append(f"- **{edge.type}** → {link}{conf}")
            else:
                # incoming
                source = lookup.get(edge.source_id)
                if source:
                    link = _wikilink(source)
                    conf = f"  *(conf: {edge.confidence:.0%})*"
                    lines.append(f"- ← **{edge.type}** from {link}{conf}")
        lines.append("")

    # Provenance footer
    lines.append("## Provenance")
    lines.append("")
    for p in node.provenance:
        lines.append(f"- {p}")
    lines.append("")

    return "\n".join(lines)


# ── Index file renderer ───────────────────────────────────────────────────────

def _render_index(
    state: SharedInterviewState,
    lookup: dict[str, GraphNode],
) -> str:
    lines: list[str] = []
    lines += [
        "# Knowledge Graph — Exit Interview Vault",
        "",
        f"> **Interviewee:** {state.interviewee.name} — {state.interviewee.role}  ",
        f"> **Session:** {state.session_id}  ",
        f"> **Turns completed:** {len(state.turns)}  ",
        f"> **Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        "",
        "---",
        "",
        "## Coverage",
        "",
    ]

    cov = state.coverage
    for field in type(cov).model_fields:
        score = getattr(cov, field)
        bar = "█" * int(score * 20) + "░" * (20 - int(score * 20))
        display = field.replace("_", " ").title()
        lines.append(f"- **{display}** `{bar}` {score:.0%}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Group nodes by category, skip superseded
    by_category: dict[str, list[GraphNode]] = defaultdict(list)
    for node in state.graph.nodes:
        if node.status == "superseded":
            continue
        category = _CATEGORY.get(node.type, node.type)
        by_category[category].append(node)

    lines.append("## Entities by Category")
    lines.append("")
    for category in sorted(by_category):
        nodes = sorted(by_category[category], key=lambda n: n.label)
        lines.append(f"### {category}")
        lines.append("")
        for node in nodes:
            stem = _safe_filename(node.label)
            badge = {"confirmed": "✅", "provisional": "🔶"}.get(node.status, "")
            lines.append(f"- {badge} [[{category}/{stem}|{node.label}]]")
        lines.append("")

    # Unresolved ambiguities
    unresolved = [a for a in state.ambiguities if not a.resolved]
    if unresolved:
        lines += ["---", "", "## ⚠ Unresolved Ambiguities", ""]
        for amb in unresolved:
            lines.append(f"- **{amb.target}** — {amb.reason}")
        lines.append("")

    # Open questions
    asked = set(state.asked_question_ids)
    pending = [q for q in state.open_questions if q.question_id not in asked]
    if pending:
        lines += ["---", "", "## 📋 Remaining Open Questions", ""]
        for q in sorted(pending, key=lambda q: q.priority):
            lines.append(f"- `[{q.priority}]` {q.text}")
        lines.append("")

    return "\n".join(lines)


# ── Main compiler ─────────────────────────────────────────────────────────────

def compile_vault(
    state: SharedInterviewState,
    output_dir: Path,
) -> dict[str, int]:
    """
    Write the Obsidian vault to output_dir.

    Returns a summary dict: {"files_written": N, "categories": M}.
    Superseded nodes are excluded from the vault.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    edge_index = _build_edge_index(state.graph)
    lookup = _node_lookup(state.graph)
    files_written = 0

    # Write one .md file per non-superseded node
    for node in state.graph.nodes:
        if node.status == "superseded":
            continue

        category = _CATEGORY.get(node.type, node.type)
        category_dir = output_dir / category
        category_dir.mkdir(exist_ok=True)

        stem = _safe_filename(node.label)
        node_file = category_dir / f"{stem}.md"
        edges = edge_index.get(node.id, [])

        node_file.write_text(
            _render_node_file(node, edges, lookup), encoding="utf-8"
        )
        files_written += 1

    # Write index.md
    index_file = output_dir / "index.md"
    index_file.write_text(_render_index(state, lookup), encoding="utf-8")
    files_written += 1

    categories_used = {
        _CATEGORY.get(n.type, n.type)
        for n in state.graph.nodes
        if n.status != "superseded"
    }

    return {"files_written": files_written, "categories": len(categories_used)}


# ── State persistence helpers ─────────────────────────────────────────────────

def save_final_state(state: SharedInterviewState, path: Path) -> None:
    """Serialize the full SharedInterviewState to JSON for later vault compilation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def load_final_state(path: Path) -> SharedInterviewState:
    """Load a previously saved SharedInterviewState from JSON."""
    if not path.exists():
        raise FileNotFoundError(f"State file not found: {path}")
    return SharedInterviewState.model_validate_json(path.read_text(encoding="utf-8"))


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    """
    Usage:
        python -m app.vault.vault_compiler [final_state.json] [output_dir]

    Defaults:
        input  → runs/final_state.json
        output → exit_interview_vault/
    """
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("runs/final_state.json")
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("exit_interview_vault")

    print(f"Loading state from {input_path} …")
    state = load_final_state(input_path)

    print(f"Compiling vault → {output_path}/ …")
    summary = compile_vault(state, output_path)

    print(
        f"Done. {summary['files_written']} files written across "
        f"{summary['categories']} categories."
    )
    print(f"Open {output_path}/index.md in Obsidian to explore.")


if __name__ == "__main__":
    main()
