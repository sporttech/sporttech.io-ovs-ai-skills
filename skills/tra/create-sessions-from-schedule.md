# Create TRA Sessions From a Schedule

## Goal
Create OVS sessions from an organiser-provided schedule, then map scheduled competition rows to OVS stages and add session references after user approval.

## Operator Contract
Treat this as a guided multi-step workflow. Keep the user oriented throughout the run.

### Start With The Full Roadmap
Before parsing or mutating anything, tell the user that the workflow contains these steps:

1. inspect `/api/ai`, the schedule, and the current OVS event structure;
2. build and visually verify the session grid;
3. ask the user to approve the session table, then create sessions;
4. map schedule items to OVS competitions, stages, groups, and exercise indexes;
5. ask the user to approve the mapping table and choose how to handle missing finals or ambiguous items;
6. create any explicitly approved missing final stages and add/reorder session references;
7. ask whether to generate or regenerate start lists;
8. generate start lists and report unresolved or intentionally empty sessions.

State that JSON files are technical execution artifacts. Human approvals will use
TSV or XLSX review tables. Also state that every mutation is separated by an
approval gate and may be repeated from the saved technical plan.

### End Every Step With A CTA
Every progress report that completes a workflow step must end with one explicit
call to action. Do not leave the user to infer the next action.

When a review artifact is created, always send a clickable link to that artifact
in the chat. Creating the file on disk or mentioning only its path is not
sufficient. Stop after sending the link and wait for explicit user approval;
do not rely on approval of a similar plan from an earlier run.

Use a concrete CTA matching the next gate, for example:

- `Next: review the session table and reply "approve sessions" or list corrections.`
- `Next: choose sequential or day-coded numbering.`
- `Next: review the mapping table and approve it, or correct the highlighted rows.`
- `Next: choose "create finals" or "leave finals empty".`
- `Next: reply "add refs" to apply the approved exercise links.`
- `Next: reply "generate start lists" to build Session.Frames.`
- `Workflow complete. Next: review the generation report; unresolved rows remain highlighted in the TSV.`

If a step is blocked, the CTA must name the exact information or decision needed
from the user.

## When To Use
Use on TRA servers when an agent has a schedule file such as a PDF, spreadsheet, CSV, or copied table and must build the event sessions around the existing competition/stage structure.

This skill is designed for schedules where each table row is an organiser session number and each venue/apparatus column contains one stream of work. In TRA, create one OVS session per non-empty competition column. All OVS sessions created from the same schedule row must use the same encoded `Session.Number`; store the short schedule time/date in `Session.Time` and the organiser's venue/apparatus column label in the session title field when the target runtime exposes one.

## Read First
Read `/api/ai` from the target server before using this skill. Use:

- `runtime.app` to confirm the server is TRA.
- `entityTypes` to confirm `sessions`, `groups`, `stages`, and `competitions` endpoints are available.
- `actions` to confirm `sessions.addRef`, `sessions.removeRef`, `sessions.reorderRef`, and `sessions.generate` are available.
- `fetchFlags` for `fetch_event_competitions`, `fetch_competition_stages`, `fetch_stage_groups`, `fetch_event_sessions`, `fetch_session_groups`, `fetch_session_frames`, and `fetch_group_performances`.
- `fieldDocs` and resource schemas, when available, to confirm the writable session title field name before patching titles.
- `principles.created-location-id` for IDs returned by `POST /api/sessions/`.
- `auth` and `methods` for token handling.

Do not rely on private source-code paths or repository links. Resolve all runtime-specific API availability from `/api/ai`.

