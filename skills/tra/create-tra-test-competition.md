# Create a TRA Test Competition

## Goal
Create a trampoline competition and verify the automatically-created first stage and group.

## When To Use
Use on TRA servers when an agent needs a visible test competition for start-list or scoring experiments.

## Read First
Read `/api/ai` from the target server before using this skill. Use:

- `runtime.app` to confirm the server is TRA.
- `constants.CompetitionTypes` for `Discipline` values.
- `constants.CompetitionPresets` for `Preset` values.
- `principles.created-location-id` for extracting the created numeric ID from `Location`.
- `methods` and `auth` for token handling.

## Inputs
- `token`
- `title`
- `discipline`
- `preset`

## Requests

### 1. Create competition

```http
POST /api/competitions/
Authorization: token <uuid>
Content-Type: application/json
```

```json
{
  "Discipline": 0,
  "Preset": 0,
  "Title": "AI Test Competition"
}
```

Use constants instead of guessing numeric values. In the current TRA FIG defaults, `Discipline=0` is TRA and `Preset=0` is `PresetAdult`, but agents must resolve this through `/api/ai.constants`.

### 2. Extract `competitionID`
Read the numeric resource ID from the `Location` response header.

Example: `Location: /api/competitions/26` means `competitionID=26`.

### 3. Verify generated children

```http
GET /api/competitions/{competitionID}?fetch_competition_stages=true&fetch_stage_groups=true
```

TRA competition creation automatically creates the first stage and first group.

## Response Hints
- Use `Competition.Stages -> Stages` to find the created first stage.
- Use `Stage.Groups -> Groups` to find the created first group.
- Refetch after mutations instead of assuming local state.

## Mutation Risk
High. This creates event data and requires a role allowed to edit the event.
