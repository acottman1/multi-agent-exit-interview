"""
Brief updater — merges extracted section items into a RoleBrief in place.

Analogous to graph/updater.py for the graph engine. Enforces:
  - Items with the same dedup_key are merged rather than duplicated.
  - list fields are unioned (order-preserving, no duplicates).
  - Scalar fields: new value wins unless it is empty/None, in which case
    the existing value is kept.
  - source_turn_ids on every item are always unioned.

merge_into_brief() mutates the brief in place and returns a BriefUpdateResult
describing how many items were added vs. updated per section.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

from app.brief.schema import (
    BriefPerson,
    BriefRisk,
    BriefSystem,
    HiringProfile,
    ImplicitKnowledgeItem,
    Responsibility,
    RoleBrief,
    RoleSummary,
)

_T = TypeVar("_T")


# ── Result object ─────────────────────────────────────────────────────────────

@dataclass
class BriefUpdateResult:
    added: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)

    @property
    def total_changes(self) -> int:
        return sum(self.added.values()) + sum(self.updated.values())

    @property
    def has_changes(self) -> bool:
        return self.total_changes > 0

    def summary(self) -> str:
        parts = []
        for section in set(list(self.added) + list(self.updated)):
            a = self.added.get(section, 0)
            u = self.updated.get(section, 0)
            if a or u:
                parts.append(f"{section}: +{a} added, ~{u} updated")
        return "; ".join(parts) if parts else "no changes"


# ── Public entry point ────────────────────────────────────────────────────────

def merge_into_brief(
    brief: RoleBrief,
    *,
    source_turn_id: str | None = None,
    role_summary: RoleSummary | None = None,
    responsibilities: list[Responsibility] | None = None,
    people: list[BriefPerson] | None = None,
    systems: list[BriefSystem] | None = None,
    implicit_knowledge: list[ImplicitKnowledgeItem] | None = None,
    risks: list[BriefRisk] | None = None,
    hiring_profile: HiringProfile | None = None,
) -> BriefUpdateResult:
    """
    Merge extracted items into the brief in place.

    All keyword arguments are optional — pass only the sections that were
    populated this turn. source_turn_id is automatically appended to every
    item's source_turn_ids provenance list.
    """
    result = BriefUpdateResult()

    if role_summary is not None:
        _merge_singleton(brief, "role_summary", role_summary, source_turn_id)
        result.added["role_summary"] = 0 if brief.role_summary else 1
        result.updated["role_summary"] = 1 if brief.role_summary else 0

    if responsibilities:
        brief.responsibilities, a, u = _merge_section(
            brief.responsibilities, responsibilities, "title", Responsibility, source_turn_id
        )
        result.added["responsibilities"] = a
        result.updated["responsibilities"] = u

    if people:
        brief.people, a, u = _merge_section(
            brief.people, people, "canonical_name", BriefPerson, source_turn_id
        )
        result.added["people"] = a
        result.updated["people"] = u

    if systems:
        brief.systems, a, u = _merge_section(
            brief.systems, systems, "canonical_name", BriefSystem, source_turn_id
        )
        result.added["systems"] = a
        result.updated["systems"] = u

    if implicit_knowledge:
        brief.implicit_knowledge, a, u = _merge_section(
            brief.implicit_knowledge, implicit_knowledge, "title", ImplicitKnowledgeItem, source_turn_id
        )
        result.added["implicit_knowledge"] = a
        result.updated["implicit_knowledge"] = u

    if risks:
        brief.risks, a, u = _merge_section(
            brief.risks, risks, "title", BriefRisk, source_turn_id
        )
        result.added["risks"] = a
        result.updated["risks"] = u

    if hiring_profile is not None:
        _merge_singleton(brief, "hiring_profile", hiring_profile, source_turn_id)

    return result


# ── Generic section merger ────────────────────────────────────────────────────

def _merge_section(
    existing: list[_T],
    incoming: list[_T],
    dedup_key: str,
    model_class: type[_T],
    source_turn_id: str | None,
) -> tuple[list[_T], int, int]:
    """
    Merge incoming items into existing list by dedup_key.

    Returns (merged_list, added_count, updated_count).
    Preserves the original item order; new items are appended.
    """
    index: dict[str, _T] = {getattr(item, dedup_key): item for item in existing}
    added = 0
    updated = 0

    for new_item in incoming:
        key = getattr(new_item, dedup_key)
        new_data = _add_source_turn_id(new_item.model_dump(), source_turn_id)  # type: ignore[attr-defined]

        if key in index:
            merged_data = _merge_dicts(
                index[key].model_dump(),  # type: ignore[attr-defined]
                new_data,
                dedup_key=dedup_key,
            )
            index[key] = model_class.model_validate(merged_data)
            updated += 1
        else:
            index[key] = model_class.model_validate(new_data)
            added += 1

    # Preserve original order, then append new items.
    seen: set[str] = set()
    result: list[_T] = []
    for item in existing:
        k = getattr(item, dedup_key)
        result.append(index[k])
        seen.add(k)
    for item in incoming:
        k = getattr(item, dedup_key)
        if k not in seen:
            result.append(index[k])
            seen.add(k)

    return result, added, updated


def _merge_singleton(
    brief: RoleBrief,
    attr: str,
    new_obj: object,
    source_turn_id: str | None,
) -> None:
    """Merge a singleton section (role_summary, hiring_profile) onto the brief."""
    existing = getattr(brief, attr)
    if existing is None:
        setattr(brief, attr, new_obj)
        return
    merged_data = _merge_dicts(
        existing.model_dump(),  # type: ignore[attr-defined]
        new_obj.model_dump(),   # type: ignore[attr-defined]
        dedup_key="",
    )
    setattr(brief, attr, type(new_obj).model_validate(merged_data))


# ── Dict-level merge helpers ──────────────────────────────────────────────────

def _add_source_turn_id(data: dict, turn_id: str | None) -> dict:
    if not turn_id or "source_turn_ids" not in data:
        return data
    existing_ids: list[str] = data["source_turn_ids"]
    if turn_id in existing_ids:
        return data
    return {**data, "source_turn_ids": existing_ids + [turn_id]}


def _merge_dicts(existing: dict, incoming: dict, dedup_key: str) -> dict:
    """
    Merge incoming field values into a copy of existing.

    Rules:
      - dedup_key field: identity — never overwrite.
      - list fields: ordered union (existing first, then new items not in existing).
      - scalar fields: incoming wins unless it is None, empty string, or empty list.
    """
    merged = dict(existing)
    for key, new_val in incoming.items():
        if key == dedup_key:
            continue
        existing_val = existing.get(key)
        if isinstance(new_val, list) and isinstance(existing_val, list):
            union = list(existing_val)
            for v in new_val:
                if v not in union:
                    union.append(v)
            merged[key] = union
        elif new_val is not None and new_val != "":
            merged[key] = new_val
    return merged