## Included Artifacts
- `skills/tra/scripts/build_sessions_plan_from_docx.py` is an optional draft extractor for simple DOCX table layouts. It uses the Python standard library only and does not contact or mutate OVS. It is a helper, not an authoritative parser: an agent must inspect the actual document, correct the extracted plan, and obtain user approval.
- `skills/tra/scripts/apply_sessions_plan.py` applies an approved session plan to an OVS server. It creates and patches sessions only; session references to exercises and start-list generation remain separate approval gates.
- `skills/tra/scripts/apply_session_references_plan.py` applies an approved session references plan. It supports separate modes for adding proposed session references and creating missing final stages.
- `skills/tra/scripts/generate_session_start_lists.py` calls `sessions.generate` for every session in an applied session plan and writes a verification report with reference and generated-frame counts.
- `skills/tra/scripts/apply_session_rotation_view.py` applies one documented `Session.RotationView` mode to every session in an applied session plan and verifies the result.
- `skills/tra/scripts/export_plan_review.py` converts session plans, references plans, and start-list reports from technical JSON into UTF-8 TSV tables for human review.

## Terminology
- **Session reference** or **exercise link** means one scheduled exercise/run link inside an OVS session. In the API this is represented by a pair of fields: `GroupID` selects an OVS group/start-list group, and `GroupFrame` selects the zero-based routine/exercise index inside each performance in that group.
- The API action names use the shorter internal term `addRef`, `removeRef`, and `reorderRef`. When communicating with users, expand this as "add/remove/reorder session references to exercises" so the plan is understandable outside the OVS implementation.
- `Session.Groups` and `Session.GroupFrame` are parallel arrays. `Session.Groups[i]` plus `Session.GroupFrame[i]` is one session reference/exercise link.
- `sessions.generate` uses the approved session references to create concrete `Session.Frames`, which are the executable start-list/scoring frames for the live session workflow.
- `Session.RotationView` controls how generated frames are visually divided into rotation sections. It changes grouping and headers, not reference order or generated frames.

Current standard client modes are:

| Value | Meaning |
| --- | --- |
| 0 | Do not divide |
| 1 | Participant rotations |
| 2 | Stage and exercise number |
| 3 | Stage and exercise number, including all stages |
| 4 | Competition, stage, and exercise number |
| 5 | Competition, stage, and exercise number, including all stages |
| 6 | Competition |
| 7 | Competition, including all stages |

Verify these modes against the current client or `/api/ai` when the runtime
version changes. Do not infer the numeric value only from the option order.

## Inputs
- `token`
- schedule file or pasted schedule table
- target event server URL
- user-approved session creation plan
- user-approved mapping from schedule names to OVS `competitionID`, `stageID`, and `groupID`

## Schedule Interpretation
Parse the schedule into this neutral model before mutating OVS:

```json
{
  "sessionLabel": "Session 2, Tue 7th July",
  "sessionNumber": 2,
  "date": "2026-07-07",
  "columns": [
    {
      "label": "TRAMPOLINE 1",
      "items": [
        {
          "raw": "Nat 6 TRP Female Flight 1",
          "competitionName": "Nat 6 TRP Female",
          "stageName": "Flight 1",
          "frameIndex": 0
        }
      ]
    }
  ]
}
```

Guidelines:

