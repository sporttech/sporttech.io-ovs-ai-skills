# Assign TRA Session References From A Schedule

## Goal

Complete phase 2 of the schedule workflow: map approved schedule items to live
OVS competitions, stages, groups, and exercise indexes; publish the complete
mapping for approval; then apply exactly the approved references and stage
creations.

Require the applied phase-1 session TSV containing actual `SessionID` values.
Do not generate start lists in this recipe.

## Mandatory Opening Message

Tell the user this is phase 2 of 3:

1. session grid — already applied;
2. session references — current phase and approval gate;
3. start-list generation — separate future approval gate.

State that no references or stages will be mutated before approval of the
clickable reference TSV.

## Read First

1. Read
   [references/session-plan-contracts.md](references/session-plan-contracts.md).
   Follow its canonical-artifact rules before implementing any phase logic: use
   the phase-2 executor and matching helpers from one skill-pack revision,
   confirm their CLI with `--help`, and do not use a local substitute while
   that canonical path is available.
2. Read the applied session TSV and its schedule provenance.
3. Run `inspect_session_workflow.py` for a fresh OVS snapshot.
4. Read live competitions, stages, groups, performance-frame limits, and
   existing session references from the snapshot.
5. Reuse the token file created during phase 1. Request credentials only if
   that token is absent or invalid.

Use only current-workflow sources allowed by the contract. Never search prior
session JSONL traces, old snapshots, audit JSON, or another workflow for a
mapping example. A prior mapping is not evidence that `FINAL` belongs to the
qualification stage or to a separate final stage.

## Prepare The Reference Table

- Map each schedule item explicitly to `SessionID`, competition, stage, group,
  and zero-based `GroupFrame`.
- Add every selected group as its own `ref` row.
- Treat table row order as the final reference order. Phase 3 materializes this
  order into start-list frames and never repairs it.
- Within one stage, always use group-major, then routine-major order:
  `G1/R1`, `G1/R2`, `G2/R1`, `G2/R2`. Never use the round-major order
  `G1/R1`, `G2/R1`, `G1/R2`, `G2/R2`.
- References from different stages may alternate by routine when the schedule
  explicitly requires that order. If the inter-stage order is ambiguous, stop
  before the approval CTA, ask the user to choose the intended sequence, then
  publish the resolved draft.
- Represent missing stages only with explicit `stageCreate` rows. Never infer or
  create a final stage silently.
- Use `ambiguous`, `unmatched`, and `skipped` rows for unresolved items. Keep
  them visible in every subsequent TSV version.
- Keep `PlanStatus=draft` until the user approves this exact file version.
- Run `validate_session_references_plan.py --plan <draft.tsv>` immediately after
  first generation and after every transformation, including sorting, row
  insertion, and manual correction. Do not publish a draft with validator
  errors. Review every warning and mention unresolved warnings in the approval
  summary.

## Approval Gate 2: Session References

After preparing or correcting the table:

1. send a clickable link to the canonical TSV;
2. summarize reference rows, stage creations, ambiguous rows, unmatched rows,
   and skipped rows;
3. call out every missing-stage decision explicitly;
4. stop without dry-run, credential discovery, or OVS mutation;
5. end the message with this explicit CTA:

`Next: review <linked filename> and reply "approve references", or list corrections and missing-stage decisions.`

Approval applies only to that exact file version. Any correction or resolved
ambiguity creates a new draft and repeats this gate.

## Apply Approved References

After the user approves:

1. set `PlanStatus=approved`;
2. request an OC password/token if one was not explicitly supplied;
3. run `apply_session_references_plan.py --dry-run`;
4. if dry-run fails, correct and republish the draft for approval;
5. apply with `--updated-plan` whenever stages will be created;
6. verify live reference order and created stage/group IDs;
7. publish the applied canonical TSV with unresolved rows preserved;
8. preserve the token file for phase 3; do not clean it up at the phase
   boundary.

If order is found to be wrong after apply, correct the affected session rows
and rerun phase 2 in `recreate` mode before phase 3. `apply` cannot reorder
references that already exist.

Finish phase 2 with:

`Phase 2 complete. Next: prepare a separate start-list generation TSV; sessions.generate will not run before approval gate 3.`

## Included Tools

- `inspect_session_workflow.py`: fetch one read-only OVS snapshot.
- `validate_session_references_plan.py`: validate each review TSV offline before
  publication and after every edit or sort.
- `apply_session_references_plan.py`: dry-run and apply stage/reference rows.
- `plan_table.py`: read and write canonical TSV tables.
