"""
Unit tests for app/brief/updater.py.

Each class maps to one logical concern so a failure points to exactly
which invariant broke. No LLM calls, no I/O — pure merge logic.
"""
from __future__ import annotations

import pytest

from app.brief.schema import (
    BriefMeta,
    BriefPerson,
    BriefRisk,
    BriefSystem,
    HiringProfile,
    ImplicitKnowledgeItem,
    Responsibility,
    RoleBrief,
    RoleSummary,
)
from app.brief.updater import (
    BriefUpdateResult,
    _add_source_turn_id,
    _merge_dicts,
    _merge_section,
    merge_into_brief,
)


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _brief() -> RoleBrief:
    meta = BriefMeta(
        session_id="sess_test",
        domain_name="test",
        interviewee_name="Alex Rivera",
        role_title="Data Engineer",
    )
    return RoleBrief(meta=meta)


def _responsibility(title: str = "Own pipeline", **kwargs) -> Responsibility:
    return Responsibility(
        title=title,
        description=kwargs.get("description", "Manages the ETL pipeline."),
        criticality=kwargs.get("criticality", "high"),
        frequency=kwargs.get("frequency", "daily"),
        systems_involved=kwargs.get("systems_involved", []),
        people_involved=kwargs.get("people_involved", []),
        source_turn_ids=kwargs.get("source_turn_ids", []),
    )


def _person(name: str = "Sarah Chen", **kwargs) -> BriefPerson:
    return BriefPerson(
        canonical_name=name,
        role_title=kwargs.get("role_title", "Data Engineer"),
        organization=kwargs.get("organization", "Data Team"),
        relationship_type=kwargs.get("relationship_type", "collaborator"),
        continuity_reason=kwargs.get("continuity_reason", "Owns dbt models."),
        source_turn_ids=kwargs.get("source_turn_ids", []),
    )


def _system(name: str = "Snowflake", **kwargs) -> BriefSystem:
    return BriefSystem(
        canonical_name=name,
        ownership_status=kwargs.get("ownership_status", "owned"),
        fragility=kwargs.get("fragility", "medium"),
        documentation_status=kwargs.get("documentation_status", "partially-documented"),
        access_holders=kwargs.get("access_holders", []),
        source_turn_ids=kwargs.get("source_turn_ids", []),
    )


def _risk(title: str = "Pipeline SPOF", **kwargs) -> BriefRisk:
    return BriefRisk(
        title=title,
        description=kwargs.get("description", "Only one person knows how to fix it."),
        risk_type=kwargs.get("risk_type", "single_point_of_failure"),
        severity=kwargs.get("severity", "high"),
        likelihood=kwargs.get("likelihood", "possible"),
        source_turn_ids=kwargs.get("source_turn_ids", []),
    )


def _ik(title: str = "Weekend workaround", **kwargs) -> ImplicitKnowledgeItem:
    return ImplicitKnowledgeItem(
        title=title,
        description=kwargs.get("description", "Re-trigger job 47 on failures."),
        knowledge_type=kwargs.get("knowledge_type", "workaround"),
        urgency=kwargs.get("urgency", "first-week"),
        source_turn_ids=kwargs.get("source_turn_ids", []),
    )


# ── BriefUpdateResult ─────────────────────────────────────────────────────────

class TestBriefUpdateResult:
    def test_total_changes_sums_added_and_updated(self):
        r = BriefUpdateResult(added={"responsibilities": 2}, updated={"people": 1})
        assert r.total_changes == 3

    def test_has_changes_true_when_any_nonzero(self):
        r = BriefUpdateResult(added={"responsibilities": 1})
        assert r.has_changes is True

    def test_has_changes_false_when_all_zero(self):
        r = BriefUpdateResult(added={"responsibilities": 0}, updated={"people": 0})
        assert r.has_changes is False

    def test_has_changes_false_when_empty(self):
        r = BriefUpdateResult()
        assert r.has_changes is False

    def test_summary_describes_changes(self):
        r = BriefUpdateResult(
            added={"responsibilities": 2, "people": 0},
            updated={"responsibilities": 0, "systems": 1},
        )
        text = r.summary()
        assert "responsibilities" in text
        assert "systems" in text

    def test_summary_returns_no_changes_when_empty(self):
        r = BriefUpdateResult()
        assert r.summary() == "no changes"