- Preserve source wording in `raw`; normalise only in additional fields.
- Prefer structured sources in this order when multiple schedule files are available: spreadsheet/CSV, DOCX tables, then PDF visual/table extraction, then plain text.
- For DOCX schedules, read real table rows and cells. Treat the first column as the session label/date when it contains `Session N, Day Date`, and the remaining columns as venue/apparatus labels.
- Do not assume organiser DOCX files follow one stable template. Human-authored files may use merged cells, manual line breaks, nested tables, repeated headers, page splits, text boxes, colour-only semantics, or changed column order. Interpret the document as an agent using both structure and rendered pages.
- A deterministic DOCX extraction script may be used only to produce a draft. Visually inspect every rendered page, compare all schedule rows and apparatus columns with the draft, and correct omissions, merged items, false splits, and ignored notes before presenting the plan.
- The schedule document and the user-approved plan are the sources of truth. Script output alone is never sufficient evidence that the schedule was parsed correctly.
- For PDFs, prefer coordinate/table extraction over plain text order. Session labels may be vertically centred in merged left-side cells, so text extraction can place scheduled rows before or after the visible session label.
- When a PDF page starts with scheduled rows before the first visible session label, treat them as candidates for that page's first session, not automatically as a continuation from the previous page.
- Mark rows near session boundaries or page breaks as needing user validation when the extracted order conflicts with the visible layout.
- Treat `NO COMPETITION`, training access, breaks, and movement notes as non-competition cells unless the user explicitly asks to create session references for them.
- Do not create OVS sessions for cells that contain only `NO COMPETITION`, training access, movement notes, or other non-competition text.
- For every non-empty competition cell in a row, create a separate OVS session. Reuse the row's schedule number for each of these OVS sessions.
- Keep `Session.Time` short: use the clock time/range if present, otherwise use the date only, for example `Tue 7 Jul`.
- Initially put the organiser's venue/apparatus column label in the session title field, not in `Session.Time`. Preserve the exact source column label separately in the technical plan.
- Do not hard-code a vocabulary of apparatus names or abbreviations in deterministic extractors. Different organisers and schedule files may use different terminology.
- If the user asks to abbreviate, rename, or normalise titles, treat that as a correction to the current review plan. Apply the requested mapping to `SessionTitle` in that plan only, regenerate the human review table, link it in chat, and wait for approval again.
- In current TRA metadata the title field is `SessionTitle`; verify through `/api/ai.fieldDocs.Session.SessionTitle`.
- Do not duplicate the word `Session` or the local schedule session number in the title or `Time`; the encoded `Session.Number` already carries the approved numbering.
- If the runtime does not expose a writable session title field through `/api/ai`, do not guess the field name. Stop and ask the user whether to proceed with short `Time` only, wait for updated metadata, or use a user-specified title field.
- Before proposing `Session.Number`, check whether schedule session numbers restart on each day. If they do, do not use the raw schedule number directly because OVS would show repeated stream numbers across the event.
- When schedule numbering restarts by day, ask the user how to encode OVS session numbers before creating sessions. Recommended options:
  - **Sequential event numbering**: continue across days, for example day 1 sessions `1,2,3`, day 2 sessions `4,5,6`, and so on.
  - **Day-coded numbering**: encode day and local session number, for example `101,102,103`, `201,202,203`.
  - **User-provided numbering**: use an explicit mapping supplied by the user.
- Apply the chosen encoded number to every OVS session stream created from the same schedule row. Keep the source schedule label in the plan shown to the user, but do not put it into `Session.Time` unless the user explicitly asks for that.
- For session references, add all OVS groups from the matched stage by default. A schedule item normally describes work for a competition/stage, not only one OVS group.
- If the schedule explicitly says `Group 1`, `Group 2`, `G1`, or similar, limit session references to the corresponding OVS stage group indexes. Show that narrowing in the references plan.
- Interpret `Flight 1`, `Flight 2`, and `Flight 3` as routine/frame indexes `0`, `1`, and `2` applied to the selected group set when the frame index is within the stage `PerfomanceFramesLimit`.
- If a `Flight N` value exceeds `PerfomanceFramesLimit` but the stage has at least `N` groups, treat it as a possible source flight/group number, map it to OVS group index `N`, and mark the ref as `needs-review`.
- For TRA trampoline sessions with several groups and several exercise frames, order session references by group first, then exercise frame: `Group 1 Exercise 1`, `Group 1 Exercise 2`, then `Group 2 Exercise 1`, `Group 2 Exercise 2`. Do not default to exercise-first ordering such as `Group 1 Exercise 1`, `Group 2 Exercise 1`, then `Group 1 Exercise 2`, `Group 2 Exercise 2`. If the organiser schedule explicitly requires exercise-first ordering, show that as an exception in the references plan and ask for approval.
- Interpret `FINAL` as work for a final stage or final exercise frame.
- If a competition has only `Flight 1` in the schedule and the matched stage supports at least two exercise frames, it is usually obvious that `FINAL` should map to `GroupFrame=1` for every selected OVS group. Mark this as `proposed` with `mappingMode=obvious-final-as-next-exercise-frame`.
- If `Flight 2` already uses `GroupFrame=1`, or the stage does not support another exercise frame, do not silently point `FINAL` at qualification groups. Add it to the references plan as `blocked-missing-final` and ask whether to leave final exercise links empty for now or create the needed final stages/groups before adding session references.
- If a schedule gives no clock time, store only the date/day in `Session.Time`, for example `Tue 7 Jul`.
- If a schedule gives actual start times, store only the time or time range in `Session.Time`.

