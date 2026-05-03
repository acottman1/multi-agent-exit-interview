"""
Config validator — programmatic gap detection for a freshly generated DomainConfig.

No LLM. Checks structural completeness and minimum quality bars.
Returns a list of ConfigGap objects; empty list means the config is valid.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config.domain_config import DomainConfig

Severity = Literal["error", "warning"]

_MIN_QUESTION_VARIANTS = 2
_MIN_MANDATORY_CATEGORIES = 1
_MIN_MEANINGFUL_THRESHOLD = 0.2


@dataclass
class ConfigGap:
    severity: Severity
    field: str
    message: str

    def __str__(self) -> str:
        icon = "✗" if self.severity == "error" else "⚠"
        return f"{icon} [{self.field}] {self.message}"


def validate_config(config: DomainConfig) -> list[ConfigGap]:
    """
    Return all detected gaps in the config.

    Errors block saving; warnings are advisory. An empty list means the config
    passed all checks and is safe to present to the user for approval.
    """
    gaps: list[ConfigGap] = []
    _check_categories(config, gaps)
    _check_question_banks(config, gaps)
    _check_extraction_targets(config, gaps)
    _check_clarification_triggers(config, gaps)
    _check_vault_templates(config, gaps)
    return gaps


def has_errors(gaps: list[ConfigGap]) -> bool:
    return any(g.severity == "error" for g in gaps)


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_categories(config: DomainConfig, gaps: list[ConfigGap]) -> None:
    if not config.coverage_categories:
        gaps.append(ConfigGap(
            severity="error",
            field="coverage_categories",
            message="No coverage categories defined. The engine has nothing to ask about.",
        ))
        return

    mandatory = config.mandatory_categories()
    if len(mandatory) < _MIN_MANDATORY_CATEGORIES:
        gaps.append(ConfigGap(
            severity="error",
            field="coverage_categories",
            message=(
                f"No mandatory categories defined. "
                "The interview will never know when to stop."
            ),
        ))

    for cat in mandatory:
        if cat.min_score < _MIN_MEANINGFUL_THRESHOLD:
            gaps.append(ConfigGap(
                severity="warning",
                field=f"coverage_categories.{cat.name}.min_score",
                message=(
                    f"Mandatory category {cat.name!r} has min_score={cat.min_score:.2f}, "
                    "which is very low and will be reached after almost any answer."
                ),
            ))


def _check_question_banks(config: DomainConfig, gaps: list[ConfigGap]) -> None:
    for cat in config.coverage_categories:
        variants = config.question_banks.get(cat.name, [])
        if not variants:
            gaps.append(ConfigGap(
                severity="error",
                field=f"question_banks.{cat.name}",
                message=f"No question variants for category {cat.name!r}.",
            ))
        elif len(variants) < _MIN_QUESTION_VARIANTS:
            gaps.append(ConfigGap(
                severity="warning",
                field=f"question_banks.{cat.name}",
                message=(
                    f"Category {cat.name!r} has only {len(variants)} question variant. "
                    f"At least {_MIN_QUESTION_VARIANTS} are recommended for variety."
                ),
            ))


def _check_extraction_targets(config: DomainConfig, gaps: list[ConfigGap]) -> None:
    for cat in config.coverage_categories:
        if cat.name not in config.extraction_targets:
            gaps.append(ConfigGap(
                severity="error",
                field=f"extraction_targets.{cat.name}",
                message=(
                    f"No extraction target for category {cat.name!r}. "
                    "The engine won't know where to put extracted items."
                ),
            ))
            continue

        target = config.extraction_targets[cat.name]
        if not target.dedup_key:
            gaps.append(ConfigGap(
                severity="error",
                field=f"extraction_targets.{cat.name}.dedup_key",
                message=(
                    f"Extraction target for {cat.name!r} has no dedup_key. "
                    "Duplicate items cannot be detected across turns."
                ),
            ))
        if not target.item_description:
            gaps.append(ConfigGap(
                severity="warning",
                field=f"extraction_targets.{cat.name}.item_description",
                message=(
                    f"Extraction target for {cat.name!r} has no item_description. "
                    "The extraction agent will have no guidance on what to produce."
                ),
            ))


def _check_clarification_triggers(config: DomainConfig, gaps: list[ConfigGap]) -> None:
    if not config.clarification_triggers:
        gaps.append(ConfigGap(
            severity="warning",
            field="clarification_triggers",
            message=(
                "No clarification triggers defined. "
                "Ambiguous references (first names, vague system mentions) will not be flagged."
            ),
        ))


def _check_vault_templates(config: DomainConfig, gaps: list[ConfigGap]) -> None:
    if not config.vault_templates:
        gaps.append(ConfigGap(
            severity="warning",
            field="vault_templates",
            message=(
                "No vault templates defined. "
                "Obsidian Markdown output will not be available for this domain."
            ),
        ))
