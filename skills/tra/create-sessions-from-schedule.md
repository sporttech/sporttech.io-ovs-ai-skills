# Create TRA Sessions From A Schedule

## Goal

Complete phase 1 of the schedule workflow: read and visually verify an organiser
schedule, publish a canonical session TSV for approval, then create the approved
OVS sessions and record their actual IDs.

Do not map session references or generate start lists in this recipe.

## Mandatory Opening Message

Before using tools, tell the user the complete three-phase roadmap:

1. prepare, approve, and create the session grid;
2. prepare, approve, and apply session references, including explicitly approved
   missing stages;
3. prepare, approve, and generate session start lists.

State that each phase has its own clickable TSV and independent approval gate.
Never collapse or skip these three approvals.

## Read First

1. Read
   [references/session-plan-contracts.md](references/session-plan-contracts.md).
   Follow its canonical-artifact rules before implementing any phase logic: use
   the phase-1 executor and matching helpers from one skill-pack revision,
   confirm their CLI with `--help`, and do not use a local substitute while
   that canonical path is available.
2. Run `inspect_session_workflow.py` to fetch `/api/ai` and the live event graph
   into one reusable snapshot.
3. Read and render the schedule when document layout matters.

Resolve writable fields and runtime conventions from `/api/ai`. Do not inspect
browser storage, local storage, unrelated files, or another user session for
credentials. If mutation requires authentication and no token/password was
explicitly provided for this task, ask the user for it only after the session
table is approved. Read and follow the credential lifecycle in
[references/session-plan-contracts.md](references/session-plan-contracts.md):
keep the resulting token file for phases 2 and 3.

## Prepare The Session Table

- Treat a DOCX/PDF extractor only as a draft helper.
- Visually compare every row, column, merged cell, page boundary, and manual
  line break with the rendered schedule.
- Preserve original wording in `Source`.
- Do not put organiser terminology or abbreviation dictionaries into scripts.
- Use the default field conventions below unless the user has already specified
  another format.
- Express approved decisions explicitly in `Field:<name>` columns.
- Keep `PlanStatus=draft` until the user approves this exact file version.

For TRA schedules, one non-empty apparatus/venue cell normally becomes one OVS
session. Streams from the same organiser row normally share the approved
`Session.Number`. Ignore service notes and `NO COMPETITION` cells unless the
user explicitly asks to schedule them.

Default field conventions:

- Generate the initial plan with day-coded `Field:Number` values: `101`, `102`,
  `103`, then `201`, `202`, and so on. The leading digits identify the ordinal
  schedule day; the final two digits are the organiser session number within
  that day. Derive the day ordinal from chronological schedule dates, not
  weekday names.
- After publishing the initial plan, the review summary may offer other
  numbering schemes before the approval CTA. If the user chooses one, publish
  a corrected draft and repeat the approval gate.
- `Field:Time` contains only the session's short date, for example `Tue 7 Jul`.
  Do not add a session number, venue, stream, time range, or service
  information.
- `Field:SessionTitle` contains only the apparatus, venue, or stream name from
  the source schedule. Do not duplicate the date, add generic words such as
  `Session` or `Поток`, or append an organiser session number already
  represented by `Field:Number`.

## Approval Gate 1: Session Grid

After preparing or correcting the table:

1. send a clickable link to the canonical TSV;
2. summarize session and skipped-row counts;
3. stop without running the executor, requesting credentials, or mutating OVS;
4. end the message with this explicit CTA:

`Next: review <linked filename> and reply "approve sessions", or list the corrections required.`

Approval applies only to that exact file version. If the user requests changes,
publish a new draft and repeat this gate.

## Apply Approved Sessions

After the user approves:

1. set `PlanStatus=approved` in the approved TSV;
2. request an OC password/token if one was not explicitly supplied;
3. run `apply_sessions_plan.py --dry-run`;
4. if dry-run fails, correct and republish the draft for approval;
5. apply with `--updated-plan`;
6. verify live session values and IDs;
7. publish the applied canonical TSV;
8. preserve the token file for phases 2 and 3; do not clean it up at the phase
   boundary.

Never create sessions without `--updated-plan`.

Finish phase 1 with:

`Phase 1 complete. Next: use the applied session TSV to prepare the session-reference mapping; no references will be applied before approval gate 2.`

## Included Tools

- `inspect_session_workflow.py`: fetch one read-only OVS snapshot.
- `build_sessions_plan_from_docx.py`: produce a draft session TSV.
- `apply_sessions_plan.py`: dry-run and apply the approved session TSV.
- `plan_table.py`: read and write canonical TSV tables.
