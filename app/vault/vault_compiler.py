"""
Obsidian Vault Compiler — Phase 7.

Constraint §26-6: This module runs AFTER the interview ends as a standalone
post-processing step.  It must never be imported or called during a live
turn loop.

Entry points
------------
compile_vault(state, output_dir)         — graph engine (called programmatically)
compile_brief_vault(brief, config, dir)  — brief engine (called programmatically)
main()                                   — CLI: --engine graph|brief

Output layout (graph engine)
-----------------------------
exit_interview_vault/
  index.md
  People/Alex_Miller.md ...

Output layout (brief engine)
-----------------------------
<slug>_brief/
  <interviewee_slug>.md     # single comprehensive file
  index.md                  # links to all compiled briefs in directory
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


# ── State persistence helpers (graph engine) ──────────────────────────────────

def save_final_state(state: SharedInterviewState, path: Path) -> None:
    """Serialize the full SharedInterviewState to JSON for later vault compilation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def load_final_state(path: Path) -> SharedInterviewState:
    """Load a previously saved SharedInterviewState from JSON."""
    if not path.exists():
        raise FileNotFoundError(f"State file not found: {path}")
    return SharedInterviewState.model_validate_json(path.read_text(encoding="utf-8"))


# ── Brief vault: Mustache renderer ───────────────────────────────────────────

def _mustache_render(template: str, context: dict) -> str:
    """
    Minimal Mustache renderer supporting:
      {{field}}                    — scalar substitution
      {{#list}}...{{.}}...{{/list}} — list iteration ({{.}} = item)

    Does NOT support nested sections, lambdas, or partials — the vault
    templates only use these two constructs.
    """
    # 1. List sections: {{#key}}...body...{{/key}}
    def _render_section(m: re.Match) -> str:
        key = m.group(1)
        body = m.group(2)
        items = context.get(key) or []
        if not items:
            return ""
        parts: list[str] = []
        for item in items:
            # {{.}} → the item itself (string)
            parts.append(body.replace("{{.}}", str(item)))
        return "".join(parts)

    result = re.sub(
        r"\{\{#(\w+)\}\}(.*?)\{\{/\1\}\}",
        _render_section,
        template,
        flags=re.DOTALL,
    )

    # 2. Scalar substitution: {{field}}
    def _render_scalar(m: re.Match) -> str:
        key = m.group(1)
        val = context.get(key)
        if val is None:
            return ""
        return str(val)

    result = re.sub(r"\{\{(\w+)\}\}", _render_scalar, result)
    return result


def _to_wikilink(value: str) -> str:
    """Wrap a plain name in [[double brackets]] if not already wrapped."""
    value = value.strip()
    if value.startswith("[[") and value.endswith("]]"):
        return value
    return f"[[{value}]]"


def _apply_wikilinks(data: dict, wikilink_fields: list[str]) -> dict:
    """
    Return a copy of data with the specified fields wrapped as [[wikilinks]].
    List fields are wrapped per-item; scalar fields are wrapped whole.
    """
    result = dict(data)
    for field in wikilink_fields:
        val = result.get(field)
        if val is None:
            continue
        if isinstance(val, list):
            result[field] = [_to_wikilink(str(v)) for v in val if v]
        elif val:
            result[field] = _to_wikilink(str(val))
    return result


# ── Brief vault: fallback section templates ───────────────────────────────────

_DEFAULT_SECTION_TEMPLATES: dict[str, str] = {
    "responsibility_item": (
        "### {{title}}\n"
        "**Criticality:** {{criticality}}  |  **Frequency:** {{frequency}}  |  "
        "**Handoff:** {{handoff_status}}\n\n"
        "{{description}}\n\n"
    ),
    "person_item": (
        "### {{canonical_name}}\n"
        "**Role:** {{role_title}}  |  **Org:** {{organization}}  |  "
        "**Relationship:** {{relationship_type}}\n\n"
        "{{continuity_reason}}\n\n"
    ),
    "system_item": (
        "### {{canonical_name}}\n"
        "**Ownership:** {{ownership_status}}  |  **Fragility:** {{fragility}}  |  "
        "**Docs:** {{documentation_status}}\n\n"
        "{{gotchas}}\n\n"
    ),
    "implicit_knowledge_item": (
        "### {{title}}\n"
        "**Type:** {{knowledge_type}}  |  **Urgency:** {{urgency}}\n\n"
        "{{description}}\n\n"
    ),
    "risk_item": (
        "### {{title}}\n"
        "**Type:** {{risk_type}}  |  **Severity:** {{severity}}  |  "
        "**Likelihood:** {{likelihood}}\n\n"
        "{{description}}\n\n"
        "**Mitigation:** {{mitigation}}\n\n"
    ),
    "hiring_profile_item": (
        "**Role:** {{role_title}}\n\n"
        "{{background_note}}\n\n"
    ),
}