## Plan And Review Artifacts
Before mutating OVS, write both:

- a technical JSON plan used by the application scripts;
- a human-readable TSV or XLSX review table used for approval.

Never ask a user to approve raw JSON as the primary review surface. Link the
review table first and the JSON second. The user must be able to inspect or edit
the table, request corrections, and reapply the saved technical plan without
reparsing the schedule.

Use this shape:

```json
{
  "kind": "ovs-tra-session-plan",
  "version": 1,
  "source": {
    "scheduleFile": "TRP Order of Work 2026 CONDENSED- V1 01Jun26.docx",
    "numbering": "day-coded"
  },
  "sessions": [
    {
      "sourceLabel": "Session 2, Tue 7th July",
      "sourceSessionNumber": 2,
      "Number": 102,
      "Time": "Tue 7 Jul",
      "SessionTitle": "TRAMPOLINE 1",
      "items": [
        {
          "raw": "Nat 6 TRP Female Flight 1",
          "competitionName": "Nat 6 TRP Female",
          "stageName": "Flight 1",
          "frameIndex": 0
        }
      ],
      "unmatched": []
    }
  ],
  "skipped": [
    {
      "sourceLabel": "Session 1, Tue 7th July",
      "column": "TRAMPOLINE 1",
      "raw": "NO COMPETITION",
      "reason": "no-competition"
    }
  ]
}
```

The `sessions` array is the contract consumed by `skills/tra/scripts/apply_sessions_plan.py`. Each session object must contain `Number`, `Time`, and `SessionTitle`. Keep mapping-only details such as `items`, `unmatched`, `sourceLabel`, and `sourceSessionNumber` in the plan for review and later session reference creation.

Export a human review table after creating or changing any plan:

```bash
python3 skills/tra/scripts/export_plan_review.py \
  --plan /path/to/tra-session-plan.json \
  --output /path/to/tra-session-plan.review.tsv
```

The TSV is UTF-8 with a BOM so it opens cleanly in common spreadsheet tools.
Use XLSX instead when the available spreadsheet tooling makes filtering,
multiple decision sheets, or visual highlighting materially easier. At minimum,
the review table must expose all fields needed for the current approval gate.

Recommended workflow:

1. Parse schedule and OVS structure. For a simple DOCX table schedule, the included builder may be used to accelerate the initial extraction:

```bash
python3 skills/tra/scripts/build_sessions_plan_from_docx.py \
  --source /path/to/schedule.docx \
  --output /path/to/tra-session-plan.json \
  --year 2026 \
  --numbering day-coded \
  --server http://192.168.31.22:48145
```

The builder attempts to treat each non-empty competition cell as one OVS
session, records the original cell text for later reference mapping, and
records empty or non-competition cells in `skipped`. Its output has
`review.status=draft-extraction` and must not be applied until an agent has
rendered and inspected the source document, corrected the JSON as needed, and
changed the review status after user approval.

2. Render and visually inspect the source document. Reconcile the draft with every visible schedule row and column.
3. Write the corrected plan JSON to a durable path in the current workspace or another user-visible location.
4. Export the corrected plan to TSV or XLSX.
5. Show a concise summary and send clickable chat links: the human review table first, then the technical JSON.
6. End with: `Next: review the session table and reply "approve sessions" or list corrections.`
7. Stop and wait for explicit approval of this exact plan. Approval from a previous run does not carry over. If the user edits the table, reconcile the edits into JSON and export and link the table again. The approved JSON remains the execution source of truth.
8. Run the included script with the approved plan and token.
9. Save the script output plan with created `sessionID` values and export an updated review table.
10. End with: `Next: review the created sessions, then reply "build refs plan".`

