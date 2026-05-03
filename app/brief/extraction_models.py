"""
Instructor-enforced output wrappers for the five brief-engine extraction agents.

Each model wraps the relevant list from app.brief.schema so that instructor
can enforce the Pydantic shape against the LLM response. Defined here (not
in schema.py) to keep I/O contracts separate from the core data models.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.brief.schema import (
    BriefPerson,
    BriefRisk,
    BriefSystem,
    ImplicitKnowledgeItem,
    Responsibility,
)


class ResponsibilityExtractionOutput(BaseModel):
    responsibilities: list[Responsibility]


class PeopleExtractionOutput(BaseModel):
    people: list[BriefPerson]


class SystemsExtractionOutput(BaseModel):
    systems: list[BriefSystem]


class ImplicitKnowledgeExtractionOutput(BaseModel):
    items: list[ImplicitKnowledgeItem]


class RiskExtractionOutput(BaseModel):
    risks: list[BriefRisk]
