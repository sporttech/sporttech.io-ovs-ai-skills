# OVS Session Plan Table Contracts

## Contents

- [General rules](#general-rules)
- [Session plan](#session-plan)
- [References plan](#references-plan)
- [Start-list plan](#start-list-plan)
- [Executor commands](#executor-commands)

## General Rules

Plans are UTF-8 TSV files with a header row. The table is the sole editable and
executable source of truth.

Use three independent phase recipes and approval gates:

1. [create-sessions-from-schedule.md](../create-sessions-from-schedule.md);
2. [assign-session-references-from-schedule.md](../assign-session-references-from-schedule.md);
3. [generate-session-start-lists.md](../generate-session-start-lists.md).

For every gate, publish a clickable draft TSV, end with the exact CTA required
by that phase recipe, and stop. Do not run the executor, request credentials, or
set `PlanStatus=approved` until the user approves that exact file version.

## Credential Lifecycle

- Request an OC password/token only after approval gate 1, immediately before
  the first dry-run that requires authentication.
- Exchange a password for a token once with `POST /api/access_tokens/`.
- Read the token only from the last path segment of the HTTP `Location` response
  header. The response body is empty and must never be parsed as JSON or treated
  as a token source.
- Store only the extracted token in a protected temporary file.
- Reuse the same token file through phases 1, 2, and 3 of the same workflow.
- Do not delete or rotate the token between phase recipes merely because one
  phase completed.
- Delete the temporary token file only after phase 3 completes, the user
  explicitly ends the workflow, or the token is invalid.
- Never publish the token, include it in artifacts, or recover credentials from
  browser/session storage or unrelated files.

Every row repeats:

| Column | Meaning |
| --- | --- |
| `PlanKind` | Exact contract identifier |
| `Version` | Contract version |
| `Mode` | Operation mode |
| `PlanStatus` | `draft`, `approved`, or `applied` |
| `RowType` | Meaning of this row |

Use JSON only inside `Source`, `Details`, or list-valued cells when nested
metadata is useful. Executors do not interpret `Source` or unresolved rows.

Executor JSON output is an optional audit snapshot. Do not edit or execute it.

## Session Plan

Use `PlanKind=ovs-session-plan`, `Version=2`, and `Mode=create` or `patch`.

| Column | Required | Meaning |
| --- | --- | --- |
| `RowType` | yes | `session` or `skipped` |
| `SessionID` | patch only | Existing session ID; assigned after create |
| `Field:<name>` | yes for session | Field sent to Session PATCH |
| `Source.items` | no | JSON list of schedule item `raw` strings |
| `Source.IgnoredItems` | no | JSON list of ignored source strings |
| `Source` | no | Remaining provenance, including source column and date |
| `Details` | no | Human review notes |

Example:

```tsv
PlanKind	Version	Mode	PlanStatus	RowType	SessionID	Field:Number	Field:Time	Field:SessionTitle	Field:RotationView	Source.items	Source.IgnoredItems	Source
ovs-session-plan	2	create	approved	session		102	Tue 7 Jul	TRA 1	4	["SYN Nat 6 Combined Flight 1","SYN Nat 6 Combined FINAL"]	[]	{"column":"TRAMPOLINE 1","date":"2026-07-07","sourceLabel":"Session 2"}
```

Rules:

- `sessionID` is optional in create mode and required in patch mode.
- A create row with an existing `sessionID` reuses and patches that session.
- All rows are validated against current `/api/ai` before the first mutation.
- Dry-run accepts draft tables; mutation requires `PlanStatus=approved` or
  `PlanStatus=applied`.
- Unknown, read-only, or unavailable fields fail the whole plan.
- A mutating create run requires `--updated-plan`. Treat that generated TSV as
  the next canonical version. Reapplying it does not create another session.
- `RotationView` is an ordinary `Field:RotationView` column.

## References Plan

Use `PlanKind=ovs-session-refs-plan`, `Version=2`, and `Mode=apply` or
`recreate`.

### `stageCreate` rows

| Column | Required | Meaning |
| --- | --- | --- |
| `CompetitionTitle` | yes | Human-facing live competition title |
| `StageID` | after apply | Existing/created stage ID |
| `StageKind` | yes | Exact constant name from `/api/ai` `StageKinds` |
| `StageField:<name>` | yes | Explicit writable Stage field |
| `Target` | yes | Folded JSON with `CompetitionID`, kind, and applied group IDs |
| `Source` | no | Human context |

The executor does not select stage kinds, infer finals, or supply defaults.
For example, write `StageKind=Final1`; the executor resolves its numeric value
from the current `/api/ai`. Every other required Stage field must be present.

### `ref` rows

| Column | Required | Meaning |
| --- | --- | --- |
| `SessionID` | yes | Existing target session |
| `SessionNumber` | yes | Human-facing OVS session number |
| `SessionTitle` | yes | Human-facing OVS session title |
| `CompetitionTitle` | yes | Live OVS competition title |
| `StageKind` | yes | Human-facing stage kind |
| `GroupNumber` | yes | One-based group number inside the stage |
| `ExerciseNumber` | yes | One-based exercise/routine number |
| `Target` | yes | Folded JSON containing technical IDs and zero-based frame |
| `Source` | no | Schedule provenance |
| `Details` | no | Additional review metadata |

For an existing group, use
`Target={"GroupID":123,"GroupFrame":0}`. For a group that will be created by a
`stageCreate` row, use
`Target={"CompetitionID":12,"StageKind":"Final1","GroupIndex":0,"GroupFrame":0}`.
Keep `CompetitionID`, `GroupID`, and zero-based `GroupFrame` out of the visible
review columns. `StageID` remains visible because it is useful after apply.

The reader continues to accept the legacy expanded ID columns, but the writer
publishes the folded `Target` format.

The row order is the final order in `recreate` mode and the add order for new
references in `apply` mode. For normal TRA group-first ordering, place rows as
`G1/E1`, `G1/E2`, `G2/E1`, `G2/E2`. The executor never sorts them.

A mutating run that creates a stage requires `--updated-plan`. Existing
`StageID` rows are checked against the live parent competition and group list.

### Unresolved rows

Use `RowType=ambiguous`, `unmatched`, or `skipped`, with review information in
`Source` and `Details`. These rows remain in canonical TSV versions but are
never applied.

In recreate mode, only sessions named by `ref` rows are cleared. References in
all other sessions remain untouched.

## Start-List Plan

Use `PlanKind=ovs-session-start-lists-plan`, `Version=1`, and `Mode=create` or
`append`.

Each row uses `RowType=session`, an explicit `SessionID`, and the same approval
status rule. The executor reports:

- `generated`;
- `no-refs`;
- `refs-without-performances`;
- `performances-without-frames` as an error.

## Executor Commands

Fetch the reusable read-only OVS snapshot through one stable command:

```bash
python3 skills/tra/scripts/inspect_session_workflow.py \
  --base-url http://ovs.example \
  --output workflow-snapshot.json
```

The inspector performs GET requests only. Its snapshot contains raw `/api/ai`,
the competition/stage/group/session graph, writable fields, StageKinds, session
actions, summary counts, and normalized relation indexes. It never validates a
plan. Run the relevant executor with `--dry-run` for authoritative validation.

Draft DOCX extraction:

```bash
python3 skills/tra/scripts/build_sessions_plan_from_docx.py \
  --source schedule.docx \
  --output sessions.draft.tsv \
  --year 2026 \
  --numbering day-coded
```

Session dry-run and apply:

```bash
python3 skills/tra/scripts/apply_sessions_plan.py \
  --base-url http://ovs.example \
  --plan sessions.approved.tsv \
  --token-file token.txt \
  --dry-run

python3 skills/tra/scripts/apply_sessions_plan.py \
  --base-url http://ovs.example \
  --plan sessions.approved.tsv \
  --token-file token.txt \
  --updated-plan sessions.applied.tsv \
  --audit-output sessions.audit.json
```

References dry-run and apply:

```bash
python3 skills/tra/scripts/apply_session_references_plan.py \
  --base-url http://ovs.example \
  --plan refs.approved.tsv \
  --token-file token.txt \
  --dry-run

python3 skills/tra/scripts/apply_session_references_plan.py \
  --base-url http://ovs.example \
  --plan refs.approved.tsv \
  --token-file token.txt \
  --updated-plan refs.applied.tsv \
  --audit-output refs.audit.json
```

Start-list generation:

```bash
python3 skills/tra/scripts/generate_session_start_lists.py \
  --base-url http://ovs.example \
  --plan start-lists.approved.tsv \
  --token-file token.txt \
  --audit-output start-lists.audit.json
```
