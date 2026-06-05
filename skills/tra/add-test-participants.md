# Add TRA Test Participants

## Goal
Create one or more performances in a group and fill the automatically-created athlete records.

## When To Use
Use after creating or locating a TRA group that should receive synthetic participants.

## Read First
Read `/api/ai` from the target server before using this skill. Use:

- `entityTypes` for `/api/performances/` and `/api/athletes/{id}` availability.
- `principles.created-location-id` for IDs from `Location`.
- `fieldDocs` for `Athlete.Sex`, `Athlete.DateOfBirth`, and `Person.ExternalID` semantics.
- `importFormats` only if generating CSV/XLSX instead of direct API writes.

## Inputs
- `token`
- `groupID`
- participant names and optional profile fields

## Requests

### 1. Create performance in group

```http
POST /api/performances/
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "ParentID": 119
}
```

`ParentID` is the target `groupID`.

### 2. Extract `performanceID`
Read it from the `Location` response header.

### 3. Read created athlete slots

```http
GET /api/performances/{performanceID}?fetch_performance_athletes=true
```

The server creates the performance, its frames, and blank athlete slot(s). Resolve athlete IDs through `Performance.Athletes -> Athletes`.

### 4. Patch athlete fields

```http
PATCH /api/athletes/{athleteID}
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "Surname": "Testov",
  "GivenName": "Participant01",
  "Representing": "Test Region",
  "Sex": "male",
  "DateOfBirth": "2008-01-01T00:00:00Z",
  "Level": "TEST",
  "ExternalID": 100001
}
```

Use API field names, not UI aliases:

- `GivenName`, not `FirstName`.
- `Surname`, not `LastName`.
- `Representing`, not `Region`.

`Sex` is a string. For individual athlete records, use `male` or `female`. `DateOfBirth` for direct API writes is RFC3339.

## Response Hints
- Repeat POST/GET/PATCH for each participant or team entry as needed.
- After patching, refetch the group/stage graph with `fetch_group_performances=true&fetch_performance_athletes=true`.

## Mutation Risk
High. This creates performances and patches athletes.
