"""
Contract tests for the five brief-engine extraction agents.

Mirrors tests/contracts/test_agent_contracts.py for the graph engine.
Verifies:
  1. Each agent accepts exactly the state slice its function signature declares (§26-4).
  2. Each agent returns the correct Pydantic output model.
  3. Each agent handles empty extraction correctly (no items found).

The instructor client is monkeypatched so no real API calls are made.
"""
from __future__ import annotations

import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.brief.schema import (
    BriefPerson,
    BriefRisk,
    BriefSystem,
    ImplicitKnowledgeItem,
    Responsibility,
)
from app.brief.extraction_models import (
    ImplicitKnowledgeExtractionOutput,
    PeopleExtractionOutput,
    ResponsibilityExtractionOutput,
    RiskExtractionOutput,
    SystemsExtractionOutput,
)
from app.core.models import InterviewTurn


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture()
def sample_turn() -> InterviewTurn:
    return InterviewTurn(
        turn_number=1,
        question="Walk me through what you actually own day-to-day.",
        question_rationale="Mapping responsibilities.",
        answer=(
            "I own the monthly reporting pipeline in Snowflake and the Airflow DAGs "
            "that feed it. Sarah from the data team helps with the dbt models, and "
            "Marcus in finance is the main consumer. There's a workaround in the "
            "staging environment that only I know about — if the ETL fails on weekends "
            "you have to manually re-trigger job 47."
        ),
    )


