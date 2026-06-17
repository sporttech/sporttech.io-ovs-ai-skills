# Create TRA Sessions From a Schedule

## Goal
Create OVS sessions from an organiser-provided schedule, then map scheduled competition rows to OVS stages and add session references after user approval.

## When To Use
Use on TRA servers when an agent has a schedule file such as a PDF, spreadsheet, CSV, or copied table and must build the event sessions around the existing competition/stage structure.

This skill is designed for schedules where each table row is an organiser session number and each venue/apparatus column contains one stream of work. In TRA, create one OVS session per non-empty competition column. All OVS sessions created from the same schedule row must use the same encoded `Session.Number`; store the short schedule time/date in `Session.Time` and the venue/apparatus column label in the session title field when the target runtime exposes one.

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
- For PDFs, prefer coordinate/table extraction over plain text order. Session labels may be vertically centred in merged left-side cells, so text extraction can place scheduled rows before or after the visible session label.
- When a PDF page starts with scheduled rows before the first visible session label, treat them as candidates for that page's first session, not automatically as a continuation from the previous page.
- Mark rows near session boundaries or page breaks as needing user validation when the extracted order conflicts with the visible layout.
- Treat `NO COMPETITION`, training access, breaks, and movement notes as non-refs unless the user explicitly asks to create refs for them.
- Do not create OVS sessions for cells that contain only `NO COMPETITION`, training access, movement notes, or other non-competition text.
- For every non-empty competition cell in a row, create a separate OVS session. Reuse the row's schedule number for each of these OVS sessions.
- Keep `Session.Time` short: use the clock time/range if present, otherwise use the date only, for example `Tue 7 Jul`.
- Put the venue/apparatus column label in the session title field, for example `TRAMPOLINE 2`, not in `Session.Time`. In current TRA metadata this field is `SessionTitle`; verify through `/api/ai.fieldDocs.Session.SessionTitle`.
- Do not duplicate the word `Session` or the local schedule session number in the title or `Time`; the encoded `Session.Number` already carries the approved numbering.
- If the runtime does not expose a writable session title field through `/api/ai`, do not guess the field name. Stop and ask the user whether to proceed with short `Time` only, wait for updated metadata, or use a user-specified title field.
- Before proposing `Session.Number`, check whether schedule session numbers restart on each day. If they do, do not use the raw schedule number directly because OVS would show repeated stream numbers across the event.
- When schedule numbering restarts by day, ask the user how to encode OVS session numbers before creating sessions. Recommended options:
  - **Sequential event numbering**: continue across days, for example day 1 sessions `1,2,3`, day 2 sessions `4,5,6`, and so on.
  - **Day-coded numbering**: encode day and local session number, for example `101,102,103`, `201,202,203`.
  - **User-provided numbering**: use an explicit mapping supplied by the user.
- Apply the chosen encoded number to every OVS session stream created from the same schedule row. Keep the source schedule label in the plan shown to the user, but do not put it into `Session.Time` unless the user explicitly asks for that.
- Interpret `Flight 1`, `Flight 2`, and `Flight 3` as routine/frame indexes `0`, `1`, and `2` for the matching group unless the OVS stage/group structure proves otherwise.
- Interpret `FINAL` as the final-stage group for the matching competition, usually frame index `0`.
- If a schedule gives no clock time, store only the date/day in `Session.Time`, for example `Tue 7 Jul`.
- If a schedule gives actual start times, store only the time or time range in `Session.Time`.

## Required User Approvals
This workflow has two approval gates.

### 1. Approve session creation plan
Before creating sessions, show the user:

- parsed sessions in order;
- proposed `Number`, `Time`, and title for each OVS session, showing duplicate `Number` values when multiple venue/apparatus streams come from the same schedule row;
- the chosen session-number encoding when source schedule numbers restart by day;
- schedule rows/items that will later need refs;
- ignored rows such as training, breaks, movement notes, and `NO COMPETITION`.

Do not create sessions until the user approves this plan. If repeated day-local numbering is detected and the user has not chosen an encoding scheme, ask for that choice before showing the final creation plan.

### 2. Approve schedule-to-OVS mapping
After sessions exist, build and show a mapping table:

| Schedule text | OVS competition | OVS stage | OVS group | Frame index | Confidence | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Nat 6 TRP Female Flight 1 | Nat 6 TRP Female | Qualification | Group 1 | 0 | high | matched by title and flight |

Ask the user to approve or correct the mapping. Do not add refs until the user approves it.

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

### 2. Create each approved session

```http
POST /api/sessions/
Authorization: token <uuid>
Content-Type: application/json
```

```json
{}
```

Extract `sessionID` from the `Location` header.

### 3. Patch session fields

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

### 4. Refetch sessions

```http
GET /api/event?fetch_event_sessions=true&fetch_session_groups=true&fetch_session_frames=true
```

Verify that the created sessions appear in the expected order and with the expected fields.

### 5. Add approved refs

For every approved mapped item:

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

`GroupID` is the target OVS group ID. `GroupFrame` is zero-based and identifies the routine/frame within each performance in the group.

### 6. Reorder refs if needed

If refs were added in a different order than the schedule:

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

`n` is the zero-based target position inside the session refs list.

### 7. Generate session start lists

After refs are correct, create or refresh the session frames:

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

Use `mode=create` to replace generated session frames from current refs. Use `mode=append` only when the user explicitly wants to keep existing frames and append new ones.

### 8. Verify the result

```http
GET /api/sessions/{sessionID}?fetch_session_groups=true&fetch_session_frames=true&fetch_group_performances=true&fetch_performance_athletes=true
```

Check:

- `Session.Groups` and `Session.GroupFrame` match the approved refs and order.
- `Session.Frames` were generated when requested.
- The referenced groups have performances for the requested frame index.

## Updating Refs From A New Schedule
When the user provides an updated schedule:

1. Parse the new schedule into the same neutral model.
2. Read current sessions with `fetch_event_sessions`, `fetch_session_groups`, and `fetch_session_frames`.
3. Show a diff: sessions to create, sessions to patch, refs to add, refs to remove, refs to reorder, and frames that would be regenerated.
4. Ask for user approval before mutating.
5. Use `removeRef` only for refs that are explicitly removed from the schedule:

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

6. Add/reorder refs as needed, then run `generate` with `mode=create` only after the user approves regeneration.

## Matching Heuristics
Use conservative matching and expose uncertainty:

- Match discipline codes and keywords first: `TRP`, `SYN`, `DMT`, `TUM`.
- Match level/age/sex tokens next, for example `Nat 6`, `Youth U15`, `Junior U17`, `Senior`, `Male`, `Female`, `Mixed`, `Combined`.
- Match stage words last: `Flight 1`, `Flight 2`, `FINAL`.
- Prefer exact or near-exact competition title matches over inferred matches.
- If several OVS stages or groups can match a schedule item, mark confidence as low and require the user to choose.
- Never silently create refs for ambiguous rows.

## Failure Modes
- The schedule text extraction may merge table columns. If column positions matter, ask the user for the original spreadsheet or use visual/table extraction before planning.
- `addRef` fails if `GroupID` does not exist or `GroupFrame` is outside the valid frame range.
- `generate` fails when `mode` is not `create` or `append`.
- Re-running imports without a diff can duplicate refs or replace generated frames unexpectedly.
- Existing sessions may already contain manually curated refs; preserve them unless the approved update plan says otherwise.

## Mutation Risk
High. This creates and patches sessions, changes session refs, and can regenerate session start lists.
