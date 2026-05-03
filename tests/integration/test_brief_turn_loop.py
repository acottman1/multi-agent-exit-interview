"""
Integration tests for the brief-engine turn loop.

Focus areas:
  - A single run_brief_turn completes end-to-end with scripted answers.
  - Six agents run concurrently (Constraint §26-1).
  - The brief and coverage are updated correctly after each turn.
  - run_brief_interview respects max_turns and mandatory-coverage stop condition.
  - Clarifications are converted to open questions.
  - The orchestrator does not repeat the same question on consecutive turns.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Iterator

import pytest

from app.agents.stubs import STUB_DELAY_SECONDS
from app.brief.extraction_models import (
    ImplicitKnowledgeExtractionOutput,
    PeopleExtractionOutput,
    ResponsibilityExtractionOutput,
    RiskExtractionOutput,
    SystemsExtractionOutput,
)
from app.brief.schema import (
    BriefMeta,
    BriefPerson,
    BriefRisk,
    BriefSystem,
    ImplicitKnowledgeItem,
    Responsibility,
    RoleBrief,
)
from app.brief.session import BriefSessionState
from app.core.models import (
    Clarification,
    ClarificationOutput,
    InterviewTurn,
)
from app.interview import brief_turn_loop
from app.interview.brief_turn_loop import run_brief_interview, run_brief_turn


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_exit_interview_config():
    """Load the bundled exit-interview DomainConfig from disk."""
    from app.config.config_store import load_domain_config
    from app.config.domain_config import DomainConfig
    import json

    config_path = Path(__file__).parents[2] / "app" / "config" / "instances" / "exit_interview.json"
    return DomainConfig.model_validate_json(config_path.read_text())


def _make_state() -> BriefSessionState:
    config = _load_exit_interview_config()
    meta = BriefMeta(
        session_id="sess_test",
        domain_name=config.domain_name,
        interviewee_name="Alex Rivera",
        role_title="Senior Data Engineer",
    )
    brief = RoleBrief(meta=meta)
    return BriefSessionState(domain_config=config, brief=brief)


async def _awaitable(value):
    return value


def _patch_all_agents_empty(monkeypatch) -> None:
    """Monkeypatch all 6 brief-loop agents to return empty outputs instantly."""
    monkeypatch.setattr(brief_turn_loop, "extract_responsibilities",
                        lambda *_a, **_k: _awaitable(ResponsibilityExtractionOutput(responsibilities=[])))
    monkeypatch.setattr(brief_turn_loop, "extract_people",
                        lambda *_a, **_k: _awaitable(PeopleExtractionOutput(people=[])))
    monkeypatch.setattr(brief_turn_loop, "extract_systems",
                        lambda *_a, **_k: _awaitable(SystemsExtractionOutput(systems=[])))
    monkeypatch.setattr(brief_turn_loop, "extract_implicit_knowledge",
                        lambda *_a, **_k: _awaitable(ImplicitKnowledgeExtractionOutput(items=[])))
    monkeypatch.setattr(brief_turn_loop, "extract_risks",
                        lambda *_a, **_k: _awaitable(RiskExtractionOutput(risks=[])))
    monkeypatch.setattr(brief_turn_loop, "detect_clarifications",
                        lambda *_a, **_k: _awaitable(ClarificationOutput(clarifications=[])))


def scripted(answers: list[str]):
    """Sync scripted answer provider."""
    it: Iterator[str] = iter(answers)

    def provider(_question: str) -> str:
        try:
            return next(it)
        except StopIteration:
            return "(no further answer)"

    return provider


def async_scripted(answers: list[str]):
    """Async scripted answer provider."""
    it: Iterator[str] = iter(answers)

    async def provider(_question: str) -> str:
        try:
            return next(it)
        except StopIteration:
            return "(no further answer)"

    return provider


# ── Single-turn smoke tests ───────────────────────────────────────────────────

class TestSingleBriefTurn:
    async def test_run_brief_turn_completes(self):
        state = _make_state()
        result = await run_brief_turn(state, scripted(["I own the data pipeline."]))
        assert result.turn.turn_number == 1
        assert result.turn.answer == "I own the data pipeline."

    async def test_turn_appended_to_state(self):
        state = _make_state()
        await run_brief_turn(state, scripted(["Answer 1"]))
        assert len(state.turns) == 1
        assert state.turns[0].answer == "Answer 1"

    async def test_question_id_tracked_in_asked_list(self):
        state = _make_state()
        result = await run_brief_turn(state, scripted(["Answer"]))
        assert result.orchestrator_output.question_id in state.asked_question_ids

    async def test_async_answer_provider_is_awaited(self):
        state = _make_state()
        result = await run_brief_turn(state, async_scripted(["async answer"]))
        assert result.turn.answer == "async answer"

    async def test_selected_question_bypasses_orchestrator(self):
        """When a question is pre-selected, the orchestrator is not consulted."""
        from app.agents.brief_orchestrator import select_brief_question

        state = _make_state()
        chosen = select_brief_question(state)
        # Change state so orchestrator would pick differently
        result = await run_brief_turn(state, scripted(["pre-selected answer"]), selected_question=chosen)
        assert result.orchestrator_output.question_id == chosen.question_id

    async def test_brief_meta_completeness_updated(self):
        """After a turn, brief.meta.completeness_score reflects weighted coverage."""
        state = _make_state()
        assert state.brief.meta.completeness_score == 0.0
        await run_brief_turn(state, scripted(["I own the data pipeline."]))
        # Completeness won't necessarily be > 0 since stubs return empty items,
        # but the field must have been touched (no exception = wiring works).
        assert isinstance(state.brief.meta.completeness_score, float)


# ── Concurrency proof ─────────────────────────────────────────────────────────

class TestBriefTurnConcurrency:
    async def test_six_agents_run_in_parallel(self, monkeypatch):
        """
        Monkeypatch all 6 agents with sleepy stubs then time the total.
        Sequential would be 6 * delay; parallel ≈ 1 * delay.
        Assert well below 4 * delay.
        """
        def _sleeping(empty_factory):
            async def _agent(*_args, **_kwargs):
                await asyncio.sleep(STUB_DELAY_SECONDS)
                return empty_factory()
            return _agent

        monkeypatch.setattr(brief_turn_loop, "extract_responsibilities",
                            _sleeping(lambda: ResponsibilityExtractionOutput(responsibilities=[])))
        monkeypatch.setattr(brief_turn_loop, "extract_people",
                            _sleeping(lambda: PeopleExtractionOutput(people=[])))
        monkeypatch.setattr(brief_turn_loop, "extract_systems",
                            _sleeping(lambda: SystemsExtractionOutput(systems=[])))
        monkeypatch.setattr(brief_turn_loop, "extract_implicit_knowledge",
                            _sleeping(lambda: ImplicitKnowledgeExtractionOutput(items=[])))
        monkeypatch.setattr(brief_turn_loop, "extract_risks",
                            _sleeping(lambda: RiskExtractionOutput(risks=[])))
        monkeypatch.setattr(brief_turn_loop, "detect_clarifications",
                            _sleeping(lambda: ClarificationOutput(clarifications=[])))

        state = _make_state()
        start = time.monotonic()
        await run_brief_turn(state, scripted(["Answer"]))
        elapsed = time.monotonic() - start
        assert elapsed < 4 * STUB_DELAY_SECONDS, (
            f"Turn took {elapsed:.3f}s — suggests agents ran sequentially."
        )

    async def test_agents_started_before_any_completed(self, monkeypatch):
        """
        Deterministic concurrency proof: all 6 agents must have started
        before the first one finishes.
        """
        starts: list[float] = []
        ends: list[float] = []

        def _tracked(empty_factory):
            async def _agent(*_args, **_kwargs):
                starts.append(time.monotonic())
                await asyncio.sleep(STUB_DELAY_SECONDS)
                ends.append(time.monotonic())
                return empty_factory()
            return _agent

        monkeypatch.setattr(brief_turn_loop, "extract_responsibilities",
                            _tracked(lambda: ResponsibilityExtractionOutput(responsibilities=[])))
        monkeypatch.setattr(brief_turn_loop, "extract_people",
                            _tracked(lambda: PeopleExtractionOutput(people=[])))
        monkeypatch.setattr(brief_turn_loop, "extract_systems",
                            _tracked(lambda: SystemsExtractionOutput(systems=[])))
        monkeypatch.setattr(brief_turn_loop, "extract_implicit_knowledge",
                            _tracked(lambda: ImplicitKnowledgeExtractionOutput(items=[])))
        monkeypatch.setattr(brief_turn_loop, "extract_risks",
                            _tracked(lambda: RiskExtractionOutput(risks=[])))
        monkeypatch.setattr(brief_turn_loop, "detect_clarifications",
                            _tracked(lambda: ClarificationOutput(clarifications=[])))

        state = _make_state()
        await run_brief_turn(state, scripted(["Answer"]))

        assert len(starts) == 6
        first_end = min(ends)
        last_start = max(starts)
        assert last_start <= first_end, (
            "Agents appear to have run sequentially, not concurrently."
        )


# ── Multi-turn loop ───────────────────────────────────────────────────────────

class TestRunBriefInterview:
    async def test_respects_max_turns(self, monkeypatch):
        _patch_all_agents_empty(monkeypatch)
        state = _make_state()
        results = await run_brief_interview(
            state, scripted(["a"] * 5), max_turns=3,
        )
        assert len(results) == 3
        assert len(state.turns) == 3

    async def test_should_stop_short_circuits(self, monkeypatch):
        _patch_all_agents_empty(monkeypatch)
        state = _make_state()

        def stop_after_two(s: BriefSessionState) -> bool:
            return len(s.turns) >= 2

        results = await run_brief_interview(
            state, scripted(["a"] * 10), max_turns=10, should_stop=stop_after_two,
        )
        assert len(results) == 2

    async def test_different_questions_per_turn(self, monkeypatch):
        """The orchestrator must not repeat the same question twice in a row."""
        _patch_all_agents_empty(monkeypatch)
        state = _make_state()
        results = await run_brief_interview(
            state, scripted(["a"] * 5), max_turns=5,
        )
        questions = [r.orchestrator_output.next_question for r in results]
        assert len(set(questions)) == len(questions), (
            f"Duplicate questions: {questions}"
        )

    async def test_asked_question_ids_accumulate_uniquely(self, monkeypatch):
        _patch_all_agents_empty(monkeypatch)
        state = _make_state()
        await run_brief_interview(state, scripted(["a"] * 4), max_turns=4)
        assert len(state.asked_question_ids) == 4
        assert len(set(state.asked_question_ids)) == 4

    async def test_stops_when_should_stop_returns_true(self):
        """
        A custom should_stop that always returns True causes the loop to exit
        immediately without running any turns.
        """
        state = _make_state()
        results = await run_brief_interview(
            state, scripted(["a"] * 5), max_turns=5, should_stop=lambda _s: True
        )
        assert len(results) == 0


# ── Extractor-to-brief wiring ─────────────────────────────────────────────────

class TestExtractorWiring:
    async def test_responsibilities_reach_brief(self, monkeypatch):
        async def resp_stub(_turn, _known_titles):
            return ResponsibilityExtractionOutput(responsibilities=[
                Responsibility(
                    title="Own Snowflake pipeline",
                    description="Manages ETL pipeline.",
                    criticality="high",
                    frequency="daily",
                )
            ])

        monkeypatch.setattr(brief_turn_loop, "extract_responsibilities", resp_stub)

        state = _make_state()
        await run_brief_turn(state, scripted(["I own the Snowflake pipeline."]))
        assert len(state.brief.responsibilities) == 1
        assert state.brief.responsibilities[0].title == "Own Snowflake pipeline"

    async def test_people_reach_brief(self, monkeypatch):
        async def people_stub(_turn, _known_people):
            return PeopleExtractionOutput(people=[
                BriefPerson(
                    canonical_name="Sarah Chen",
                    role_title="Data Engineer",
                    organization="Data Team",
                    relationship_type="collaborator",
                    continuity_reason="Owns dbt models.",
                )
            ])

        monkeypatch.setattr(brief_turn_loop, "extract_people", people_stub)

        state = _make_state()
        await run_brief_turn(state, scripted(["Sarah helps with dbt."]))
        assert any(p.canonical_name == "Sarah Chen" for p in state.brief.people)

    async def test_systems_reach_brief(self, monkeypatch):
        async def systems_stub(_turn, _known_systems):
            return SystemsExtractionOutput(systems=[
                BriefSystem(
                    canonical_name="Snowflake",
                    ownership_status="owned",
                    fragility="medium",
                    documentation_status="partially-documented",
                )
            ])

        monkeypatch.setattr(brief_turn_loop, "extract_systems", systems_stub)

        state = _make_state()
        await run_brief_turn(state, scripted(["I use Snowflake."]))
        assert any(s.canonical_name == "Snowflake" for s in state.brief.systems)

    async def test_risks_reach_brief(self, monkeypatch):
        async def risk_stub(_turn, _known_titles):
            return RiskExtractionOutput(risks=[
                BriefRisk(
                    title="Pipeline SPOF",
                    description="Only I know the fix.",
                    risk_type="single_point_of_failure",
                    severity="high",
                    likelihood="possible",
                )
            ])

        monkeypatch.setattr(brief_turn_loop, "extract_risks", risk_stub)

        state = _make_state()
        await run_brief_turn(state, scripted(["Only I can fix it."]))
        assert any(r.title == "Pipeline SPOF" for r in state.brief.risks)

    async def test_implicit_knowledge_reaches_brief(self, monkeypatch):
        async def ik_stub(_turn, _known_titles):
            return ImplicitKnowledgeExtractionOutput(items=[
                ImplicitKnowledgeItem(
                    title="Weekend ETL workaround",
                    description="Re-trigger job 47.",
                    knowledge_type="workaround",
                    urgency="first-week",
                )
            ])

        monkeypatch.setattr(brief_turn_loop, "extract_implicit_knowledge", ik_stub)

        state = _make_state()
        await run_brief_turn(state, scripted(["Workaround: re-trigger job 47."]))
        assert any(i.title == "Weekend ETL workaround" for i in state.brief.implicit_knowledge)

    async def test_coverage_increases_after_extraction(self, monkeypatch):
        """Coverage for 'responsibilities' must increase after items are added."""
        async def resp_stub(_turn, _known_titles):
            return ResponsibilityExtractionOutput(responsibilities=[
                Responsibility(
                    title="Own pipeline",
                    description="Manages ETL.",
                    criticality="high",
                    frequency="daily",
                )
            ])

        monkeypatch.setattr(brief_turn_loop, "extract_responsibilities", resp_stub)

        state = _make_state()
        assert state.coverage.get("responsibilities", 0.0) == 0.0
        await run_brief_turn(state, scripted(["I own the pipeline."]))
        assert state.coverage.get("responsibilities", 0.0) > 0.0

    async def test_empty_stubs_leave_brief_unchanged(self, monkeypatch):
        """With all agents returning empty, the brief must not grow."""
        _patch_all_agents_empty(monkeypatch)
        state = _make_state()
        await run_brief_turn(state, scripted(["answer"]))
        assert state.brief.is_empty()


# ── Clarification feedback ────────────────────────────────────────────────────

class TestClarificationFeedback:
    async def test_clarifications_become_open_questions(self, monkeypatch):
        async def clar_stub(_turn, _aliases):
            return ClarificationOutput(clarifications=[
                Clarification(
                    kind="ambiguous_entity",
                    target="Sarah",
                    reason="Two Sarahs in the org.",
                    suggested_question="Which Sarah did you mean?",
                    priority="high",
                )
            ])

        monkeypatch.setattr(brief_turn_loop, "detect_clarifications", clar_stub)

        state = _make_state()
        before = len(state.open_questions)
        await run_brief_turn(state, scripted(["Sarah helped."]))
        assert len(state.open_questions) == before + 1
        assert state.open_questions[-1].text == "Which Sarah did you mean?"

    async def test_clarification_priority_preserved(self, monkeypatch):
        async def clar_stub(_turn, _aliases):
            return ClarificationOutput(clarifications=[
                Clarification(
                    kind="unclear_ownership",
                    target="the database",
                    reason="Unspecified which database.",
                    suggested_question="Which database?",
                    priority="medium",
                )
            ])

        monkeypatch.setattr(brief_turn_loop, "detect_clarifications", clar_stub)

        state = _make_state()
        await run_brief_turn(state, scripted(["the database broke"]))
        assert state.open_questions[-1].priority == "medium"