# ── _merge_dicts ──────────────────────────────────────────────────────────────

class TestMergeDicts:
    def test_dedup_key_never_overwritten(self):
        existing = {"title": "A", "description": "old"}
        incoming = {"title": "B", "description": "new"}
        result = _merge_dicts(existing, incoming, dedup_key="title")
        assert result["title"] == "A"

    def test_scalar_incoming_wins(self):
        existing = {"title": "A", "description": "old"}
        incoming = {"title": "A", "description": "new"}
        result = _merge_dicts(existing, incoming, dedup_key="title")
        assert result["description"] == "new"

    def test_none_incoming_keeps_existing(self):
        existing = {"title": "A", "description": "keep me"}
        incoming = {"title": "A", "description": None}
        result = _merge_dicts(existing, incoming, dedup_key="title")
        assert result["description"] == "keep me"

    def test_empty_string_incoming_keeps_existing(self):
        existing = {"title": "A", "description": "keep me"}
        incoming = {"title": "A", "description": ""}
        result = _merge_dicts(existing, incoming, dedup_key="title")
        assert result["description"] == "keep me"

    def test_list_union_preserves_order(self):
        existing = {"key": "x", "items": ["a", "b"]}
        incoming = {"key": "x", "items": ["b", "c"]}
        result = _merge_dicts(existing, incoming, dedup_key="key")
        assert result["items"] == ["a", "b", "c"]

    def test_list_union_no_duplicates_from_incoming(self):
        existing = {"key": "x", "items": ["a", "b"]}
        incoming = {"key": "x", "items": ["a", "b", "c"]}
        result = _merge_dicts(existing, incoming, dedup_key="key")
        assert result["items"].count("a") == 1
        assert result["items"].count("b") == 1

    def test_list_union_appends_new_items(self):
        existing = {"key": "x", "items": ["a"]}
        incoming = {"key": "x", "items": ["b", "c"]}
        result = _merge_dicts(existing, incoming, dedup_key="key")
        assert result["items"] == ["a", "b", "c"]

    def test_empty_list_incoming_keeps_existing(self):
        existing = {"key": "x", "items": ["a", "b"]}
        incoming = {"key": "x", "items": []}
        result = _merge_dicts(existing, incoming, dedup_key="key")
        assert result["items"] == ["a", "b"]


# ── _add_source_turn_id ───────────────────────────────────────────────────────

class TestAddSourceTurnId:
    def test_appends_new_turn_id(self):
        data = {"source_turn_ids": ["t1"]}
        result = _add_source_turn_id(data, "t2")
        assert result["source_turn_ids"] == ["t1", "t2"]

    def test_does_not_duplicate_existing_id(self):
        data = {"source_turn_ids": ["t1"]}
        result = _add_source_turn_id(data, "t1")
        assert result["source_turn_ids"] == ["t1"]

    def test_none_turn_id_returns_data_unchanged(self):
        data = {"source_turn_ids": ["t1"]}
        result = _add_source_turn_id(data, None)
        assert result["source_turn_ids"] == ["t1"]

    def test_key_absent_returns_data_unchanged(self):
        data = {"title": "x"}
        result = _add_source_turn_id(data, "t1")
        assert "source_turn_ids" not in result


# ── _merge_section ────────────────────────────────────────────────────────────

