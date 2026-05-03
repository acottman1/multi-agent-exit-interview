"""
Config reviewer — turns ConfigGaps into human-readable summaries and targeted
clarification questions. Pure Python, no LLM.

Also generates a "preview question" — the first question the engine would ask
using this config — so the user can sanity-check it before approving.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config.domain_config import DomainConfig
from app.meta.config_validator import ConfigGap, has_errors


@dataclass
class ConfigReview:
    is_valid: bool
    gap_summary: str
    clarification_questions: list[str]
    preview_question: str | None = None


def review_config(
    config: DomainConfig,
    gaps: list[ConfigGap],
    preview_question: str | None = None,
) -> ConfigReview:
    """
    Produce a human-readable review from validator gaps.

    preview_question: the first question the engine would ask with this config,
    obtained by calling select_brief_question() on a fresh BriefSessionState.
    Pass None if you have not yet computed it.
    """
    return ConfigReview(
        is_valid=not has_errors(gaps),
        gap_summary=_format_summary(config, gaps),
        clarification_questions=_derive_clarifications(config, gaps),
        preview_question=preview_question,
    )


def format_approval_prompt(review: ConfigReview) -> str:
    """Format the full approval message shown to the user."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("CONFIG REVIEW")
    lines.append("=" * 60)
    lines.append(review.gap_summary)

    if review.preview_question:
        lines.append("")
        lines.append("PREVIEW — first question this config would ask:")
        lines.append(f'  "{review.preview_question}"')

    lines.append("")
    if review.is_valid:
        lines.append("✓ Config passed all checks.")
        if review.clarification_questions:
            lines.append(
                "  Optional improvements available — answer the questions below "
                "to refine, or type 'approve' to save as-is."
            )
        else:
            lines.append("  Type 'approve' to save, or describe changes you'd like.")
    else:
        lines.append(
            "✗ Config has errors that must be resolved before saving. "
            "Please answer the clarification questions below."
        )

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_summary(config: DomainConfig, gaps: list[ConfigGap]) -> str:
    lines: list[str] = []
    lines.append(f"Domain: {config.display_name} ({config.domain_name})")
    lines.append(
        f"Categories: {len(config.coverage_categories)} defined, "
        f"{len(config.mandatory_categories())} mandatory"
    )
    lines.append(
        f"Question variants: "
        + ", ".join(
            f"{cat.name}={len(config.question_banks.get(cat.name, []))}"
            for cat in config.coverage_categories
        )
    )

    if not gaps:
        lines.append("Gaps: none — config is complete.")
    else:
        errors = [g for g in gaps if g.severity == "error"]
        warnings = [g for g in gaps if g.severity == "warning"]
        if errors:
            lines.append(f"Errors ({len(errors)}):")
            for g in errors:
                lines.append(f"  {g}")
        if warnings:
            lines.append(f"Warnings ({len(warnings)}):")
            for g in warnings:
                lines.append(f"  {g}")

    return "\n".join(lines)


def _derive_clarifications(config: DomainConfig, gaps: list[ConfigGap]) -> list[str]:
    """Map each gap to a targeted clarification question for the user."""
    questions: list[str] = []
    seen_fields: set[str] = set()

    for gap in gaps:
        field = gap.field
        if field in seen_fields:
            continue
        seen_fields.add(field)

        if "question_banks" in field:
            cat = field.split(".")[-1]
            questions.append(
                f"Can you give me 3 ways you'd naturally ask about '{cat.replace('_', ' ')}' "
                f"in this kind of conversation?"
            )
        elif "extraction_targets" in field and "dedup_key" in field:
            cat = field.split(".")[1]
            questions.append(
                f"For '{cat.replace('_', ' ')}' items, what single field uniquely identifies "
                f"one item from another? (e.g. a name, a title, a system identifier)"
            )
        elif "extraction_targets" in field:
            cat = field.split(".")[1]
            questions.append(
                f"What does one '{cat.replace('_', ' ')}' item look like in the output? "
                f"Describe the fields that matter most."
            )
        elif "mandatory" in field or field == "coverage_categories":
            questions.append(
                "Which of your categories absolutely have to be covered before the interview "
                "can be considered complete? What's the minimum bar for each?"
            )
        elif "clarification_triggers" in field:
            questions.append(
                "What kinds of vague or ambiguous responses should the interviewer "
                "always follow up on? (e.g. first names only, passive ownership, "
                "unnamed systems)"
            )
        elif "vault_templates" in field:
            questions.append(
                "How should the output document be structured? Describe the sections "
                "and what each one should show."
            )

    return questions
