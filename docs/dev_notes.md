# Development Notes

Observations, failure modes, and design decisions encountered during development.
These are raw notes for inclusion in the write-up — not polished prose.

---

## 2026-04-27 — Duplicate nodes in Obsidian graph view

**Observed:** When opening the project in Obsidian graph view, a large number of
duplicate nodes are visible.

**Root cause — two separate problems:**

### Problem 1: Multiple vault directories indexed by Obsidian

If the Obsidian vault root is set anywhere above `runs/`, Obsidian indexes all
run subdirectories simultaneously. Entities that appear in multiple runs (e.g.,
`Jordan_Lee.md`, `Richard_Jones.md`, `Project_Falcon.md`) show up once per run
rather than once total.

- **Example:** `runs/helpful/exit_interview_vault/People/Jordan_Lee.md` and
  `runs/vague/exit_interview_vault/People/Jordan_Lee.md` are two separate files
  for the same real person because helpful and vague are both Project Falcon runs.

**Fix:** Run `merge_graphs.py` on runs that share a project, then open only the
merged vault in Obsidian:
```bash
python merge_graphs.py \
  runs/helpful/final_state.json \
  runs/vague/final_state.json \
  --name "Project Falcon" \
  --out runs/merged/falcon/
```

### Problem 2: Real duplicate nodes within a single run's graph

Even within `runs/helpful/exit_interview_vault/` alone, the same real-world
entity was extracted under different labels across turns, generating different
stable IDs and therefore different node files.

Confirmed examples from the helpful_alex run:

| Real entity | Duplicate node files created |
|---|---|
| Marcus Wright (NorthStar VP of Data) | `People/Marcus_Wright.md`, `People/VP_of_Data.md` |
| Richard Jones (client-side product owner) | `People/Richard_Jones.md`, `People/client_side_product_owner.md`, `People/product_owner.md` |
| Sarah Chen (data engineer) | `People/Sarah_Chen.md`, `People/data_engineer.md` |
| Richard Smith (program manager) | `People/Richard_Smith.md`, `People/program_manager.md` |
| dbt repo / pipeline | `Projects/dbt_models.md`, `Projects/dbt_project.md`, `Projects/falcon_dbt.md`, `Systems/dbt_models.md`, `Systems/falcon_dbt.md` |
| Change request workflow | `Workflows/Change_Request_Workflow.md`, `Workflows/change_approval_process.md`, `Workflows/change_request_approval_path.md`, `Workflows/client_side_approval_path.md`, `Workflows/client_side_change_request_approval_path.md` |
| Pipeline knowledge risk | `Risks/knowledge_transfer_risk.md`, `Risks/sole_knowledge_transfer_risk.md`, `Risks/sole_maintainer_knowledge_transfer_risk.md`, `Risks/Undocumented_Pipeline_Logic.md` |

**Root cause:** The entity extractor LLM called the same real-world entity by a
different label in different turns. The graph mapper generates stable IDs as
`{type_slug}_{label_slug}`, so "Marcus Wright" → `person_marcus_wright` and
"VP of Data" → `person_vp_of_data` become separate nodes. The alias matching
in the extraction prompt was not aggressive enough to catch role-based references
to already-known people.

**No fix applied yet.** The correct fix is tightening the entity extractor prompt
to check `existing_aliases` more aggressively before minting a new node — treating
role descriptions ("the VP of Data", "the program manager") as potential aliases
for existing Person nodes rather than new entities. Deferred.

**Paper relevance:** Both problems are worth including in the write-up:
- Problem 1 is a deployment/UX finding: the vault compiler produces per-interview
  artifacts that need explicit merging before they are useful as a unified knowledge
  base. The merge tooling exists but is a manual step.
- Problem 2 is a system quality finding: the multi-agent extraction pipeline
  produces duplicate nodes when the same entity is referred to by role rather than
  name. This is a known limitation of label-based stable ID generation and points
  to a need for fuzzy entity resolution beyond what the current alias map provides.