Example dry run:

```bash
python3 skills/tra/scripts/apply_sessions_plan.py \
  --base-url http://192.168.31.22:48145 \
  --plan /path/to/approved-tra-session-plan.json \
  --token-file /path/to/token.txt \
  --dry-run
```

Example apply:

```bash
python3 skills/tra/scripts/apply_sessions_plan.py \
  --base-url http://192.168.31.22:48145 \
  --plan /path/to/approved-tra-session-plan.json \
  --token-file /path/to/token.txt \
  --output /path/to/applied-tra-session-plan.json
```

The script refuses to create sessions when the event already contains sessions unless `--allow-nonempty` is passed. Use `--allow-nonempty` only after the user confirms that adding sessions to the current event state is intentional.

## Required User Approvals
This workflow has two approval gates.

### 1. Approve session creation plan
Before creating sessions, show the user:

- parsed sessions in order;
- proposed `Number`, `Time`, and title for each OVS session, showing duplicate `Number` values when multiple venue/apparatus streams come from the same schedule row;
- the chosen session-number encoding when source schedule numbers restart by day;
- schedule rows/items that will later need session references to exercises;
- ignored rows such as training, breaks, movement notes, and `NO COMPETITION`.

Write the same information to a TSV or XLSX review table. The session review
table must contain at least:

| Source session | Date | OVS Number | Time | Session title | Schedule items | Ignored items | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |

Also write the technical JSON and include its path after the review-table path.
Both paths must be clickable links in the chat. Do not create sessions until
the user explicitly approves this exact table. If repeated day-local
numbering is detected and the user has not chosen an encoding scheme, end with
the CTA asking the user to choose a numbering scheme before producing the final
approval table.

### 2. Approve schedule-to-OVS mapping
After sessions exist, build and export a mapping TSV or XLSX:

| Status | Session | Schedule text | OVS competition | Stage | Group | Exercise index | Confidence | Mapping/reason | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| proposed | 103 / TRAMPOLINE 2 | Nat 6 TRP Female Flight 1 | National 6 TRP Female | Qualification | all groups | 0 | high | title and flight match | approve/correct |

Include `proposed`, `needs-review`, `blocked-missing-final`, and `unmatched`
rows in the same review surface. Ask the user to approve or correct the mapping.
Do not add session references to exercises until the user approves it. End with:
`Next: review the mapping table and approve it, or correct the highlighted rows.`

When final stages are missing, the references plan must show a separate decision block:

```json
{
  "userDecisionRequired": {
    "missingFinalStagesToCreate": [
      {
        "competitionID": 74,
        "competitionTitle": "National 6 SYN Combined",
        "existingStages": [74],
        "scheduleFinalItems": ["SYN Nat 6 Combined FINAL"],
        "createMode": {
          "script": "skills/tra/scripts/apply_session_references_plan.py",
          "mode": "create-missing-finals",
          "stageKindName": "Final1",
          "PerfomanceFramesLimit": 1
        }
      }
    ]
  }
}
```

Ask the user whether to leave these finals empty for now or run `create-missing-finals`. Creating missing final stages must be an explicit plan application mode, not an implicit side effect of adding session references.

After applying `create-missing-finals`, export the updated refs plan again and
show the new stage/group IDs in the review table before adding refs. End with:
`Next: review the updated mapping table, then reply "add refs".`

## Requests

### 1. Read the competition structure

```http
GET /api/event?fetch_event_competitions=true&fetch_competition_stages=true&fetch_stage_groups=true&fetch_event_sessions=true&fetch_session_groups=true&fetch_session_frames=true
```

Use the response to build maps:

- `Event.Competitions -> Competitions`
- `Competitions[id].Stages -> Stages`
- `Stages[id].Groups -> Groups`
- `Event.Sessions -> Sessions`

