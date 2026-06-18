#!/usr/bin/env python3
"""Fetch one reusable, read-only OVS snapshot for session planning."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ovs_plan_utils import (
    ApiError,
    collection_map,
    model_section,
    refs_for_session,
    request_json,
    writable_field_docs,
)


GRAPH_PATH = (
    "/api/event?fetch_event_competitions=true&fetch_competition_stages=true"
    "&fetch_stage_groups=true&fetch_group_performances=true"
    "&fetch_event_sessions=true&fetch_session_groups=true"
    "&fetch_session_frames=true"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch /api/ai and the live competition, stage, group, performance, "
            "and session graph into one LLM-friendly JSON snapshot."
        )
    )
    parser.add_argument("--base-url", required=True, help="OVS server root URL.")
    parser.add_argument("--output", required=True, help="Output JSON snapshot.")
    parser.add_argument("--token")
    parser.add_argument("--token-file")
    return parser.parse_args()


def read_token(args: argparse.Namespace) -> str:
    if args.token and args.token_file:
        raise SystemExit("Use either --token or --token-file, not both.")
    return (
        Path(args.token_file).read_text(encoding="utf-8").strip()
        if args.token_file
        else (args.token or "").strip()
    )


def constant_values(api_ai: dict[str, Any], constant_id: str) -> list[dict[str, Any]]:
    for constant in model_section(api_ai, "constants") or []:
        if constant.get("id") == constant_id:
            return list(constant.get("values") or [])
    return []


def action_map(api_ai: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(action["id"]): action
        for action in model_section(api_ai, "actions") or []
        if action.get("id")
    }


def relation_ids(entity: dict[str, Any], field: str) -> list[int]:
    result = []
    for value in entity.get(field) or []:
        if isinstance(value, dict):
            value = value.get("ID", value.get("id"))
        if value is not None:
            result.append(int(value))
    return result


def build_catalog(api_ai: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    competitions = collection_map(graph, "Competitions")
    stages = collection_map(graph, "Stages")
    groups = collection_map(graph, "Groups")
    performances = collection_map(graph, "Performances")
    sessions = collection_map(graph, "Sessions")
    return {
        "summary": {
            "competitionCount": len(competitions),
            "stageCount": len(stages),
            "groupCount": len(groups),
            "performanceCount": len(performances),
            "sessionCount": len(sessions),
        },
        "writableFields": {
            "Session": writable_field_docs(api_ai, "Session"),
            "Stage": writable_field_docs(api_ai, "Stage"),
        },
        "stageKinds": {
            str(value.get("name")): value.get("value")
            for value in constant_values(api_ai, "StageKinds")
        },
        "sessionActions": {
            action_id: action
            for action_id, action in action_map(api_ai).items()
            if action_id.startswith("sessions.")
        },
        "relations": {
            "competitionStages": {
                competition_id: relation_ids(competition, "Stages")
                for competition_id, competition in competitions.items()
            },
            "stageGroups": {
                stage_id: relation_ids(stage, "Groups")
                for stage_id, stage in stages.items()
            },
            "groupPerformances": {
                group_id: relation_ids(group, "Performances")
                for group_id, group in groups.items()
            },
            "sessionReferences": {
                session_id: [
                    {"GroupID": group_id, "GroupFrame": group_frame}
                    for group_id, group_frame in refs_for_session(session)
                ]
                for session_id, session in sessions.items()
            },
            "sessionFrames": {
                session_id: relation_ids(session, "Frames")
                for session_id, session in sessions.items()
            },
        },
    }


def main() -> int:
    args = parse_args()
    token = read_token(args)
    api_ai, _ = request_json(args.base_url, "/api/ai", token)
    graph, _ = request_json(args.base_url, GRAPH_PATH, token)
    if not isinstance(api_ai, dict) or not isinstance(graph, dict):
        raise ApiError("OVS inspection endpoints did not return JSON objects.")
    result = {
        "kind": "ovs-session-workflow-snapshot",
        "version": 1,
        "baseUrl": args.base_url.rstrip("/"),
        "readOnly": True,
        "catalog": build_catalog(api_ai, graph),
        "apiAi": api_ai,
        "graph": graph,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = result["catalog"]["summary"]
    print(
        f"Wrote read-only snapshot: competitions={summary['competitionCount']} "
        f"stages={summary['stageCount']} groups={summary['groupCount']} "
        f"sessions={summary['sessionCount']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