class TestMergeSection:
    def test_new_item_appended_with_added_count(self):
        merged, added, updated = _merge_section(
            [], [_responsibility("New task")], "title", Responsibility, "t1"
        )
        assert added == 1
        assert updated == 0
        assert len(merged) == 1
        assert merged[0].title == "New task"

    def test_existing_key_updated_not_duplicated(self):
        existing = _responsibility("Own pipeline", description="old")
        incoming = _responsibility("Own pipeline", description="new and better")
        merged, added, updated = _merge_section(
            [existing], [incoming], "title", Responsibility, "t2"
        )
        assert added == 0
        assert updated == 1
        assert len(merged) == 1
        assert merged[0].description == "new and better"

    def test_existing_order_preserved_new_items_appended(self):
        a = _responsibility("Task A")
        b = _responsibility("Task B")
        c = _responsibility("Task C")
        merged, added, _ = _merge_section(
            [a, b], [c, a], "title", Responsibility, None
        )
        assert [r.title for r in merged] == ["Task A", "Task B", "Task C"]
        assert added == 1

    def test_source_turn_id_appended_on_update(self):
        existing = _responsibility("Own pipeline", source_turn_ids=["t1"])
        incoming = _responsibility("Own pipeline")
        merged, _, _ = _merge_section(
            [existing], [incoming], "title", Responsibility, "t2"
        )
        assert "t1" in merged[0].source_turn_ids
        assert "t2" in merged[0].source_turn_ids

    def test_source_turn_id_appended_on_add(self):
        merged, _, _ = _merge_section(
            [], [_responsibility("New task")], "title", Responsibility, "t5"
        )
        assert "t5" in merged[0].source_turn_ids

    def test_list_fields_unioned_on_update(self):
        existing = _responsibility("Own pipeline", systems_involved=["Snowflake"])
        incoming = _responsibility("Own pipeline", systems_involved=["Databricks"])
        merged, _, _ = _merge_section(
            [existing], [incoming], "title", Responsibility, None
        )
        assert "Snowflake" in merged[0].systems_involved
        assert "Databricks" in merged[0].systems_involved


# ── merge_into_brief ──────────────────────────────────────────────────────────

class TestMergeIntoBrief:
    def test_adds_responsibility(self):
        brief = _brief()
        result = merge_into_brief(brief, responsibilities=[_responsibility()])
        assert len(brief.responsibilities) == 1
        assert result.added.get("responsibilities") == 1

    def test_adds_person(self):
        brief = _brief()
        result = merge_into_brief(brief, people=[_person()])
        assert len(brief.people) == 1
        assert result.added.get("people") == 1

    def test_adds_system(self):
        brief = _brief()
        result = merge_into_brief(brief, systems=[_system()])
        assert len(brief.systems) == 1
        assert result.added.get("systems") == 1

    def test_adds_risk(self):
        brief = _brief()
        result = merge_into_brief(brief, risks=[_risk()])
        assert len(brief.risks) == 1
        assert result.added.get("risks") == 1

    def test_adds_implicit_knowledge(self):
        brief = _brief()
        result = merge_into_brief(brief, implicit_knowledge=[_ik()])
        assert len(brief.implicit_knowledge) == 1
        assert result.added.get("implicit_knowledge") == 1

    def test_no_args_returns_no_changes(self):
        brief = _brief()
        result = merge_into_brief(brief)
        assert result.has_changes is False

    def test_empty_lists_return_no_changes(self):
        brief = _brief()
        result = merge_into_brief(brief, responsibilities=[], people=[])
        assert result.has_changes is False

    def test_deduplicates_repeated_call(self):
        brief = _brief()
        resp = _responsibility("Own pipeline")
        merge_into_brief(brief, responsibilities=[resp])
        merge_into_brief(brief, responsibilities=[resp])
        assert len(brief.responsibilities) == 1

    def test_role_summary_set_on_first_call(self):
        brief = _brief()
        summary = RoleSummary(
            one_liner="Owns the data platform end-to-end.",
            formal_vs_actual="Formal title is Analyst; actually runs engineering.",
        )
        merge_into_brief(brief, role_summary=summary)
        assert brief.role_summary is not None
        assert brief.role_summary.one_liner == "Owns the data platform end-to-end."

    def test_role_summary_merged_on_second_call(self):
        brief = _brief()
        s1 = RoleSummary(one_liner="Initial", formal_vs_actual="same")
        s2 = RoleSummary(one_liner="Updated", formal_vs_actual="different")
        merge_into_brief(brief, role_summary=s1)
        merge_into_brief(brief, role_summary=s2)
        assert brief.role_summary.one_liner == "Updated"
        assert brief.role_summary.formal_vs_actual == "different"

    def test_hiring_profile_set_on_first_call(self):
        brief = _brief()
        hp = HiringProfile(
            role_title="Data Engineer",
            required_skills=["Python", "SQL"],
        )
        merge_into_brief(brief, hiring_profile=hp)
        assert brief.hiring_profile is not None
        assert "Python" in brief.hiring_profile.required_skills

    def test_hiring_profile_skills_unioned_on_second_call(self):
        brief = _brief()
        hp1 = HiringProfile(role_title="Data Engineer", required_skills=["Python"])
        hp2 = HiringProfile(role_title="Data Engineer", required_skills=["SQL"])
        merge_into_brief(brief, hiring_profile=hp1)
        merge_into_brief(brief, hiring_profile=hp2)
        assert "Python" in brief.hiring_profile.required_skills
        assert "SQL" in brief.hiring_profile.required_skills

    def test_source_turn_id_propagated_to_items(self):
        brief = _brief()
        merge_into_brief(brief, responsibilities=[_responsibility()], source_turn_id="turn_03")
        assert "turn_03" in brief.responsibilities[0].source_turn_ids

    def test_multiple_sections_in_one_call(self):
        brief = _brief()
        result = merge_into_brief(
            brief,
            responsibilities=[_responsibility()],
            people=[_person()],
            systems=[_system()],
        )
        assert len(brief.responsibilities) == 1
        assert len(brief.people) == 1
        assert len(brief.systems) == 1
        assert result.total_changes == 3


