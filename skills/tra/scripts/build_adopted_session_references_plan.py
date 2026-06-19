#!/usr/bin/env python3
"""Build a review TSV that adopts the current live OVS session references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ovs_plan_utils import collection_map, refs_for_session
from plan_table import write_refs_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a Mode=adopt phase-2 TSV from a workflow snapshot."
    )
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--session-id",
        type=int,
        action="append",
        dest="session_ids",
        help="Session to include; repeat for multiple sessions. Default: all sessions.",
    )
    return parser.parse_args()


def entity_title(entity: dict[str, Any], fallback: str) -> str:
    for field in ("Title", "Name", "CompetitionTitle", "SessionTitle"):
        value = entity.get(field)
        if value not in (None, ""):
            return str(value)
    return fallback


def stage_kind_name(
    stage: dict[str, Any],
    stage_kinds: dict[str, Any],
) -> str:
    raw_kind = stage.get("Kind")
    for name, value in stage_kinds.items():
        if value == raw_kind:
            return name
    return str(raw_kind) if raw_kind is not None else ""


def build_plan(snapshot_path: str, session_ids: list[int] | None) -> dict[str, Any]:
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    if snapshot.get("kind") != "ovs-session-workflow-snapshot":
        raise SystemExit("Expected an ovs-session-workflow-snapshot document.")
    graph = snapshot.get("graph")
    catalog = snapshot.get("catalog")
    if not isinstance(graph, dict) or not isinstance(catalog, dict):
        raise SystemExit("Snapshot must contain graph and catalog objects.")

    competitions = collection_map(graph, "Competitions")
    stages = collection_map(graph, "Stages")
    sessions = collection_map(graph, "Sessions")
    stage_kinds = catalog.get("stageKinds") or {}
    if not isinstance(stage_kinds, dict):
        raise SystemExit("Snapshot catalog.stageKinds must be an object.")

    group_memberships: dict[int, list[tuple[int, int]]] = {}
    for raw_stage_id, stage in stages.items():
        stage_id = int(stage.get("ID", raw_stage_id))
        for group_index, raw_group_id in enumerate(stage.get("Groups") or []):
            group_memberships.setdefault(int(raw_group_id), []).append(
                (stage_id, group_index)
            )

    selected_ids = (
        sorted(int(value) for value in sessions)
        if not session_ids
        else list(dict.fromkeys(session_ids))
    )
    missing_sessions = [
        session_id for session_id in selected_ids if str(session_id) not in sessions
    ]
    if missing_sessions:
        raise SystemExit(f"Sessions missing from snapshot: {missing_sessions}")

    refs: list[dict[str, Any]] = []
    for session_id in selected_ids:
        session = sessions[str(session_id)]
        for group_id, group_frame in refs_for_session(session):
            memberships = group_memberships.get(group_id, [])
            if len(memberships) != 1:
                raise SystemExit(
                    f"GroupID={group_id} in SessionID={session_id} must belong "
                    f"to exactly one stage, got {memberships}."
                )
            stage_id, group_index = memberships[0]
            stage = stages[str(stage_id)]
            competition_id = int(stage["ParentID"])
            competition = competitions.get(str(competition_id), {})
            expected_exercise_count = stage.get("PerfomanceFramesLimit")
            if (
                not isinstance(expected_exercise_count, int)
                or expected_exercise_count < 1
            ):
                raise SystemExit(
                    f"StageID={stage_id} must expose a positive "
                    "PerfomanceFramesLimit before its references can be adopted."
                )
            refs.append(
                {
                    "sessionID": session_id,
                    "GroupID": group_id,
                    "GroupFrame": group_frame,
                    "expectedExerciseCount": expected_exercise_count,
                    "source": {
                        "sessionNumber": session.get("Number"),
                        "sessionTitle": session.get("SessionTitle") or "",
                        "competitionTitle": entity_title(
                            competition, f"Competition {competition_id}"
                        ),
                        "stageKind": stage_kind_name(stage, stage_kinds),
                        "groupNumber": group_index + 1,
                        "adoptedFromLive": True,
                        "snapshot": str(Path(snapshot_path)),
                    },
                    "adoptedFromLive": True,
                    "stageID": stage_id,
                }
            )
    if not refs:
        raise SystemExit("Selected sessions contain no live references to adopt.")
    return {
        "mode": "adopt",
        "status": "draft",
        "stageCreates": [],
        "refs": refs,
        "ambiguous": [],
        "unmatched": [],
        "omitted": [],
        "skipped": [],
    }


def main() -> int:
    args = parse_args()
    plan = build_plan(args.snapshot, args.session_ids)
    write_refs_plan(args.output, plan)
    print(f"Wrote {len(plan['refs'])} adopted references to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
