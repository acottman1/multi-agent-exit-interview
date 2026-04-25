"""
Unit tests for app/vault/vault_compiler.py.

All tests use a minimal in-memory SharedInterviewState — no file I/O except
the temp directory provided by pytest's tmp_path fixture.  No API key needed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.models import (
    Interviewee,
    OpenQuestion,
    SharedInterviewState,
)
from app.graph.schema import GraphEdge, GraphNode, KnowledgeGraph
from app.vault.vault_compiler import (
    _safe_filename,
    _wikilink,
    compile_vault,
    load_final_state,
    save_final_state,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _node(
    node_id: str,
    label: str,
    node_type: str = "Person",
    status: str = "confirmed",
    confidence: float = 0.95,
    aliases: list[str] | None = None,
    attributes: dict | None = None,
) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=node_type,
        label=label,
        aliases=aliases or [],
        attributes=attributes or {},
        status=status,
        confidence=confidence,
        provenance=["test_source"],
    )


def _edge(
    edge_id: str,
    rel_type: str,
    source_id: str,
    target_id: str,
    confidence: float = 0.90,
) -> GraphEdge:
    return GraphEdge(
        id=edge_id,
        type=rel_type,
        source_id=source_id,
        target_id=target_id,
        confidence=confidence,
        provenance=["test_source"],
    )


@pytest.fixture()
def simple_state() -> SharedInterviewState:
    """Minimal two-node, one-edge graph for basic structural tests."""
    nodes = [
        _node("person_alex", "Alex Miller", attributes={"title": "Lead Analyst"}),
        _node("project_falcon", "Project Falcon", node_type="Project", confidence=1.0),
    ]
    edges = [
        _edge("e1", "WORKS_ON", "person_alex", "project_falcon"),
    ]
    return SharedInterviewState(
        interviewee=Interviewee(name="Alex Miller", role="Analyst", project_ids=["project_falcon"]),
        graph=KnowledgeGraph(nodes=nodes, edges=edges),
    )


@pytest.fixture()
def rich_state() -> SharedInterviewState:
    """Richer state for wikilink, category, and content tests."""
    nodes = [
        _node("person_alex",   "Alex Miller",  attributes={"role": "Lead Analyst"}),
        _node("person_sarah",  "Sarah Chen",   confidence=0.88),
        _node("project_falcon","Project Falcon", node_type="Project", confidence=1.0),
        _node("system_snow",   "Snowflake",    node_type="System",   confidence=0.90),
        _node("risk_pipeline", "Undocumented Pipeline Logic", node_type="Risk", confidence=0.88),
        _node("person_super",  "Old Contact",  status="superseded",  confidence=0.50),
    ]
    edges = [
        _edge("e1", "WORKS_ON",  "person_alex",   "project_falcon"),
        _edge("e2", "OWNS",      "person_sarah",  "system_snow"),
        _edge("e3", "AFFECTS",   "risk_pipeline", "project_falcon", confidence=0.85),
    ]
    return SharedInterviewState(
        interviewee=Interviewee(name="Alex Miller", role="Analyst", project_ids=["project_falcon"]),
        graph=KnowledgeGraph(nodes=nodes, edges=edges),
        open_questions=[
            OpenQuestion(
                question_id="q_001",
                text="Who owns the escalation path?",
                rationale="Not yet captured.",
                target_category="workflows",
                priority="high",
            )
        ],
    )


# ── _safe_filename ────────────────────────────────────────────────────────────

class TestSafeFilename:
    def test_spaces_become_underscores(self):
        assert _safe_filename("Alex Miller") == "Alex_Miller"

    def test_special_chars_stripped(self):
        assert _safe_filename("Risk: API Failure!") == "Risk_API_Failure"

    def test_hyphens_become_underscores(self):
        assert _safe_filename("Change-Request Workflow") == "Change_Request_Workflow"

    def test_already_clean(self):
        assert _safe_filename("Snowflake") == "Snowflake"


# ── _wikilink ─────────────────────────────────────────────────────────────────

class TestWikilink:
    def test_person_wikilink(self):
        node = _node("p1", "Richard Jones")
        assert _wikilink(node) == "[[People/Richard_Jones]]"

    def test_system_wikilink(self):
        node = _node("s1", "Snowflake", node_type="System")
        assert _wikilink(node) == "[[Systems/Snowflake]]"

    def test_risk_wikilink(self):
        node = _node("r1", "Undocumented Pipeline Logic", node_type="Risk")
        assert _wikilink(node) == "[[Risks/Undocumented_Pipeline_Logic]]"

    def test_project_wikilink(self):
        node = _node("pj1", "Project Falcon", node_type="Project")
        assert _wikilink(node) == "[[Projects/Project_Falcon]]"


# ── compile_vault — folder structure ──────────────────────────────────────────

class TestVaultFolderStructure:
    def test_output_directory_created(self, simple_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(simple_state, vault)
        assert vault.is_dir()

    def test_index_file_created(self, simple_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(simple_state, vault)
        assert (vault / "index.md").exists()

    def test_category_subdirectories_created(self, rich_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(rich_state, vault)
        assert (vault / "People").is_dir()
        assert (vault / "Projects").is_dir()
        assert (vault / "Systems").is_dir()
        assert (vault / "Risks").is_dir()

    def test_node_files_created(self, simple_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(simple_state, vault)
        assert (vault / "People" / "Alex_Miller.md").exists()
        assert (vault / "Projects" / "Project_Falcon.md").exists()

    def test_superseded_nodes_excluded(self, rich_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(rich_state, vault)
        assert not (vault / "People" / "Old_Contact.md").exists()

    def test_summary_counts_correct(self, rich_state, tmp_path):
        vault = tmp_path / "vault"
        summary = compile_vault(rich_state, vault)
        # 5 non-superseded nodes + 1 index = 6 files
        assert summary["files_written"] == 6
        assert summary["categories"] == 4   # People, Projects, Systems, Risks


# ── compile_vault — node file content ─────────────────────────────────────────

class TestNodeFileContent:
    def _read(self, vault: Path, category: str, stem: str) -> str:
        return (vault / category / f"{stem}.md").read_text(encoding="utf-8")

    def test_frontmatter_present(self, simple_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(simple_state, vault)
        content = self._read(vault, "People", "Alex_Miller")
        assert content.startswith("---\n")
        assert "id: person_alex" in content
        assert "type: Person" in content
        assert "status: confirmed" in content
        assert "confidence: 0.95" in content

    def test_node_label_as_heading(self, simple_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(simple_state, vault)
        content = self._read(vault, "People", "Alex_Miller")
        assert "# Alex Miller" in content

    def test_attributes_rendered(self, simple_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(simple_state, vault)
        content = self._read(vault, "People", "Alex_Miller")
        assert "Lead Analyst" in content

    def test_outgoing_wikilink_in_source_file(self, simple_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(simple_state, vault)
        content = self._read(vault, "People", "Alex_Miller")
        assert "[[Projects/Project_Falcon]]" in content
        assert "WORKS_ON" in content

    def test_incoming_wikilink_in_target_file(self, simple_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(simple_state, vault)
        content = self._read(vault, "Projects", "Project_Falcon")
        # Alex's edge should appear as an incoming link on the project file
        assert "[[People/Alex_Miller]]" in content
        assert "WORKS_ON" in content

    def test_confidence_in_frontmatter(self, simple_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(simple_state, vault)
        content = self._read(vault, "Projects", "Project_Falcon")
        assert "confidence: 1.00" in content

    def test_provenance_section_present(self, simple_state, tmp_path):
        vault = tmp_path / "vault"
        compile_vault(simple_state, vault)
        content = self._read(vault, "People", "Alex_Miller")
        assert "## Provenance" in content
        assert "test_source" in content

    def test_provisional_node_badge(self, tmp_path):
        state = SharedInterviewState(
            interviewee=Interviewee(name="X", role="Y", project_ids=[]),
            graph=KnowledgeGraph(nodes=[
                _node("n1", "Weak Node", status="provisional", confidence=0.65)
            ]),
        )
        compile_vault(state, tmp_path / "vault")
        content = (tmp_path / "vault" / "People" / "Weak_Node.md").read_text(encoding="utf-8")
        assert "🔶" in content


# ── compile_vault — index.md ──────────────────────────────────────────────────

class TestIndexFile:
    def _index(self, state, tmp_path) -> str:
        compile_vault(state, tmp_path / "vault")
        return (tmp_path / "vault" / "index.md").read_text(encoding="utf-8")

    def test_index_contains_interviewee_name(self, simple_state, tmp_path):
        content = self._index(simple_state, tmp_path)
        assert "Alex Miller" in content

    def test_index_lists_all_categories(self, rich_state, tmp_path):
        content = self._index(rich_state, tmp_path)
        assert "### People" in content
        assert "### Projects" in content
        assert "### Systems" in content
        assert "### Risks" in content

    def test_index_links_to_node_files(self, simple_state, tmp_path):
        content = self._index(simple_state, tmp_path)
        assert "People/Alex_Miller" in content
        assert "Projects/Project_Falcon" in content

    def test_index_does_not_list_superseded(self, rich_state, tmp_path):
        content = self._index(rich_state, tmp_path)
        assert "Old_Contact" not in content

    def test_index_shows_coverage_section(self, simple_state, tmp_path):
        content = self._index(simple_state, tmp_path)
        assert "## Coverage" in content

    def test_index_lists_open_questions(self, rich_state, tmp_path):
        content = self._index(rich_state, tmp_path)
        assert "Who owns the escalation path?" in content


# ── State persistence (save / load round-trip) ────────────────────────────────

class TestStatePersistence:
    def test_save_and_load_roundtrip(self, simple_state, tmp_path):
        path = tmp_path / "state.json"
        save_final_state(simple_state, path)
        loaded = load_final_state(path)

        assert loaded.session_id == simple_state.session_id
        assert len(loaded.graph.nodes) == len(simple_state.graph.nodes)
        assert len(loaded.graph.edges) == len(simple_state.graph.edges)

    def test_save_creates_parent_dirs(self, simple_state, tmp_path):
        path = tmp_path / "nested" / "dir" / "state.json"
        save_final_state(simple_state, path)
        assert path.exists()

    def test_saved_file_is_valid_json(self, simple_state, tmp_path):
        path = tmp_path / "state.json"
        save_final_state(simple_state, path)
        parsed = json.loads(path.read_text())
        assert "graph" in parsed
        assert "interviewee" in parsed

    def test_load_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_final_state(tmp_path / "nonexistent.json")

    def test_node_labels_preserved_after_roundtrip(self, rich_state, tmp_path):
        path = tmp_path / "state.json"
        save_final_state(rich_state, path)
        loaded = load_final_state(path)
        original_labels = {n.label for n in rich_state.graph.nodes}
        loaded_labels = {n.label for n in loaded.graph.nodes}
        assert original_labels == loaded_labels
