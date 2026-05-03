"""
DomainConfig schema — the blueprint that drives the interview engine for a given domain.

A DomainConfig specifies what to capture (coverage_categories), how to ask about it
(question_banks), where extracted items land in the RoleBrief (extraction_targets),
what ambiguities to flag (clarification_triggers), and how to render vault output
(vault_templates). Loading a different config switches the engine to a new domain
without changing any Python code.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


ClarificationPriority = Literal["high", "medium", "low"]

VALID_SECTION_KEYS = frozenset({
    "responsibilities", "people", "systems", "implicit_knowledge", "risks"
})


# ── Coverage category ─────────────────────────────────────────────────────────

class CoverageCategory(BaseModel):
    name: str
    display_name: str
    description: str
    mandatory: bool = False
    min_score: float = Field(default=0.5, ge=0.0, le=1.0)
    weight: float = Field(default=1.0, gt=0.0)


# ── Section target ────────────────────────────────────────────────────────────

class SectionTarget(BaseModel):
    """Tells an extraction agent which RoleBrief section to fill and how."""
    section_key: str
    item_description: str
    dedup_key: str
    wikilink_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_section_key(self) -> "SectionTarget":
        if self.section_key not in VALID_SECTION_KEYS:
            raise ValueError(
                f"section_key '{self.section_key}' is not valid. "
                f"Must be one of: {sorted(VALID_SECTION_KEYS)}"
            )
        return self


# ── Clarification trigger ─────────────────────────────────────────────────────

class ClarificationTrigger(BaseModel):
    condition: str
    suggested_question_template: str
    priority: ClarificationPriority = "medium"


# ── Domain config ─────────────────────────────────────────────────────────────

class DomainConfig(BaseModel):
    domain_name: str
    display_name: str
    description: str

    coverage_categories: list[CoverageCategory]

    # Keys = coverage_category.name; values = list of question-text variants.
    question_banks: dict[str, list[str]] = Field(default_factory=dict)

    # Keys = coverage_category.name; values = SectionTarget.
    extraction_targets: dict[str, SectionTarget] = Field(default_factory=dict)

    clarification_triggers: list[ClarificationTrigger] = Field(default_factory=list)

    # Keys = template names; values = Mustache-style template strings.
    vault_templates: dict[str, str] = Field(default_factory=dict)

    # ── Convenience helpers ───────────────────────────────────────────────────

    def category_names(self) -> list[str]:
        return [c.name for c in self.coverage_categories]

    def mandatory_categories(self) -> list[CoverageCategory]:
        return [c for c in self.coverage_categories if c.mandatory]

    def coverage_weights(self) -> dict[str, float]:
        return {c.name: c.weight for c in self.coverage_categories}