# ── Realistic multi-turn scenario ────────────────────────────────────────────

class TestRealisticScenario:
    def test_person_continuity_reason_updated_across_turns(self):
        """
        Turn 1 captures Sarah with a vague continuity reason.
        Turn 2 adds specifics — the more detailed description wins.
        """
        brief = _brief()
        t1_person = _person("Sarah Chen", continuity_reason="Important contact.")
        t2_person = _person("Sarah Chen", continuity_reason="Owns all dbt models; pipeline breaks without her.")

        merge_into_brief(brief, people=[t1_person], source_turn_id="t1")
        merge_into_brief(brief, people=[t2_person], source_turn_id="t2")

        assert len(brief.people) == 1
        assert "dbt models" in brief.people[0].continuity_reason
        assert "t1" in brief.people[0].source_turn_ids
        assert "t2" in brief.people[0].source_turn_ids

    def test_system_access_holders_accumulate(self):
        """
        Access holders for Snowflake grow as more names surface across turns.
        """
        brief = _brief()
        t1 = _system("Snowflake", access_holders=["Alex Rivera"])
        t2 = _system("Snowflake", access_holders=["Sarah Chen"])
        t3 = _system("Snowflake", access_holders=["Marcus Webb"])

        merge_into_brief(brief, systems=[t1], source_turn_id="t1")
        merge_into_brief(brief, systems=[t2], source_turn_id="t2")
        merge_into_brief(brief, systems=[t3], source_turn_id="t3")

        assert len(brief.systems) == 1
        holders = brief.systems[0].access_holders
        assert "Alex Rivera" in holders
        assert "Sarah Chen" in holders
        assert "Marcus Webb" in holders

    def test_three_new_risks_added_across_turns(self):
        brief = _brief()
        for i in range(3):
            merge_into_brief(brief, risks=[_risk(f"Risk {i}")], source_turn_id=f"t{i}")
        assert len(brief.risks) == 3

    def test_section_item_count_reflects_state(self):
        brief = _brief()
        merge_into_brief(
            brief,
            responsibilities=[_responsibility("A"), _responsibility("B")],
            people=[_person("X"), _person("Y"), _person("Z")],
        )
        counts = brief.section_item_count()
        assert counts["responsibilities"] == 2
        assert counts["people"] == 3
