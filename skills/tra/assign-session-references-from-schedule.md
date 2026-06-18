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

1. Read the applied session TSV and its schedule provenance.
2. Run `inspect_session_workflow.py` for a fresh OVS snapshot.
3. Read
   [references/session-plan-contracts.md](references/session-plan-contracts.md).
4. Read live competitions, stages, groups, performance-frame limits, and
   existing session references from the snapshot.
5. Reuse the token file created during phase 1. Request credentials only if
   that token is absent or invalid.

## Prepare The Reference Table

- Map each schedule item explicitly to `SessionID`, competition, stage, group,
  and zero-based `GroupFrame`.
- Add every selected group as its own `ref` row.
- Preserve table row order as the requested reference order.
- Use group-first ordering unless the schedule explicitly requires another
  order: `G1/E1`, `G1/E2`, `G2/E1`, `G2/E2`.
- Represent missing stages only with explicit `stageCreate` rows. Never infer or
  create a final stage silently.
- Use `ambiguous`, `unmatched`, and `skipped` rows for unresolved items. Keep
  them visible in every subsequent TSV version.
- Keep `PlanStatus=draft` until the user approves this exact file version.

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

Finish phase 2 with:

`Phase 2 complete. Next: prepare a separate start-list generation TSV; sessions.generate will not run before approval gate 3.`

## Included Tools

- `inspect_session_workflow.py`: fetch one read-only OVS snapshot.
- `apply_session_references_plan.py`: dry-run and apply stage/reference rows.
- `plan_table.py`: read and write canonical TSV tables.