# ── Brief vault: section renderers ───────────────────────────────────────────

def _render_brief_section(
    items: list,
    template: str,
    wikilink_fields: list[str],
) -> str:
    """Render a list of Pydantic items using the given Mustache template."""
    if not items:
        return ""
    parts: list[str] = []
    for item in items:
        raw = item.model_dump()
        ctx = _apply_wikilinks(raw, wikilink_fields)
        # Booleans → human-readable
        for k, v in ctx.items():
            if isinstance(v, bool):
                ctx[k] = "Yes" if v else "No"
        parts.append(_mustache_render(template, ctx))
    return "\n".join(parts)


def _render_brief_file(
    brief,          # RoleBrief
    config,         # DomainConfig
    turns=None,     # list[InterviewTurn] | None
) -> str:
    """Render a single comprehensive Markdown document for the brief."""
    templates = config.vault_templates
    targets = config.extraction_targets
    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────────
    header_template = templates.get("brief_header", "# Role Brief: {{role_title}}\n")
    # Build context from all meta fields so any template placeholder resolves.
    meta_dict = brief.meta.model_dump()
    # Serialize datetime to string so Mustache doesn't emit repr().
    for k, v in meta_dict.items():
        if isinstance(v, datetime):
            meta_dict[k] = v.strftime("%Y-%m-%d")
    header_ctx = {
        **meta_dict,
        # Common aliases — templates may use any of these names.
        "employee_name": brief.meta.interviewee_name,
        "name": brief.meta.interviewee_name,
        "role": brief.meta.role_title,
        "last_day": brief.meta.last_day or "TBD",
        "team_name": brief.meta.team_name or "",
        "manager_name": brief.meta.manager_name or "",
        "completeness_score": f"{brief.meta.completeness_score:.0%}",
        "one_liner": brief.role_summary.one_liner if brief.role_summary else "",
        "formal_vs_actual": brief.role_summary.formal_vs_actual if brief.role_summary else "",
        # Interview date formatted nicely
        "interview_date": (
            brief.meta.interview_date.strftime("%Y-%m-%d")
            if not isinstance(brief.meta.interview_date, str)
            else brief.meta.interview_date
        ),
    }
    lines.append(_mustache_render(header_template, header_ctx))

    # ── Responsibilities ───────────────────────────────────────────────────────
    resp_template = (
        templates.get("responsibility_item")
        or _DEFAULT_SECTION_TEMPLATES["responsibility_item"]
    )
    if brief.responsibilities:
        lines.append("## Responsibilities & Ownership\n")
        wf = targets.get("responsibilities", {})
        wikilink_fields = wf.wikilink_fields if hasattr(wf, "wikilink_fields") else []
        lines.append(_render_brief_section(brief.responsibilities, resp_template, wikilink_fields))

    # ── People ────────────────────────────────────────────────────────────────
    person_template = (
        templates.get("person_item")
        or _DEFAULT_SECTION_TEMPLATES["person_item"]
    )
    if brief.people:
        lines.append("## Key People & Relationships\n")
        wf = targets.get("people", {})
        wikilink_fields = wf.wikilink_fields if hasattr(wf, "wikilink_fields") else []
        lines.append(_render_brief_section(brief.people, person_template, wikilink_fields))

    # ── Systems ───────────────────────────────────────────────────────────────
    system_template = (
        templates.get("system_item")
        or _DEFAULT_SECTION_TEMPLATES["system_item"]
    )
    if brief.systems:
        lines.append("## Systems & Tools\n")
        wf = targets.get("systems", {})
        wikilink_fields = wf.wikilink_fields if hasattr(wf, "wikilink_fields") else []
        lines.append(_render_brief_section(brief.systems, system_template, wikilink_fields))

    # ── Implicit knowledge ────────────────────────────────────────────────────
    ik_template = (
        templates.get("implicit_knowledge_item")
        or _DEFAULT_SECTION_TEMPLATES["implicit_knowledge_item"]
    )
    if brief.implicit_knowledge:
        lines.append("## Implicit & Undocumented Knowledge\n")
        wf = targets.get("implicit_knowledge", {})
        wikilink_fields = wf.wikilink_fields if hasattr(wf, "wikilink_fields") else []
        lines.append(_render_brief_section(brief.implicit_knowledge, ik_template, wikilink_fields))

    # ── Risks ─────────────────────────────────────────────────────────────────
    risk_template = (
        templates.get("risk_item")
        or _DEFAULT_SECTION_TEMPLATES["risk_item"]
    )
    if brief.risks:
        lines.append("## Risks & Single Points of Failure\n")
        wf = targets.get("risks", {})
        wikilink_fields = wf.wikilink_fields if hasattr(wf, "wikilink_fields") else []
        lines.append(_render_brief_section(brief.risks, risk_template, wikilink_fields))

    # ── Hiring profile ────────────────────────────────────────────────────────
    hp_template = (
        templates.get("hiring_profile_item")
        or _DEFAULT_SECTION_TEMPLATES["hiring_profile_item"]
    )
    if brief.hiring_profile:
        lines.append("## Hiring Profile for Successor\n")
        wf = targets.get("hiring_profile", {})
        wikilink_fields = wf.wikilink_fields if hasattr(wf, "wikilink_fields") else []
        lines.append(_render_brief_section([brief.hiring_profile], hp_template, wikilink_fields))

    # ── Open questions ────────────────────────────────────────────────────────
    if brief.open_questions:
        oq_lines = ["## Open Questions & Unresolved Ambiguities\n"]
        for q in brief.open_questions:
            oq_lines.append(f"- {q}")
        oq_lines.append("")
        lines.append("\n".join(oq_lines))

    # ── Interview transcript ──────────────────────────────────────────────────
    if turns:
        lines.append("---\n")
        lines.append("## Interview Transcript\n")
        for turn in turns:
            lines.append(f"**Q{turn.turn_number}: {turn.question}**\n")
            lines.append(f"{turn.answer}\n")

    return "\n".join(lines)


