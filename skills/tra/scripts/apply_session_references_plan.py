#!/usr/bin/env python3
"""Validate and apply a version 2 declarative OVS session references plan."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from ovs_plan_utils import (
    ApiError,
    collection_map,
    extract_created_id,
    refs_for_session,
    request_json,
    model_section,
    validate_fields,
    writable_field_docs,
)
from plan_table import load_refs_plan, write_refs_plan
from validate_session_references_plan import validate_plan, validation_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply an ovs-session-refs-plan v2.")
    parser.add_argument("--base-url")
    parser.add_argument("--plan")
    parser.add_argument(
        "--print-example",
        action="store_true",
        help=(
            "Print a canonical draft TSV containing stageCreate, ref, and "
            "skipped rows, then exit."
        ),
    )
    parser.add_argument("--token")
    parser.add_argument("--token-file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--updated-plan", help="Write canonical TSV with actual IDs.")
    parser.add_argument("--audit-output", help="Optional JSON execution audit.")
    return parser.parse_args()


def example_plan() -> dict[str, Any]:
    return {
        "mode": "recreate",
        "status": "draft",
        "stageCreates": [
            {
                "competitionID": 10,
                "stageID": None,
                "groupIDs": [],
                "stageKind": "Final1",
                "fields": {"PerfomanceFramesLimit": 1},
                "source": {
                    "raw": "Women FINAL",
                    "competitionTitle": "Women Individual",
                },
                "details": {
                    "userDecisionBasis": (
                        "User approved creating a separate Final1 stage."
                    )
                },
            }
        ],
        "refs": [
            {
                "sessionID": 501,
                "targetCompetitionID": 10,
                "targetStageKind": "Final1",
                "groupIndex": 0,
                "GroupFrame": 0,
                "source": {
                    "raw": "Women FINAL",
                    "sessionNumber": 501,
                    "sessionTitle": "TRA 1",
                    "competitionTitle": "Women Individual",
                    "stageKind": "Final1",
                    "groupNumber": 1,
                },
            }
        ],
        "ambiguous": [],
        "unmatched": [],
        "skipped": [
            {
                "source": {
                    "raw": "Men Final 2",
                    "sessionID": 502,
                    "sessionNumber": 502,
                    "sessionTitle": "TRA 2",
                    "competitionTitle": "Men Individual",
                },
                "reason": (
                    "User approved omitting this schedule item; no stage will "
                    "be created."
                ),
            }
        ],
    }


def print_example() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "session-refs.example.tsv"
        write_refs_plan(str(path), example_plan())
        error = validation_error(validate_plan(str(path)))
        if error:
            raise SystemExit(f"Built-in canonical example is invalid: {error}")
        sys.stdout.write(path.read_text(encoding="utf-8-sig"))


def read_token(args: argparse.Namespace) -> str:
    if args.token and args.token_file:
        raise SystemExit("Use either --token or --token-file, not both.")
    token = (
        Path(args.token_file).read_text(encoding="utf-8").strip()
        if args.token_file
        else (args.token or "").strip()
    )
    if not token:
        raise SystemExit("A token is required.")
    return token


def load_plan(path: str) -> dict[str, Any]:
    plan = load_refs_plan(path)
    if plan.get("mode") not in {"apply", "recreate"}:
        raise SystemExit("Plan mode must be 'apply' or 'recreate'.")
    for field in ("stageCreates", "refs", "ambiguous", "unmatched", "skipped"):
        if not isinstance(plan.get(field), list):
            raise SystemExit(f"Plan must contain a {field!r} array.")
    unresolved = len(plan["ambiguous"]) + len(plan["unmatched"])
    if unresolved:
        raise SystemExit(
            f"Reference plan contains {unresolved} unresolved ambiguous/unmatched "
            "rows. Resolve each row to stageCreate + ref or skipped before "
            "dry-run or apply."
        )
    return plan


def event_graph(base_url: str, token: str) -> dict[str, Any]:
    graph, _ = request_json(
        base_url,
        "/api/event?fetch_event_competitions=true&fetch_competition_stages=true"
        "&fetch_stage_groups=true&fetch_event_sessions=true&fetch_session_groups=true",
        token,
    )
    return graph if isinstance(graph, dict) else {}


def validate_stage_creates(
    plan: dict[str, Any],
    writable: dict[str, dict[str, Any]],
    stage_kinds: dict[str, int],
    competitions: dict[str, dict[str, Any]],
    stages: dict[str, dict[str, Any]],
    groups: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    targets: set[tuple[int, str]] = set()
    stage_ids: set[int] = set()
    for index, entry in enumerate(plan["stageCreates"], start=1):
        if not isinstance(entry, dict):
            raise SystemExit(f"stageCreates[{index}] must be an object.")
        competition_id = entry.get("competitionID")
        if not isinstance(competition_id, int) or isinstance(competition_id, bool):
            raise SystemExit(f"stageCreates[{index}].competitionID must be an integer.")
        if str(competition_id) not in competitions:
            raise SystemExit(f"Competition {competition_id} does not exist.")
        stage_id = entry.get("stageID")
        group_ids = entry.get("groupIDs", [])
        stage_kind = str(entry.get("stageKind", "")).strip()
        if stage_kind not in stage_kinds:
            raise SystemExit(
                f"stageCreates[{index}].StageKind {stage_kind!r} "
                "was not found in /api/ai StageKinds."
            )
        target = (competition_id, stage_kind)
        if target in targets:
            raise SystemExit(
                f"Duplicate stageCreate target: competitionID={competition_id}, "
                f"StageKind={stage_kind}"
            )
        targets.add(target)
        if stage_id is not None:
            if not isinstance(stage_id, int) or str(stage_id) not in stages:
                raise SystemExit(f"stageCreates[{index}].stageID does not exist.")
            if stage_id in stage_ids:
                raise SystemExit(f"Duplicate stageID in stageCreates: {stage_id}")
            stage_ids.add(stage_id)
            live_stage = stages[str(stage_id)]
            parent_id = live_stage.get("ParentID")
            if parent_id is not None and int(parent_id) != competition_id:
                raise SystemExit(
                    f"stageCreates[{index}].stageID {stage_id} belongs to competition "
                    f"{parent_id}, not {competition_id}."
                )
            live_group_ids = [int(value) for value in live_stage.get("Groups") or []]
            missing_live_groups = [
                group_id
                for group_id in live_group_ids
                if str(group_id) not in groups
            ]
            if missing_live_groups:
                raise SystemExit(
                    f"stageCreates[{index}].stageID {stage_id} references groups "
                    f"missing from the live graph: {missing_live_groups}."
                )
            if group_ids:
                if not isinstance(group_ids, list) or any(
                    not isinstance(value, int) or isinstance(value, bool)
                    for value in group_ids
                ):
                    raise SystemExit(
                        f"stageCreates[{index}].groupIDs must be an integer array."
                    )
                if group_ids != live_group_ids:
                    raise SystemExit(
                        f"stageCreates[{index}].groupIDs do not match live stage "
                        f"{stage_id}: expected {live_group_ids}, got {group_ids}."
                    )
            group_ids = live_group_ids
        fields = validate_fields("Stage", entry.get("fields"), writable)
        validated.append(
            {
                **entry,
                "groupIDs": group_ids,
                "stageKind": stage_kind,
                "stageKindValue": stage_kinds[stage_kind],
                "fields": fields,
            }
        )
    return validated


def validate_refs(
    plan: dict[str, Any],
    stage_creates: list[dict[str, Any]],
    sessions: dict[str, dict[str, Any]],
    groups: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    create_targets = {
        (entry["competitionID"], entry["stageKind"]): entry
        for entry in stage_creates
    }
    validated: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int]] = set()
    for index, entry in enumerate(plan["refs"], start=1):
        if not isinstance(entry, dict):
            raise SystemExit(f"refs[{index}] must be an object.")
        session_id = entry.get("sessionID")
        group_frame = entry.get("GroupFrame")
        if not isinstance(session_id, int) or str(session_id) not in sessions:
            raise SystemExit(f"refs[{index}].sessionID does not exist.")
        if not isinstance(group_frame, int) or isinstance(group_frame, bool) or group_frame < 0:
            raise SystemExit(f"refs[{index}].GroupFrame must be non-negative.")
        group_id = entry.get("GroupID")
        target_competition_id = entry.get("targetCompetitionID")
        target_stage_kind = entry.get("targetStageKind")
        has_stage_target = (
            target_competition_id is not None or target_stage_kind is not None
        )
        has_group_target = group_id is not None
        if has_group_target == has_stage_target:
            raise SystemExit(
                f"refs[{index}] must contain exactly one of GroupID or "
                "TargetCompetitionID + TargetStageKind."
            )
        if group_id is not None:
            if not isinstance(group_id, int) or str(group_id) not in groups:
                raise SystemExit(f"refs[{index}].GroupID does not exist.")
            identity = str(group_id)
        else:
            if target_competition_id is None or not target_stage_kind:
                raise SystemExit(
                    f"refs[{index}] requires both TargetCompetitionID and "
                    "TargetStageKind."
                )
            target = (target_competition_id, target_stage_kind)
            if target not in create_targets:
                raise SystemExit(
                    f"refs[{index}] targets an unknown stageCreate: "
                    f"competitionID={target_competition_id}, "
                    f"StageKind={target_stage_kind}"
                )
            group_index = entry.get("groupIndex")
            if not isinstance(group_index, int) or group_index < 0:
                raise SystemExit(
                    f"refs[{index}].groupIndex must be explicit and non-negative."
                )
            applied_groups = create_targets[target].get("groupIDs") or []
            if applied_groups and group_index >= len(applied_groups):
                raise SystemExit(f"refs[{index}].groupIndex is out of range.")
            identity = f"{target_competition_id}:{target_stage_kind}:{group_index}"
        duplicate_key = (session_id, identity, group_frame)
        if duplicate_key in seen:
            raise SystemExit(f"Duplicate reference at refs[{index}].")
        seen.add(duplicate_key)
        validated.append(dict(entry))
    return validated


def group_stage_memberships(
    stages: dict[str, dict[str, Any]],
) -> dict[int, list[tuple[int, int]]]:
    memberships: dict[int, list[tuple[int, int]]] = {}
    for raw_stage_id, stage in stages.items():
        stage_id = int(stage.get("ID", raw_stage_id))
        for group_index, raw_group_id in enumerate(stage.get("Groups") or []):
            memberships.setdefault(int(raw_group_id), []).append(
                (stage_id, group_index)
            )
    return memberships


def ordered_ref_for_group(
    session_id: int,
    group_id: int,
    group_frame: int,
    memberships: dict[int, list[tuple[int, int]]],
) -> dict[str, Any]:
    candidates = memberships.get(group_id, [])
    if len(candidates) != 1:
        reason = "no stage" if not candidates else f"multiple stages {candidates}"
        raise SystemExit(
            f"Cannot determine a unique stage for GroupID={group_id} in "
            f"SessionID={session_id}: {reason}. Ask the user to resolve the "
            "reference mapping before approval."
        )
    stage_id, group_index = candidates[0]
    return {
        "sessionID": session_id,
        "stageKey": ("stage", stage_id),
        "stageLabel": f"StageID={stage_id}",
        "groupIndex": group_index,
        "GroupFrame": group_frame,
        "GroupID": group_id,
    }


def ordered_ref_for_plan(
    ref: dict[str, Any],
    create_targets: dict[tuple[int, str], dict[str, Any]],
    memberships: dict[int, list[tuple[int, int]]],
) -> dict[str, Any]:
    session_id = int(ref["sessionID"])
    group_frame = int(ref["GroupFrame"])
    group_id = ref.get("GroupID")
    if group_id is not None:
        return ordered_ref_for_group(
            session_id, int(group_id), group_frame, memberships
        )

    target = (int(ref["targetCompetitionID"]), str(ref["targetStageKind"]))
    stage = create_targets[target]
    group_index = int(ref["groupIndex"])
    stage_id = stage.get("stageID")
    resolved_group_id = None
    if stage_id is not None:
        stage_key: tuple[Any, ...] = ("stage", int(stage_id))
        stage_label = f"StageID={stage_id}"
        group_ids = stage.get("groupIDs") or []
        if group_index < len(group_ids):
            resolved_group_id = int(group_ids[group_index])
    else:
        stage_key = ("stageCreate", target[0], target[1])
        stage_label = f"CompetitionID={target[0]}, StageKind={target[1]}"
    return {
        "sessionID": session_id,
        "stageKey": stage_key,
        "stageLabel": stage_label,
        "groupIndex": group_index,
        "GroupFrame": group_frame,
        "GroupID": resolved_group_id,
    }


def validate_reference_order(
    mode: str,
    refs: list[dict[str, Any]],
    stage_creates: list[dict[str, Any]],
    sessions: dict[str, dict[str, Any]],
    stages: dict[str, dict[str, Any]],
) -> None:
    def display_order(values: list[tuple[int, int]]) -> str:
        return ", ".join(
            f"G{group_index + 1}/R{group_frame + 1}"
            for group_index, group_frame in values
        )

    memberships = group_stage_memberships(stages)
    create_targets = {
        (int(entry["competitionID"]), str(entry["stageKind"])): entry
        for entry in stage_creates
    }
    planned = [
        ordered_ref_for_plan(ref, create_targets, memberships) for ref in refs
    ]
    target_session_ids = {int(ref["sessionID"]) for ref in refs}

    ordered: list[dict[str, Any]] = []
    existing_keys: set[tuple[int, int, int]] = set()
    if mode == "apply":
        for session_id in sorted(target_session_ids):
            for group_id, group_frame in refs_for_session(
                sessions[str(session_id)]
            ):
                ordered.append(
                    ordered_ref_for_group(
                        session_id,
                        group_id,
                        group_frame,
                        memberships,
                    )
                )
                existing_keys.add((session_id, group_id, group_frame))

    for ref in planned:
        group_id = ref.get("GroupID")
        if group_id is not None and (
            int(ref["sessionID"]),
            int(group_id),
            int(ref["GroupFrame"]),
        ) in existing_keys:
            continue
        ordered.append(ref)

    blocks: dict[tuple[int, tuple[Any, ...]], list[dict[str, Any]]] = {}
    for ref in ordered:
        key = (int(ref["sessionID"]), ref["stageKey"])
        blocks.setdefault(key, []).append(ref)

    for (session_id, _stage_key), block in blocks.items():
        group_indexes = {int(ref["groupIndex"]) for ref in block}
        group_frames = {int(ref["GroupFrame"]) for ref in block}
        if len(group_indexes) < 2 or len(group_frames) < 2:
            continue
        actual = [
            (int(ref["groupIndex"]), int(ref["GroupFrame"])) for ref in block
        ]
        expected = sorted(actual)
        if actual == expected:
            continue
        suffix = (
            " Use Mode=recreate for this session because apply preserves "
            "existing references."
            if mode == "apply"
            else ""
        )
        raise SystemExit(
            f"Non-canonical reference order for SessionID={session_id}, "
            f"{block[0]['stageLabel']}: actual [{display_order(actual)}], "
            f"expected group-major order [{display_order(expected)}].{suffix}"
        )


def stage_groups(base_url: str, token: str, stage_id: int) -> list[int]:
    document, _ = request_json(
        base_url, f"/api/stages/{stage_id}?fetch_stage_groups=true", token
    )
    groups = collection_map(document, "Groups")
    if groups:
        return [int(group_id) for group_id in groups]
    if isinstance(document, dict):
        stage = document.get("Stages", {}).get(str(stage_id), document)
        values = stage.get("Groups", []) if isinstance(stage, dict) else []
        return [int(group_id) for group_id in values]
    return []


def resolve_ref(
    ref: dict[str, Any],
    stage_by_target: dict[tuple[int, str], dict[str, Any]],
) -> dict[str, Any]:
    result = dict(ref)
    if result.get("GroupID") is None:
        stage = stage_by_target[
            (result["targetCompetitionID"], result["targetStageKind"])
        ]
        result["GroupID"] = int(stage["groupIDs"][result["groupIndex"]])
        result.pop("targetCompetitionID", None)
        result.pop("targetStageKind", None)
        result.pop("groupIndex", None)
    return result


def main() -> int:
    args = parse_args()
    if args.print_example:
        print_example()
        return 0
    if not args.base_url or not args.plan:
        raise SystemExit(
            "--base-url and --plan are required unless --print-example is used."
        )
    offline_report = validate_plan(args.plan)
    offline_error = validation_error(offline_report)
    if offline_error:
        raise SystemExit(offline_error)
    plan = load_plan(args.plan)
    mode = plan["mode"]
    if not args.dry_run and plan.get("status") not in {"approved", "applied"}:
        raise SystemExit(
            "Mutating execution requires PlanStatus=approved or PlanStatus=applied."
        )
    token = read_token(args)
    api_ai, _ = request_json(args.base_url, "/api/ai", token)
    if not isinstance(api_ai, dict):
        raise SystemExit("/api/ai did not return a JSON object.")
    writable_stages = writable_field_docs(api_ai, "Stage")
    stage_kinds = {
        str(value.get("name")): int(value["value"])
        for constant in (model_section(api_ai, "constants") or [])
        if constant.get("id") == "StageKinds"
        for value in (constant.get("values") or [])
    }

    graph = event_graph(args.base_url, token)
    competitions = collection_map(graph, "Competitions")
    stages = collection_map(graph, "Stages")
    groups = collection_map(graph, "Groups")
    sessions = collection_map(graph, "Sessions")
    stage_creates = validate_stage_creates(
        plan, writable_stages, stage_kinds, competitions, stages, groups
    )
    refs = validate_refs(plan, stage_creates, sessions, groups)
    validate_reference_order(mode, refs, stage_creates, sessions, stages)
    creates_stages = any(entry.get("stageID") is None for entry in stage_creates)
    if creates_stages and not args.dry_run and not args.updated_plan:
        raise SystemExit(
            "--updated-plan is required when the plan creates stages, so assigned "
            "stage and group IDs are not lost."
        )

    applied_stages = [dict(entry) for entry in stage_creates]
    if not args.dry_run:
        for stage in applied_stages:
            if stage.get("stageID") is None:
                _, headers = request_json(
                    args.base_url,
                    "/api/stages/",
                    token,
                    "POST",
                    {"ParentID": stage["competitionID"]},
                )
                stage["stageID"] = extract_created_id(headers.get("Location"))
            request_json(
                args.base_url,
                f"/api/stages/{stage['stageID']}",
                token,
                "PATCH",
                {"Kind": stage["stageKindValue"], **stage["fields"]},
            )
            stage["groupIDs"] = stage_groups(args.base_url, token, stage["stageID"])
            if not stage["groupIDs"]:
                raise ApiError(f"Stage {stage['stageID']} has no groups.")

    stage_by_target = {
        (entry["competitionID"], entry["stageKind"]): entry
        for entry in applied_stages
    }
    resolved_refs = [
        resolve_ref(ref, stage_by_target)
        if not args.dry_run or ref.get("GroupID") is not None
        else dict(ref)
        for ref in refs
    ]
    target_session_ids = sorted({int(ref["sessionID"]) for ref in refs})
    removed: list[dict[str, int]] = []
    added: list[dict[str, Any]] = []
    if not args.dry_run:
        fresh_sessions = collection_map(event_graph(args.base_url, token), "Sessions")
        if mode == "recreate":
            for session_id in target_session_ids:
                for group_id, group_frame in refs_for_session(
                    fresh_sessions[str(session_id)]
                ):
                    request_json(
                        args.base_url,
                        f"/api/sessions/{session_id}/removeRef",
                        token,
                        "POST",
                        {"GroupID": group_id, "GroupFrame": group_frame},
                    )
                    removed.append(
                        {
                            "sessionID": session_id,
                            "GroupID": group_id,
                            "GroupFrame": group_frame,
                        }
                    )
            existing: set[tuple[int, int, int]] = set()
        else:
            existing = {
                (session_id, group_id, group_frame)
                for session_id in target_session_ids
                for group_id, group_frame in refs_for_session(
                    fresh_sessions[str(session_id)]
                )
            }
        for order, ref in enumerate(resolved_refs, start=1):
            key = (int(ref["sessionID"]), int(ref["GroupID"]), int(ref["GroupFrame"]))
            if key in existing:
                continue
            request_json(
                args.base_url,
                f"/api/sessions/{ref['sessionID']}/addRef",
                token,
                "POST",
                {"GroupID": ref["GroupID"], "GroupFrame": ref["GroupFrame"]},
            )
            added.append({**ref, "appliedOrder": order})
            existing.add(key)

    verification: dict[str, Any] = {"status": "not-run" if args.dry_run else "matched"}
    if not args.dry_run:
        after_sessions = collection_map(event_graph(args.base_url, token), "Sessions")
        mismatches: dict[str, Any] = {}
        expected_by_session: dict[int, list[tuple[int, int]]] = {}
        for ref in resolved_refs:
            expected_by_session.setdefault(int(ref["sessionID"]), []).append(
                (int(ref["GroupID"]), int(ref["GroupFrame"]))
            )
        for session_id, expected in expected_by_session.items():
            actual = refs_for_session(after_sessions[str(session_id)])
            matched = actual == expected if mode == "recreate" else all(
                item in actual for item in expected
            )
            if not matched:
                mismatches[str(session_id)] = {
                    "expected": expected,
                    "actual": actual,
                }
        verification = {
            "status": "matched" if not mismatches else "mismatch",
            "mismatches": mismatches,
        }

    result = {
        **plan,
        "status": "applied" if not args.dry_run else plan.get("status"),
        "stageCreates": applied_stages,
        "refs": resolved_refs,
        "apply": {
            "baseUrl": args.base_url.rstrip("/"),
            "mode": mode,
            "dryRun": args.dry_run,
            "targetSessionIDs": target_session_ids,
            "createdStages": sum(
                original.get("stageID") is None and applied.get("stageID") is not None
                for original, applied in zip(stage_creates, applied_stages)
            )
            if not args.dry_run
            else 0,
            "removedRefs": removed,
            "addedRefs": added,
            "verification": verification,
        },
    }
    if args.updated_plan and not args.dry_run:
        write_refs_plan(args.updated_plan, result)
        print(f"Wrote canonical applied plan to {args.updated_plan}")
    if args.audit_output:
        Path(args.audit_output).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote audit to {args.audit_output}")
    if verification["status"] == "mismatch":
        raise ApiError("Reference verification failed.")
    print(
        f"{'Validated' if args.dry_run else 'Applied'} "
        f"{len(applied_stages)} stage creates and {len(refs)} references."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
