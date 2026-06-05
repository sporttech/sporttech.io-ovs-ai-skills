# Draw a TRA Stage Start List

## Goal
Shuffle or redistribute stage performances across groups using the server action endpoint.

## When To Use
Use when a TRA stage already has groups and performances and the agent must perform a start-list draw.

## Read First
Read `/api/ai` from the target server before using this skill. Use:

- `actions` to confirm `stages.draw` is available.
- `fetchFlags` for `fetch_stage_groups`, `fetch_group_performances`, and `fetch_performance_athletes`.
- `auth` for mutation permissions.

## Inputs
- `token`
- `stageID`
- `seed`

## Requests

### 1. Read stage graph before draw

```http
GET /api/stages/{stageID}?fetch_stage_groups=true&fetch_group_performances=true&fetch_performance_athletes=true
```

Use the response to verify there are groups and performances to draw.

### 2. Call draw action

```http
POST /api/stages/{stageID}/draw?seed=123
Authorization: token <uuid>
```

The action returns `204 No Content` on success.

`seed=-1` keeps the collected performance order. Any other integer performs deterministic shuffling.

### 3. Refetch stage graph

```http
GET /api/stages/{stageID}?fetch_stage_groups=true&fetch_group_performances=true&fetch_performance_athletes=true
```

Read `Groups[id].Performances` to get the new order.

## Failure Modes
- Missing or non-integer `seed` can fail the action.
- Stage without groups or performances cannot produce a useful draw.
- Insufficient role permissions reject the mutation.

## Mutation Risk
High. This changes start-list order.