# ── Brief vault: main entry point ─────────────────────────────────────────────

def compile_brief_vault(
    brief,          # RoleBrief
    config,         # DomainConfig
    output_dir: Path,
    turns=None,     # list[InterviewTurn] | None
) -> dict[str, int]:
    """
    Write an Obsidian-compatible brief vault to output_dir.

    Creates:
      <output_dir>/<interviewee_slug>.md   — full brief document
      <output_dir>/index.md                — index of all .md files in the dir

    Returns {"files_written": N}.
    Constraint §26-6: must only be called post-interview.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Render the brief
    content = _render_brief_file(brief, config, turns=turns)
    slug = _safe_filename(brief.meta.interviewee_name) or brief.brief_id
    brief_file = output_dir / f"{slug}.md"
    brief_file.write_text(content, encoding="utf-8")
    files_written = 1

    # Write or update the index
    _write_brief_index(output_dir)
    files_written += 1

    return {"files_written": files_written}


def _write_brief_index(output_dir: Path) -> None:
    """Write an index.md that links to every brief .md in the directory."""
    brief_files = sorted(
        p for p in output_dir.glob("*.md") if p.stem != "index"
    )
    lines = [
        "# Role Brief Vault — Index",
        "",
        f"> **Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Compiled briefs",
        "",
    ]
    for p in brief_files:
        display = p.stem.replace("_", " ")
        lines.append(f"- [[{p.stem}|{display}]]")
    lines.append("")
    (output_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


# ── Brief state persistence helpers ───────────────────────────────────────────

def save_brief_state(state, path: Path) -> None:  # state: BriefSessionState
    """Serialize a BriefSessionState to JSON for later vault compilation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def load_brief_state(path: Path):  # -> BriefSessionState
    """Load a previously saved BriefSessionState from JSON."""
    from app.brief.session import BriefSessionState

    if not path.exists():
        raise FileNotFoundError(f"Brief state file not found: {path}")
    return BriefSessionState.model_validate_json(path.read_text(encoding="utf-8"))


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    """
    Usage:
        python -m app.vault.vault_compiler [options] [input] [output_dir]

    Options:
        --engine graph   (default) compile KnowledgeGraph vault from final_state.json
        --engine brief   compile RoleBrief vault from brief_state.json

    Defaults:
        graph: input → runs/final_state.json,  output → exit_interview_vault/
        brief: input → runs/brief_state.json,  output → role_brief_vault/
    """
    args = sys.argv[1:]
    engine = "graph"
    if "--engine" in args:
        idx = args.index("--engine")
        engine = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    if engine == "brief":
        input_path = Path(args[0]) if args else Path("runs/brief_state.json")
        output_path = Path(args[1]) if len(args) > 1 else Path("role_brief_vault")

        print(f"Loading brief state from {input_path} …")
        state = load_brief_state(input_path)
        from app.config.config_store import load_domain_config
        config = load_domain_config(state.domain_config.domain_name)

        print(f"Compiling brief vault → {output_path}/ …")
        summary = compile_brief_vault(state.brief, config, output_path, turns=state.turns)
        print(f"Done. {summary['files_written']} files written.")
        print(f"Open {output_path}/index.md in Obsidian to explore.")

    else:
        input_path = Path(args[0]) if args else Path("runs/final_state.json")
        output_path = Path(args[1]) if len(args) > 1 else Path("exit_interview_vault")

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
