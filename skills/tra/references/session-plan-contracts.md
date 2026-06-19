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

## Canonical Skill-Pack Artifacts

The scripts in this skill-pack repository are the canonical execution path for
all three phases. Before preparing or executing a phase, the agent MUST:

1. read that phase recipe and this contract;
2. use the canonical phase scripts from the same skill-pack revision as the
   recipe;
3. fetch every imported local helper from that same revision;
4. run each phase executor with `--help` to confirm its command contract;
5. use the canonical executor for dry-run and mutation after the phase approval
   gate.

A local checkout of this repository is canonical when the recipe, executor, and
helpers all come from the same checked-out revision. When loading the skill pack
remotely, resolve one repository commit and fetch all required files from that
commit; do not mix files fetched from moving branches at different times.

Canonical file sets:

- phase 1: `inspect_session_workflow.py`,
  `build_sessions_plan_from_docx.py`, `apply_sessions_plan.py`,
  `plan_table.py`, and `ovs_plan_utils.py`;
- phase 2: `inspect_session_workflow.py`,
  `validate_session_references_plan.py`,
  `apply_session_references_plan.py`, `plan_table.py`, and
  `ovs_plan_utils.py`;
- phase 3: `inspect_session_workflow.py`,
  `build_adopted_session_references_plan.py`,
  `validate_session_references_plan.py`,
  `generate_session_start_lists.py`, `plan_table.py`, and
  `ovs_plan_utils.py`.

Do not create a custom executor, partially reimplement a canonical script, or
substitute older or simplified helpers merely because local code is convenient.
A custom fallback is allowed only when the canonical script is unavailable,
cannot run after reasonable environment setup, or the user explicitly requests
a custom implementation. Before falling back, report the canonical-path
blocker and the behavioral differences or compatibility risks.

Never replace an approval-gated dry-run with an earlier dry-run. Before
approval, use `--help` and other non-executing inspection only.

## Workflow Source Isolation

A new workflow MUST derive decisions only from:

- files explicitly supplied by the user for the current workflow;
- canonical TSV artifacts produced and approved in earlier phases of this same
  workflow;
- a fresh OVS snapshot fetched for the current phase;
- `/api/ai`, the live OVS graph, and the canonical skill-pack revision selected
  for this workflow.

Do not search, read, or infer rules from Codex session logs, archived chats,
terminal history, JSONL traces, previous workflow directories, old snapshots,
old audit JSON, or artifacts from another event unless the user explicitly
supplies that exact artifact as current input. In particular, never inspect
`~/.codex/sessions`, `~/.codex/archived_sessions`, or
`~/.codex/session_index.jsonl` for examples or missing context.

Historical workflow output is not a canonical example and must not be used to
invent mappings such as whether `FINAL` means another `GroupFrame` or a separate
stage. Resolve each such decision from the current schedule, current live
stage/group data, `/api/ai`, and explicit user approval. If those sources do not
determine the mapping uniquely, publish it as ambiguous and ask the user before
the phase CTA.

Create a fresh snapshot at the explicit path chosen for the current workflow.
Never discover or reuse a snapshot merely because a similarly named JSON file
already exists.

The snapshot contract has three data roots:

- `graph`: raw live OVS entity collections such as `Sessions`,
  `Competitions`, `Stages`, and `Groups`;
- `catalog`: normalized summaries, writable fields, constants, and relation
  indexes prepared for planning;
- `apiAi`: the machine-readable `/api/ai` response.

Do not read legacy or locally invented top-level entity keys from the snapshot.

## Credential Lifecycle

- Request an OC password/token only after approval gate 1, immediately before
  the first dry-run that requires authentication.
- In a standalone phase that must read an authenticated OVS before its first
  approval gate, request credentials only when the read actually fails or the
  user has explicitly supplied them. Read access does not authorize mutation.
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

Default field recommendations:

- Generate the initial plan with day-coded `Field:Number` values: `101`, `102`,
  `103`, then `201`, `202`, and so on. The leading digits are the ordinal
  schedule day and the final two digits are the organiser session number within
  that day. In formula form:
  `dayOrdinal * 100 + organiserSessionNumber`.
- Determine `dayOrdinal` from chronological schedule dates. Preserve the source
  date and organiser session number in `Source` metadata so the numbering
  remains auditable.
- Other numbering schemes may be offered in the review summary after the
  initial plan has been generated and before the approval CTA. If the user
  selects one, publish a corrected draft and repeat the approval gate.
- `Field:Time` contains only a short session date such as `Tue 7 Jul`. It must
  not contain the session number, venue, stream, time range, or service
  metadata.
- `Field:SessionTitle` contains only the source apparatus, venue, or stream
  name. It must not duplicate the date, add generic words such as `Session` or
  `Поток`, or append an organiser session number already represented by
  `Field:Number`.

## References Plan

