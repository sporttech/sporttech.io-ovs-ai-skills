#!/usr/bin/env python3
"""Generate and verify start lists from an explicit session ID plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ovs_plan_utils import ApiError, collection_map, request_json
from plan_table import load_start_lists_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply an ovs-session-start-lists-plan v1."
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--token")
    parser.add_argument("--token-file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--audit-output")
    return parser.parse_args()


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
    plan = load_start_lists_plan(path)
    if plan.get("mode") not in {"create", "append"}:
        raise SystemExit("Plan mode must be 'create' or 'append'.")
    session_ids = plan.get("sessionIDs")
    if not isinstance(session_ids, list) or not session_ids:
        raise SystemExit("Plan must contain a non-empty sessionIDs array.")
    if any(not isinstance(value, int) or isinstance(value, bool) for value in session_ids):
        raise SystemExit("Every sessionID must be an integer.")
    if len(session_ids) != len(set(session_ids)):
        raise SystemExit("sessionIDs must be unique.")
    return plan


def event_graph(base_url: str, token: str) -> dict[str, Any]:
    graph, _ = request_json(
        base_url,
        "/api/event?fetch_event_sessions=true&fetch_session_groups=true"
        "&fetch_session_frames=true",
        token,
    )
    return graph if isinstance(graph, dict) else {}


def referenced_performance_count(
    base_url: str, token: str, session_id: int
) -> int:
    detail, _ = request_json(
        base_url,
        f"/api/sessions/{session_id}?fetch_session_groups=true"
        "&fetch_group_performances=true&fetch_session_frames=true",
        token,
    )
    groups = collection_map(detail, "Groups")
    return sum(len(group.get("Performances") or []) for group in groups.values())


def main() -> int:
    args = parse_args()
    token = read_token(args)
    plan = load_plan(args.plan)
    if not args.dry_run and plan.get("status") not in {"approved", "applied"}:
        raise SystemExit(
            "Mutating execution requires PlanStatus=approved or PlanStatus=applied."
        )
    session_ids = plan["sessionIDs"]
    before = collection_map(event_graph(args.base_url, token), "Sessions")
    missing = [session_id for session_id in session_ids if str(session_id) not in before]
    if missing:
        raise SystemExit(f"Sessions missing from target server: {missing}")

    targets = [
        {
            "sessionID": session_id,
            "fields": {
                key: before[str(session_id)].get(key)
                for key in ("Number", "Time", "SessionTitle")
            },
            "referenceCount": len(before[str(session_id)].get("Groups") or []),
            "framesBefore": len(before[str(session_id)].get("Frames") or []),
        }
        for session_id in session_ids
    ]
    if not args.dry_run:
        for session_id in session_ids:
            request_json(
                args.base_url,
                f"/api/sessions/{session_id}/generate",
                token,
                "POST",
                {"mode": plan["mode"]},
            )

    after = before if args.dry_run else collection_map(
        event_graph(args.base_url, token), "Sessions"
    )
    report_sessions = []
    for target in targets:
        session_id = target["sessionID"]
        frames_after = len(after[str(session_id)].get("Frames") or [])
        performances = None
        if target["referenceCount"] and not frames_after and not args.dry_run:
            performances = referenced_performance_count(
                args.base_url, token, session_id
            )
        if args.dry_run:
            status = "not-run"
        elif target["referenceCount"] == 0:
            status = "no-refs"
        elif frames_after > 0:
            status = "generated"
        elif performances == 0:
            status = "refs-without-performances"
        else:
            status = "performances-without-frames"
        report_sessions.append(
            {
                **target,
                "framesAfter": frames_after,
                "referencedPerformanceCount": performances,
                "status": status,
            }
        )

    report = {
        "kind": "ovs-session-start-lists-report",
        "version": 1,
        "sourcePlan": args.plan,
        "mode": plan["mode"],
        "dryRun": args.dry_run,
        "sessions": report_sessions,
    }
    if args.audit_output:
        Path(args.audit_output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote audit to {args.audit_output}")
    failed = [
        item
        for item in report_sessions
        if item["status"] == "performances-without-frames"
    ]
    if failed:
        raise ApiError(
            "Sessions with referenced performances but no frames: "
            + ", ".join(str(item["sessionID"]) for item in failed)
        )
    print(
        f"{'Validated' if args.dry_run else 'Generated'} "
        f"{len(report_sessions)} session start lists."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