def _mock_client(return_value) -> MagicMock:
    """Return a mock instructor async client whose messages.create resolves to return_value."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=return_value)
    return client


# ── Responsibility extractor ──────────────────────────────────────────────────

class TestResponsibilityExtractorContract:
    async def test_returns_responsibility_extraction_output(self, monkeypatch, sample_turn):
        from app.agents import responsibility_extractor

        expected = ResponsibilityExtractionOutput(responsibilities=[
            Responsibility(
                title="Own monthly reporting pipeline",
                description="Maintains Snowflake pipeline and Airflow DAGs.",
                criticality="high",
                frequency="monthly",
            )
        ])
        monkeypatch.setattr(responsibility_extractor, "get_client", lambda: _mock_client(expected))

        result = await responsibility_extractor.extract_responsibilities(sample_turn, [])

        assert isinstance(result, ResponsibilityExtractionOutput)
        assert len(result.responsibilities) == 1
        assert result.responsibilities[0].title == "Own monthly reporting pipeline"

    async def test_returns_empty_when_nothing_extracted(self, monkeypatch, sample_turn):
        from app.agents import responsibility_extractor

        expected = ResponsibilityExtractionOutput(responsibilities=[])
        monkeypatch.setattr(responsibility_extractor, "get_client", lambda: _mock_client(expected))

        result = await responsibility_extractor.extract_responsibilities(sample_turn, [])
        assert result.responsibilities == []

    async def test_accepts_state_slice_only(self):
        """§26-4: function must accept only (turn, known_titles)."""
        from app.agents import responsibility_extractor

        params = list(inspect.signature(responsibility_extractor.extract_responsibilities).parameters)
        assert params == ["turn", "known_titles"]

    async def test_known_titles_passed_as_list(self, monkeypatch, sample_turn):
        """Known titles are passed as a plain list of strings."""
        from app.agents import responsibility_extractor

        expected = ResponsibilityExtractionOutput(responsibilities=[])
        monkeypatch.setattr(responsibility_extractor, "get_client", lambda: _mock_client(expected))

        result = await responsibility_extractor.extract_responsibilities(
            sample_turn, ["Own monthly reporting pipeline"]
        )
        assert isinstance(result, ResponsibilityExtractionOutput)


# ── People extractor ──────────────────────────────────────────────────────────

class TestPeopleExtractorContract:
    async def test_returns_people_extraction_output(self, monkeypatch, sample_turn):
        from app.agents import people_extractor

        expected = PeopleExtractionOutput(people=[
            BriefPerson(
                canonical_name="Sarah Chen",
                role_title="Data Engineer",
                organization="Data Team",
                relationship_type="collaborator",
                continuity_reason="Owns the dbt models the pipeline depends on.",
            )
        ])
        monkeypatch.setattr(people_extractor, "get_client", lambda: _mock_client(expected))

        result = await people_extractor.extract_people(sample_turn, {})

        assert isinstance(result, PeopleExtractionOutput)
        assert result.people[0].canonical_name == "Sarah Chen"
        assert result.people[0].relationship_type == "collaborator"

    async def test_returns_empty_when_nothing_extracted(self, monkeypatch, sample_turn):
        from app.agents import people_extractor

        expected = PeopleExtractionOutput(people=[])
        monkeypatch.setattr(people_extractor, "get_client", lambda: _mock_client(expected))

        result = await people_extractor.extract_people(sample_turn, {})
        assert result.people == []

    async def test_accepts_state_slice_only(self):
        """§26-4: function must accept only (turn, known_people)."""
        from app.agents import people_extractor

        params = list(inspect.signature(people_extractor.extract_people).parameters)
        assert params == ["turn", "known_people"]

    async def test_known_people_passed_as_dict(self, monkeypatch, sample_turn):
        """Known people slice is a dict {canonical_name: role_title}."""
        from app.agents import people_extractor

        expected = PeopleExtractionOutput(people=[])
        monkeypatch.setattr(people_extractor, "get_client", lambda: _mock_client(expected))

        result = await people_extractor.extract_people(
            sample_turn, {"Sarah Chen": "Data Engineer"}
        )
        assert isinstance(result, PeopleExtractionOutput)


# ── Systems extractor ─────────────────────────────────────────────────────────

class TestSystemsExtractorContract:
    async def test_returns_systems_extraction_output(self, monkeypatch, sample_turn):
        from app.agents import systems_extractor

        expected = SystemsExtractionOutput(systems=[
            BriefSystem(
                canonical_name="Snowflake",
                ownership_status="owned",
                fragility="medium",
                documentation_status="partially-documented",
            )
        ])
        monkeypatch.setattr(systems_extractor, "get_client", lambda: _mock_client(expected))

        result = await systems_extractor.extract_systems(sample_turn, [])

        assert isinstance(result, SystemsExtractionOutput)
        assert result.systems[0].canonical_name == "Snowflake"
        assert result.systems[0].ownership_status == "owned"

    async def test_multiple_systems_returned(self, monkeypatch, sample_turn):
        from app.agents import systems_extractor

        expected = SystemsExtractionOutput(systems=[
            BriefSystem(
                canonical_name="Snowflake",
                ownership_status="owned",
                fragility="medium",
                documentation_status="partially-documented",
            ),
            BriefSystem(
                canonical_name="Apache Airflow",
                ownership_status="owned",
                fragility="high",
                documentation_status="undocumented",
            ),
        ])
        monkeypatch.setattr(systems_extractor, "get_client", lambda: _mock_client(expected))

        result = await systems_extractor.extract_systems(sample_turn, [])
        assert len(result.systems) == 2

    async def test_returns_empty_when_nothing_extracted(self, monkeypatch, sample_turn):
        from app.agents import systems_extractor

        expected = SystemsExtractionOutput(systems=[])
        monkeypatch.setattr(systems_extractor, "get_client", lambda: _mock_client(expected))

        result = await systems_extractor.extract_systems(sample_turn, [])
        assert result.systems == []

    async def test_accepts_state_slice_only(self):
        """§26-4: function must accept only (turn, known_systems)."""
        from app.agents import systems_extractor

        params = list(inspect.signature(systems_extractor.extract_systems).parameters)
        assert params == ["turn", "known_systems"]


# ── Implicit knowledge extractor ──────────────────────────────────────────────

class TestImplicitKnowledgeExtractorContract:
    async def test_returns_implicit_knowledge_extraction_output(self, monkeypatch, sample_turn):
        from app.agents import implicit_knowledge_extractor

        expected = ImplicitKnowledgeExtractionOutput(items=[
            ImplicitKnowledgeItem(
                title="Weekend ETL failure workaround",
                description="Manually re-trigger job 47 in the staging environment.",
                knowledge_type="workaround",
                urgency="first-week",
            )
        ])
        monkeypatch.setattr(
            implicit_knowledge_extractor, "get_client", lambda: _mock_client(expected)
        )

        result = await implicit_knowledge_extractor.extract_implicit_knowledge(sample_turn, [])

        assert isinstance(result, ImplicitKnowledgeExtractionOutput)
        assert result.items[0].knowledge_type == "workaround"
        assert result.items[0].urgency == "first-week"

    async def test_returns_empty_when_nothing_extracted(self, monkeypatch, sample_turn):
        from app.agents import implicit_knowledge_extractor

        expected = ImplicitKnowledgeExtractionOutput(items=[])
        monkeypatch.setattr(
            implicit_knowledge_extractor, "get_client", lambda: _mock_client(expected)
        )

        result = await implicit_knowledge_extractor.extract_implicit_knowledge(sample_turn, [])
        assert result.items == []

    async def test_accepts_state_slice_only(self):
        """§26-4: function must accept only (turn, known_titles)."""
        from app.agents import implicit_knowledge_extractor

        params = list(
            inspect.signature(implicit_knowledge_extractor.extract_implicit_knowledge).parameters
        )
        assert params == ["turn", "known_titles"]


# ── Risk extractor ────────────────────────────────────────────────────────────

class TestRiskExtractorContract:
    async def test_returns_risk_extraction_output(self, monkeypatch, sample_turn):
        from app.agents import risk_extractor

        expected = RiskExtractionOutput(risks=[
            BriefRisk(
                title="Weekend ETL single point of failure",
                description="Only one person knows how to recover the ETL when it fails on weekends.",
                risk_type="single_point_of_failure",
                severity="high",
                likelihood="possible",
                mitigation="Document the manual recovery steps for job 47.",
            )
        ])
        monkeypatch.setattr(risk_extractor, "get_client", lambda: _mock_client(expected))

        result = await risk_extractor.extract_risks(sample_turn, [])

        assert isinstance(result, RiskExtractionOutput)
        assert result.risks[0].risk_type == "single_point_of_failure"
        assert result.risks[0].severity == "high"

    async def test_returns_empty_when_nothing_extracted(self, monkeypatch, sample_turn):
        from app.agents import risk_extractor

        expected = RiskExtractionOutput(risks=[])
        monkeypatch.setattr(risk_extractor, "get_client", lambda: _mock_client(expected))

        result = await risk_extractor.extract_risks(sample_turn, [])
        assert result.risks == []

    async def test_accepts_state_slice_only(self):
        """§26-4: function must accept only (turn, known_titles)."""
        from app.agents import risk_extractor

        params = list(inspect.signature(risk_extractor.extract_risks).parameters)
        assert params == ["turn", "known_titles"]

    async def test_known_titles_dedup_slice(self, monkeypatch, sample_turn):
        """Existing risk titles are passed so the agent can avoid duplicating them."""
        from app.agents import risk_extractor

        expected = RiskExtractionOutput(risks=[])
        monkeypatch.setattr(risk_extractor, "get_client", lambda: _mock_client(expected))

        result = await risk_extractor.extract_risks(
            sample_turn, ["Weekend ETL single point of failure"]
        )
        assert isinstance(result, RiskExtractionOutput)
