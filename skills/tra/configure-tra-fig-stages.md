# Configure TRA FIG Stages

## Goal
Set TRA stage kinds and common FIG-style calculation and tie-break options.

## When To Use
Use when an agent must turn a simple TRA competition into one of these layouts:

- Qualification + Qualification2 + Final1 + Final2
- Qualification + Final1 + Final2

## Read First
Read `/api/ai` from the target server before using this skill. Use:

- `constants.StageKinds` for stage kind values.
- `constants.CalcKinds` for `CalcOptions` values.
- `constants.Tiebreakers` for `Tiebreakers` values.
- `fieldDocs.Stage.CalcOptions`, `fieldDocs.Stage.Tiebreakers`, and `fieldDocs.Stage.PerfomanceFramesLimit` for field semantics.
- `principles.created-location-id` for IDs returned by `POST /api/stages/`.

Do not use numeric examples without resolving constants on the target server.

## Inputs
- `token`
- `competitionID`
- `qualificationStageID`
- optional existing stage IDs to delete
- desired layout

## Request Pattern

### 1. Patch qualification stage

```http
PATCH /api/stages/{qualificationStageID}
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "Kind": 0,
  "CalcOptions": [5, 14, 22, 31],
  "Tiebreakers": [1, 2, 3, 0, 0, 0, 0, 0]
}
```

### 2. Optional Qualification2
For `Qualification + Qualification2 + Final1 + Final2`, create and patch Qualification2.

```http
POST /api/stages/
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "ParentID": 26
}
```

`ParentID` is `competitionID`. Extract `qualification2StageID` from `Location`.

```http
PATCH /api/stages/{qualification2StageID}
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "Kind": 6
}
```

For `Qualification + Final1 + Final2`, skip this request pair.

### 3. Create and patch Final1

```http
POST /api/stages/
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "ParentID": 26
}
```

Extract `final1StageID` from `Location`.

```http
PATCH /api/stages/{final1StageID}
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "Kind": 8,
  "Tiebreakers": [5, 1, 2, 3, 0, 0, 0, 0]
}
```

### 4. Create and patch Final2

```http
POST /api/stages/
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "ParentID": 26
}
```

Extract `final2StageID` from `Location`.

```http
PATCH /api/stages/{final2StageID}
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "Kind": 7,
  "CalcOptions": [5, 9, 14, 22, 31],
  "Tiebreakers": [5, 1, 2, 3, 0, 0, 0, 0],
  "PerfomanceFramesLimit": 1
}
```

The API field is spelled `PerfomanceFramesLimit` for backward compatibility.

### 5. Delete intentionally discarded stages

```http
DELETE /api/stages/{stageID}
Authorization: token <uuid>
```

Only delete empty or intentionally discarded stages.

### 6. Refetch competition graph

```http
GET /api/competitions/{competitionID}?fetch_competition_stages=true&fetch_stage_groups=true
```

Server may sort stages according to stage kind order after patching `Kind`.

## Mutation Risk
High. This changes competition structure and calculation semantics.