Use `PlanKind=ovs-session-refs-plan`, `Version=2`, and `Mode=apply` or
`recreate` for phase-2 mutation. Use `Mode=adopt` only as a read-only,
user-approved description of refs that were assembled manually in live OVS.
`apply_session_references_plan.py` must never execute `Mode=adopt`.

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
| `ExpectedExerciseCount` | yes | Positive `Stage.PerfomanceFramesLimit` from the current snapshot or planned stage |
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

If a session contains any exercise for a group, the phase-2 plan must account
for every exercise from `1` through `ExpectedExerciseCount`. Normally each is a
`ref` row. A direct user decision to omit one exercise must be represented by a
separate `RowType=omitted` row with the same visible identity and target,
`Details.omittedIntentionally=true`, and a non-empty `Details.reason`.
`approve references` alone does not authorize an omission. The canonical row
type and flag are spelled `omitted` and `omittedIntentionally`.

`ExpectedExerciseCount` is copied from the current live stage
`PerfomanceFramesLimit`, or from `StageField:PerfomanceFramesLimit` for a stage
being created. Dry-run verifies it against the live/planned stage and fails if
the plan is stale or inconsistent.

The phase-2 row order fully determines the reference order: it is the final
order in `recreate` mode and the add order for new references in `apply` mode.
Phase 3 preserves this order when generating start lists and never repairs it.

Within one TRA stage, refs must be group-major and then routine-major:
`G1/R1`, `G1/R2`, `G2/R1`, `G2/R2`. The round-major sequence `G1/R1`,
`G2/R1`, `G1/R2`, `G2/R2` is invalid. References belonging to different stages
may alternate by routine when the source schedule requires it; the executor
does not reorder across stages. If that inter-stage order is ambiguous, resolve
it with the user and repeat approval gate 2.

Dry-run validates the plan order in `recreate` mode. In `apply` mode it
validates the projected live order: existing refs followed by missing refs in
plan order. If existing refs prevent a canonical result, use `recreate` for the
affected sessions before phase 3.

Before publishing any phase-2 draft, run the offline review validator. Run it
again after every transformation of the TSV, including sorting or manual edits:

```bash
python3 skills/tra/scripts/validate_session_references_plan.py \
  --plan refs.draft.tsv
```

The validator is a rule engine. Each independent check returns a `RuleResult`
with `rule`, `status`, `errors`, `warnings`, and `data`; the report exposes
these under `ruleResults` and also aggregates compatible top-level
`errors`/`warnings`.

The validator blocks duplicate logical refs, invalid human review fields,
`ExerciseNumber`/`Target.GroupFrame` mismatches,
`GroupNumber`/`Target.GroupIndex` mismatches, inconsistent session numbers, and
non-group-major ordering inside each
`SessionID + CompetitionTitle + StageKind` block. It warns about source/review
metadata mismatches and fragmented session blocks. Warnings require review but
do not fail unless `--strict-warnings` is used.

The `exercise-completeness` rule blocks a group as soon as at least one
exercise is included but any exercise through `ExpectedExerciseCount` is
neither included nor explicitly omitted. The `omitted-exercise-details` rule
blocks omission rows without a direct user confirmation flag and reason.

A `FINAL` schedule item must not be mapped to `StageKind=Qualification` based
on `PerfomanceFramesLimit`, `GroupFrame`, or live graph shape. The validator
also detects a `Details.mappingMode` beginning with `final-to-qualification`.
Such a row is blocked unless the user directly requested the exception for that
competition and the row records both:

- `Details.finalInQualificationExplicitlyRequested=true`;
- a non-empty `Details.finalMappingBasis` containing the instruction.

General approval of the phase-2 TSV is not sufficient. Every confirmed
exception must be listed separately in the approval summary.

A mutating run that creates a stage requires `--updated-plan`. Existing
`StageID` rows are checked against the live parent competition and group list.

### Unresolved rows

`RowType=ambiguous` and `RowType=unmatched` are review-draft states only. They
may be used to expose incomplete interpretation, but an approved, applied, or
adopted references plan must not contain either.

For an uncertain human stage label, preserve the original schedule text in
`Source.raw` and record:

- `Details.proposedAction`: `stageCreate` or `skipped`;
- `Details.proposedStageKind`: required for a `stageCreate` proposal;
- `Details.proposalBasis`: why schedule context and live data suggest it;
- alternatives useful for the user's decision.

The user must resolve each row to one of three executable outcomes:

- explicit `stageCreate` followed by the required `ref` rows;
- explicit exercise-level `omitted` with
  `Details.omittedIntentionally=true` and `Details.reason`;
- explicit `skipped` with a non-empty `Details.reason`.

The canonical creation row is `stageCreate`, never `addStage`. General
`approve references` does not resolve outstanding ambiguity. The offline
validator reports unresolved draft rows and blocks them once the plan is no
longer `draft`; the executor blocks unresolved rows in every mode before token
or network access.

