# Assign TRA Session References From A Schedule

## Goal

Complete phase 2 of the schedule workflow: map approved schedule items to live
OVS competitions, stages, groups, and exercise indexes; publish the complete
mapping for approval; then apply exactly the approved references and stage
creations.

Use either the applied phase-1 session TSV or existing live sessions from a
fresh workflow snapshot. Do not generate start lists in this recipe.

## Mandatory Opening Message

Tell the user this is phase 2 of 3 in a complete schedule workflow, or a
standalone references workflow when the sessions already exist:

1. session grid — already applied or adopted from live OVS;
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
2. Select one session source:
   - normal workflow: read the applied phase-1 TSV and its schedule provenance;
   - standalone phase 2: use existing `SessionID`, `Number`, `SessionTitle`, and
     current refs from a fresh workflow snapshot. State that phase 1 is out of
     scope and do not invent missing schedule provenance.
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
- Treat schedule labels such as `Flight`, `Group`, `Round`, `Exercise`,
  `Routine`, and their localized abbreviations as user-defined terminology.
  Analyze the schedule and live graph first, but if a label can mean either a
  group number or an exercise number, stop before publishing the approval CTA
  and ask the user what that label means. Do not silently choose one
  interpretation. Preserve the answer in `Source` or `Details`.
- Add every selected group as its own `ref` row.
- Copy the live stage `PerfomanceFramesLimit` into
  `ExpectedExerciseCount` on every `ref` row. For a stage being created, use
  its planned `StageField:PerfomanceFramesLimit`.
- Once any exercise from a group is included in a session, represent every
  exercise from `1` through `ExpectedExerciseCount`. Use a `ref` row when the
  exercise is included. An absent exercise is a blocking validation error
  unless the user directly confirms the omission.
- Record a confirmed missing exercise as its own `RowType=omitted` row with
  the same session, competition, stage, group, target identity, and
  `ExpectedExerciseCount`; set `ExerciseNumber` to the omitted exercise and
  record `Details.omittedIntentionally=true` plus a non-empty
  `Details.reason` containing the user's instruction. General approval of the
  TSV is not confirmation of an omission.
- Treat table row order as the final reference order. Phase 3 materializes this
  order into start-list frames and never repairs it.
- Within one stage, always use group-major, then routine-major order:
  `G1/R1`, `G1/R2`, `G2/R1`, `G2/R2`. Never use the round-major order
  `G1/R1`, `G2/R1`, `G1/R2`, `G2/R2`.
- References from different stages may alternate by routine when the schedule
  explicitly requires that order. If the inter-stage order is ambiguous, stop
  before the approval CTA, ask the user to choose the intended sequence, then
  publish the resolved draft.
- Interpret human stage labels such as `Final`, `Финал`, `Final 1`, `Final 2`,
  abbreviations, and localized variants from the schedule context, adjacent
  items, and current live graph. Make a best-effort proposal instead of asking
  the user to perform the initial analysis.
- If the likely stage does not exist or the mapping is not certain, publish a
  review-only `ambiguous` row. Preserve the original text in `Source.raw` and
  record a concrete `Details.proposedAction` (`stageCreate` or `skipped`),
  `Details.proposedStageKind` when proposing creation,
  `Details.proposalBasis`, and the relevant alternatives.
- Resolve every such row with the user before approval. The only final outcomes
  for a missing stage are explicit `stageCreate` + `ref` rows, or an explicit
  `skipped` row with `Details.reason`. Never infer, create, or omit a stage
  silently. Do not invent `RowType=addStage`; the canonical row type is
  `stageCreate`.
- Never infer that `FINAL` is another routine in `Qualification` from
  `PerfomanceFramesLimit`, `GroupFrame`, or the live graph. A `FINAL` schedule
  item mapped to `StageKind=Qualification` is invalid by default. If the stage
  structure is unclear, publish an `ambiguous` row and ask the user.
- Allow `FINAL` in `Qualification` only after a direct user instruction for the
  named competition. Record
  `Details.finalInQualificationExplicitlyRequested=true` and that instruction
  in `Details.finalMappingBasis`. General approval of the TSV is not that
  instruction.
- Use `ambiguous` and `unmatched` only in review drafts. They are discussion
  markers, not executable outcomes. Convert every one to `stageCreate` + `ref`
  rows, an explicit exercise-level `omitted` row, or `skipped` before approval.
- Keep approved `skipped` rows visible in subsequent TSV versions so phase 3
  can explain intentionally omitted sessions.
- Keep `PlanStatus=draft` until the user approves this exact file version.
- Run `validate_session_references_plan.py --plan <draft.tsv>` immediately after
  first generation and after every transformation, including sorting, row
  insertion, and manual correction. Do not publish a draft with validator
  errors. Review every warning and mention unresolved warnings in the approval
  summary.

## Approval Gate 2: Session References

After preparing or correcting the table:

1. send a clickable link to the canonical TSV;
2. summarize reference rows, stage creations, exercise omissions, ambiguous
   rows, unmatched rows, and proposed or approved skips;
3. call out every missing-stage proposal explicitly and obtain a concrete
   create-or-skip decision for each one before accepting `approve references`;
4. list every confirmed `FINAL`-in-`Qualification` exception and its user
   basis; if none exist, say so;
5. list every `RowType=omitted` exercise and the direct user instruction that
   authorized it; if none exist, say so;
6. stop without dry-run, credential discovery, or OVS mutation;
7. end the message with this explicit CTA:

`Next: review <linked filename> and reply "approve references", or list corrections and missing-stage decisions.`

`approve references` does not resolve an `ambiguous` or `unmatched` row. If any
remain, request the missing create-or-skip decisions, publish a new draft, and
repeat the gate. Approval applies only to the exact fully resolved file version.

## Apply Approved References

After the user approves:

1. set `PlanStatus=approved`;
2. request an OC password/token if one was not explicitly supplied;
3. run `apply_session_references_plan.py --dry-run`;
4. if dry-run fails, correct and republish the draft for approval;
5. apply with `--updated-plan` whenever stages will be created;
6. verify live reference order and created stage/group IDs;
7. publish the applied canonical TSV with approved `skipped` rows preserved;
8. preserve the token file for phase 3; do not clean it up at the phase
   boundary.

If order is found to be wrong after apply, correct the affected session rows
and rerun phase 2 in `recreate` mode before phase 3. `apply` cannot reorder
references that already exist.

If an invalid `FINAL`-to-`Qualification` mapping is found after apply:

1. stop phase 3 immediately;
2. identify every affected `SessionID`;
3. rebuild those sessions in a corrected phase-2 `recreate` draft;
4. obtain explicit approval for every final-stage decision;
5. apply and verify the corrected phase 2;
6. discard any previous phase-3 draft and prepare a new one from the corrected
   applied references TSV.

Finish phase 2 with:

`Phase 2 complete. Next: prepare a separate start-list generation TSV; sessions.generate will not run before approval gate 3.`

In standalone phase 2, the same approval gate, validator, dry-run, apply, and
verification rules remain mandatory. Existing sessions are input, not evidence
that their current refs or stage semantics are correct.

## Included Tools

- `inspect_session_workflow.py`: fetch one read-only OVS snapshot.
- `validate_session_references_plan.py`: validate each review TSV offline before
  publication and after every edit or sort.
- `apply_session_references_plan.py`: dry-run and apply stage/reference rows.
  Use `--print-example` to print a canonical validator-compatible
  `stageCreate + ref + skipped` TSV.
- `plan_table.py`: read and write canonical TSV tables.