For large events, use the partitioned graph-read principle from `/api/ai` and fetch selected stages separately.

### 2. Apply the approved session plan

Use the included script instead of issuing ad hoc session creation requests:

```bash
python3 skills/tra/scripts/apply_sessions_plan.py \
  --base-url <server-url> \
  --plan <approved-plan.json> \
  --token-file <token-file> \
  --output <applied-plan.json>
```

The output plan records `sessionID` on each created session. Use that file for later schedule-to-OVS mapping and session reference creation.

The script performs these API steps for each approved session:

#### Create each approved session

```http
POST /api/sessions/
Authorization: token <uuid>
Content-Type: application/json
```

```json
{}
```

Extract `sessionID` from the `Location` header.

#### Patch session fields

```http
PATCH /api/sessions/{sessionID}
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "Number": 2,
  "Time": "Tue 7 Jul",
  "SessionTitle": "TRAMPOLINE 2"
}
```

`Number` must be a positive integer. Multiple TRA sessions may intentionally share the same `Number` when they are parallel streams from the same schedule row, but different schedule rows should not collide unless the user explicitly asks for that. `Time` is a short string for the time/range/date only. Use the actual writable session title field exposed by `/api/ai`; for current TRA servers this is `SessionTitle`, not `Title`.

### 3. Refetch sessions

```http
GET /api/event?fetch_event_sessions=true&fetch_session_groups=true&fetch_session_frames=true
```

Verify that the created sessions appear in the expected order and with the expected fields.
Export the applied session plan to TSV/XLSX and end with the CTA for building
the refs plan.

### 4. Add approved session references to exercises

Use the included references-plan script. To create missing final stages first:

```bash
python3 skills/tra/scripts/apply_session_references_plan.py \
  --base-url <server-url> \
  --plan <approved-refs-plan.json> \
  --token-file <token-file> \
  --mode create-missing-finals \
  --output <refs-plan-with-created-finals.json>
```

`create-missing-finals` creates one final stage per competition listed in `userDecisionRequired.missingFinalStagesToCreate`, using `StageKinds.Final1` by default and `PerfomanceFramesLimit=1`. It then writes an updated references plan with the created `stageID` and first created final `GroupID`. Review that updated plan before adding session references.

Export every initial or updated refs plan:

```bash
python3 skills/tra/scripts/export_plan_review.py \
  --plan <approved-or-updated-refs-plan.json> \
  --output <refs-plan.review.tsv>
```

To add approved session references without touching already existing references:

```bash
python3 skills/tra/scripts/apply_session_references_plan.py \
  --base-url <server-url> \
  --plan <approved-refs-plan.json> \
  --token-file <token-file> \
  --mode add-proposed \
  --output <applied-refs-plan.json>
```

To recreate session references from the approved plan and normalize TRA trampoline ordering:

```bash
python3 skills/tra/scripts/apply_session_references_plan.py \
  --base-url <server-url> \
  --plan <approved-refs-plan.json> \
  --token-file <token-file> \
  --mode recreate-proposed \
  --output <recreated-refs-plan.json>
```

`recreate-proposed` removes current session references, then adds `status=proposed` references from the plan in group-first order inside each session competition/stage block. Use this when the existing session was built exercise-first and must be normalized before `sessions.generate`.

After refs are verified, export the applied refs plan and end with:
`Next: reply "generate start lists" to build Session.Frames.`

For every approved mapped item, the script performs:

```http
POST /api/sessions/{sessionID}/addRef
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "GroupID": 119,
  "GroupFrame": 0
}
```

`GroupID` is the target OVS group ID. `GroupFrame` is zero-based and identifies the routine/exercise frame within each performance in the group. Together they form one session reference, meaning "include this group exercise in this OVS session."

### 5. Reorder session references if needed

If session references were added in a different order than the schedule:

```http
POST /api/sessions/{sessionID}/reorderRef
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "GroupID": 119,
  "GroupFrame": 0,
  "n": 0
}
```