In recreate mode, only sessions named by `ref` rows are cleared. References in
all other sessions remain untouched.

### Decoupled phase inputs

- Standalone phase 2 may target existing live sessions without a phase-1 TSV.
  Read their IDs and human fields from a fresh snapshot, then use the ordinary
  phase-2 draft, approval, dry-run, and apply workflow.
- Standalone phase 3 may adopt manually assembled live refs. Build a
  `Mode=adopt`, `PlanStatus=draft` TSV from a fresh snapshot, validate it,
  publish it for explicit reference approval, then set
  `PlanStatus=approved`. This artifact is never applied to OVS.
- Approval of an adopted refs TSV uses the exact CTA from the phase-3 recipe
  and is independent of the later start-list approval.
- Phase 3 compares the exact ordered `(GroupID, GroupFrame)` list for every
  target session against `--references-plan` before generation. Any live drift
  requires a fresh adopted draft and approval.

## Start-List Plan

Use `PlanKind=ovs-session-start-lists-plan`, `Version=1`, and `Mode=create` or
`append`.

Executable rows use `RowType=session`, an explicit `SessionID`, exactly one
writable field `Field:RotationView`, and the same approval status rule. Sessions
with zero refs must instead use non-executable `RowType=omitted`, an explicit
`SessionID`, human-facing number/title when available, and a non-empty
`Details.reason`. The executor includes omitted rows in its audit but never
patches or generates them.

Resolve allowed rotation values from current `/api/ai`. The executor patches
this approved field before generation and verifies the resulting value. Phase
3 additionally requires
`--references-plan` pointing either
to a phase-2 apply/recreate TSV with `PlanStatus=applied`, or to a `Mode=adopt`
TSV with `PlanStatus=approved`. The executor re-runs the offline validator and
compares its ordered refs with live OVS before generation. The executor reports:

- `generated`;
- `refs-without-performances`, an expected non-error state when referenced
  groups do not yet contain performances;
- `performances-without-frames` as an error.

### `Field:RotationView` choices

The TRA UI uses this fixed value order:

| Value | Localization key | Russian | English |
| ---: | --- | --- | --- |
| `0` | `RotationEmpty` | `не разделять` | `keep as one` |
| `1` | `RotationByParticipant` | `ротации участников` | `participants rotation` |
| `2` | `RotationByRoutine` | `этапу и номеру упражнения` | `stage and routine number` |
| `3` | `RotationByRoutineNoRefSkip` | `этапу и номеру упражнения, добавив все этапы` | `stage and routine number, ensure all groups` |
| `4` | `RotationByCandR` | `соревнованию, этапу и номеру упражнения` | `competition, stage, routine number` |
| `5` | `RotationByCandRNoRefSkip` | `соревнованию, этапу и номеру упражнени, добавив все этапы` | `competition, stage, routine number, ensure all groups` |
| `6` | `RotationByC` | `соревнованию` | `competition` |
| `7` | `RotationByCNoRefSkip` | `соревнованию, добавив все этапы` | `competition, ensure all groups` |

The Russian value-5 text intentionally preserves the current UI spelling.
TRA declares `en`, `ru`, `ja`, and `cn`, but its `ja` and `cn` resources do not
override these keys; they fall back to the English labels through
`default_locale=en`.

Before approval gate 3, show the choices in the user's locale and obtain an
explicit selection. Do not treat the current live value as approval and do not
default all sessions to `0`. Record the selected integer in each row; one value
may be applied to all sessions only when the user chooses that explicitly.

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
Read raw entities from `graph`, normalized indexes from `catalog`, and API
metadata from `apiAi`; do not expect entity collections at the snapshot root.

Print a canonical phase-2 example directly from the executor:

```bash
python3 skills/tra/scripts/apply_session_references_plan.py --print-example
```

The generated example uses the same TSV writer and is accepted by the same
parser and offline validator as a real plan.

## Environment Troubleshooting

Treat failures before an HTTP response separately from plan validation:

- DNS, connection, sandbox, filesystem, and network-policy errors indicate an
  environment blocker, not an invalid TSV;
- use the canonical scripts after obtaining the required environment access;
- do not replace the executor, alter plan semantics, change the target server,
  or bypass authentication merely because the environment blocked a command;
- if authenticated access still fails, request the user's current credentials
  rather than recovering a token from unrelated files.

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
# Standalone phase 3: first export and approve the live refs.
python3 skills/tra/scripts/build_adopted_session_references_plan.py \
  --snapshot workflow-snapshot.json \
  --output refs.adopted.draft.tsv \
  --session-id 12

python3 skills/tra/scripts/generate_session_start_lists.py \
  --base-url http://ovs.example \
  --plan start-lists.approved.tsv \
  --references-plan refs.applied-or-adopted.tsv \
  --token-file token.txt \
  --audit-output start-lists.audit.json
```
