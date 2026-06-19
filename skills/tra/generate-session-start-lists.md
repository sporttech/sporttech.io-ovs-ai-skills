# Generate TRA Session Start Lists

## Goal

Complete phase 3 of the schedule workflow: prepare the exact set of sessions
whose start lists will be generated, publish it for approval, then call
`sessions.generate` and verify the resulting frames.

Use either a canonical applied phase-2 references TSV or a separately approved
`Mode=adopt` TSV representing manually assembled live refs. Pass that TSV to
the executor with `--references-plan`.

## Mandatory Opening Message

Tell the user this is phase 3 of 3, or a standalone start-list workflow over
approved adopted refs, and is an independent approval gate.
State that start-list generation may replace existing frames in `Mode=create`
and will not run before approval of the clickable TSV.

## Read First

1. Read
   [references/session-plan-contracts.md](references/session-plan-contracts.md).
   Follow its canonical-artifact rules before implementing any phase logic: use
   the phase-3 executor and matching helpers from one skill-pack revision,
   confirm their CLI with `--help`, and do not use a local substitute while
   that canonical path is available.
2. Select and validate one references source:
   - normal workflow: canonical phase-2 TSV with `PlanStatus=applied`;
   - standalone phase 3: export current live refs with
     `build_adopted_session_references_plan.py`, publish the resulting
     `Mode=adopt`, `PlanStatus=draft` TSV for reference review, and change it to
     `approved` only after the user explicitly adopts that exact version.
   Re-run `validate_session_references_plan.py` and stop if it contains errors.
3. Run `inspect_session_workflow.py` for a fresh OVS snapshot.
4. Inspect current references, frames, and referenced group performances for
   every proposed session.
5. Reuse the token file created during phase 1. Request credentials only if
   that token is absent or invalid.

## Prepare The Start-List Table

- Use one explicit `RowType=session` row per target `SessionID`.
- Use `Mode=create` for normal regeneration and `Mode=append` only when the user
  explicitly wants to preserve existing frames.
- Include every intentionally empty session in the review summary even if it is
  omitted from generation.
- Explain sessions with no refs or referenced groups without performances.
- Keep `PlanStatus=draft` until the user approves this exact file version.
- For standalone phase 3, approval of the adopted refs TSV is separate from
  approval of the start-list TSV. Never collapse these two approvals.

For standalone phase 3, publish the adopted refs TSV before preparing the
start-list TSV, summarize its target sessions and ordered refs, then stop with:

`Next: review <linked adopted refs filename> and reply "approve adopted references", or list the reference corrections required.`

Only that exact adopted file version may be changed to `PlanStatus=approved`.
After approval, prepare the separate start-list draft and use approval gate 3.

## Approval Gate 3: Start-List Generation

After preparing or correcting the table:

1. send a clickable link to the canonical TSV;
2. summarize target sessions, generation mode, sessions without refs, and
   sessions expected to remain empty;
3. stop without dry-run, credential discovery, or calling `sessions.generate`;
4. end the message with this explicit CTA:

`Next: review <linked filename> and reply "approve start lists", or list the sessions or generation mode to change.`

Approval applies only to that exact file version. Any change creates a new draft
and repeats this gate.

## Generate Approved Start Lists

After the user approves:

1. set `PlanStatus=approved`;
2. request an OC password/token if one was not explicitly supplied;
3. run `generate_session_start_lists.py --references-plan
   <refs.applied-or-adopted.tsv> --dry-run`;
4. if dry-run fails, correct and republish the draft for approval;
5. run the executor without `--dry-run`;
6. verify `Session.Frames` and publish the audit report;
7. report `generated`, `no-refs`, `refs-without-performances`, and failures;
8. delete the temporary token file only after the complete workflow has
   finished.

Finish with:

`Workflow complete. Next: review the generation report and the listed empty or failed sessions.`

## Included Tools

- `inspect_session_workflow.py`: fetch one read-only OVS snapshot.
- `build_adopted_session_references_plan.py`: export manually assembled live
  refs into a reviewable `Mode=adopt` TSV.
- `validate_session_references_plan.py`: revalidate the applied phase-2 source
  before dry-run or generation.
- `generate_session_start_lists.py`: dry-run, generate, and verify frames.
- `plan_table.py`: read the canonical start-list TSV.