`n` is the zero-based target position inside the session references list.

For TRA trampoline, check the order before generating start lists. The default expected order is group-first:

```text
G1 Exercise 1
G1 Exercise 2
G2 Exercise 1
G2 Exercise 2
```

Use `reorderRef` to reach this order when the references were added exercise-first. This matters because `sessions.generate` uses the current `Session.Groups` and `Session.GroupFrame` order to build `Session.Frames`.

### 6. Generate session start lists

After session references are correct, create or refresh the session frames:

```http
POST /api/sessions/{sessionID}/generate
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "mode": "create"
}
```

Use `mode=create` to replace generated session frames from current session references. Use `mode=append` only when the user explicitly wants to keep existing frames and append new ones.

Use the included script to make this step repeatable and to save a report:

```bash
python3 skills/tra/scripts/generate_session_start_lists.py \
  --base-url <server-url> \
  --session-plan <applied-session-plan.json> \
  --token-file <token-file> \
  --mode create \
  --output <start-lists-report.json>
```

The script calls `sessions.generate` for every session in the applied session
plan, including sessions without references. The report marks these as
`no-refs`; they are not generation failures. References to groups that do not
yet contain performances are reported as `refs-without-performances`; this is
expected for final stages before finalists are advanced. A session with
referenced performances but zero generated frames is reported as
`performances-without-frames` and causes the script to fail.

Export the generation report for human review:

```bash
python3 skills/tra/scripts/export_plan_review.py \
  --plan <start-lists-report.json> \
  --output <start-lists-report.review.tsv>
```

End with:
`Workflow complete. Next: review the generation report; unresolved or intentionally empty sessions are identified in the Status column.`

### 7. Verify the result

```http
GET /api/sessions/{sessionID}?fetch_session_groups=true&fetch_session_frames=true&fetch_group_performances=true&fetch_performance_athletes=true
```

Check:

- `Session.Groups` and `Session.GroupFrame` match the approved session references and order.
- `Session.Frames` were generated when requested.
- The referenced groups have performances for the requested frame index.

## Updating Session References From A New Schedule
When the user provides an updated schedule:

1. Parse the new schedule into the same neutral model.
2. Read current sessions with `fetch_event_sessions`, `fetch_session_groups`, and `fetch_session_frames`.
3. Show a diff: sessions to create, sessions to patch, session references to add, session references to remove, session references to reorder, and frames that would be regenerated.
4. Ask for user approval before mutating.
5. Use `removeRef` only for session references that are explicitly removed from the schedule:

```http
POST /api/sessions/{sessionID}/removeRef
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "GroupID": 119,
  "GroupFrame": 0
}
```

6. Add/reorder session references as needed, then run `generate` with `mode=create` only after the user approves regeneration.

## Matching Heuristics
Use conservative matching and expose uncertainty:

- Match discipline codes and keywords first: `TRP`, `SYN`, `DMT`, `TUM`.
- Match level/age/sex tokens next, for example `Nat 6`, `Youth U15`, `Junior U17`, `Senior`, `Male`, `Female`, `Mixed`, `Combined`.
- Match stage words last: `Flight 1`, `Flight 2`, `FINAL`.
- Prefer exact or near-exact competition title matches over inferred matches.
- If several OVS stages or groups can match a schedule item, mark confidence as low and require the user to choose.
- Never silently create session references for ambiguous rows.

## Failure Modes
- The schedule text extraction may merge table columns. If column positions matter, ask the user for the original spreadsheet or use visual/table extraction before planning.
- `addRef` fails if `GroupID` does not exist or `GroupFrame` is outside the valid frame range.
- `generate` fails when `mode` is not `create` or `append`.
- Re-running imports without a diff can duplicate session references or replace generated frames unexpectedly.
- Existing sessions may already contain manually curated session references; preserve them unless the approved update plan says otherwise.

## Mutation Risk
High. This creates and patches sessions, changes session references to exercises, and can regenerate session start lists.
