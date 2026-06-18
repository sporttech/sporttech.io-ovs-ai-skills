#!/usr/bin/env python3
"""Validate and apply a version 2 declarative OVS session plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ovs_plan_utils import (
    ApiError,
    collection_map,
    extract_created_id,
    request_json,
    validate_fields,
    writable_field_docs,
)
from plan_table import load_session_plan, write_session_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply an ovs-session-plan v2.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--token")
    parser.add_argument("--token-file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--updated-plan", help="Write the canonical TSV with assigned IDs.")
    parser.add_argument("--audit-output", help="Optional JSON execution audit.")
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
    plan = load_session_plan(path)
    if plan.get("mode") not in {"create", "patch"}:
        raise SystemExit("Plan mode must be 'create' or 'patch'.")
    if not isinstance(plan.get("sessions"), list) or not plan["sessions"]:
        raise SystemExit("Plan must contain a non-empty sessions array.")
    return plan


def validate_plan(
    plan: dict[str, Any],
    writable: dict[str, dict[str, Any]],
    live_sessions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    mode = plan["mode"]
    validated: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for index, entry in enumerate(plan["sessions"], start=1):
        if not isinstance(entry, dict):
            raise SystemExit(f"sessions[{index}] must be an object.")
        session_id = entry.get("sessionID")
        if mode == "patch" and session_id is None:
            raise SystemExit(f"sessions[{index}].sessionID is required in patch mode.")
        if session_id is not None:
            if not isinstance(session_id, int) or isinstance(session_id, bool) or session_id < 0:
                raise SystemExit(f"sessions[{index}].sessionID must be a non-negative integer.")
            if session_id in seen_ids:
                raise SystemExit(f"Duplicate sessionID in plan: {session_id}")
            seen_ids.add(session_id)
            if str(session_id) not in live_sessions:
                raise SystemExit(f"Session {session_id} does not exist on the target server.")
        fields = validate_fields("Session", entry.get("fields"), writable)
        validated.append(
            {
                **entry,
                "sessionID": session_id,
                "fields": fields,
                "_planIndex": index,
            }
        )
    return validated


def event_graph(base_url: str, token: str) -> dict[str, Any]:
    graph, _ = request_json(
        base_url,
        "/api/event?fetch_event_sessions=true&fetch_session_groups=true"
        "&fetch_session_frames=true",
        token,
    )
    return graph if isinstance(graph, dict) else {}


def write_audit(path: str | None, plan: dict[str, Any]) -> None:
    if path:
        Path(path).write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote result to {path}")


def main() -> int:
    args = parse_args()
    token = read_token(args)
    plan = load_plan(args.plan)
    if not args.dry_run and plan.get("status") not in {"approved", "applied"}:
        raise SystemExit(
            "Mutating execution requires PlanStatus=approved or PlanStatus=applied."
        )
    api_ai, _ = request_json(args.base_url, "/api/ai", token)
    if not isinstance(api_ai, dict):
        raise SystemExit("/api/ai did not return a JSON object.")
    writable = writable_field_docs(api_ai, "Session")
    live_before = collection_map(event_graph(args.base_url, token), "Sessions")
    sessions = validate_plan(plan, writable, live_before)
    creates_sessions = any(
        plan["mode"] == "create" and entry.get("sessionID") is None
        for entry in sessions
    )
    if creates_sessions and not args.dry_run and not args.updated_plan:
        raise SystemExit(
            "--updated-plan is required when the plan creates sessions, so assigned "
            "IDs are not lost."
        )

    results: list[dict[str, Any]] = []
    for entry in sessions:
        session_id = entry["sessionID"]
        action = "patch"
        if plan["mode"] == "create" and session_id is None:
            action = "create"
        elif plan["mode"] == "create":
            action = "reuse"
        results.append(
            {
                **{key: value for key, value in entry.items() if key != "_planIndex"},
                "action": action,
                "verification": {"status": "pending"},
            }
        )

    if not args.dry_run:
        for result in results:
            if result["action"] == "create":
                _, headers = request_json(
                    args.base_url, "/api/sessions/", token, "POST", {}
                )
                result["sessionID"] = extract_created_id(headers.get("Location"))
            request_json(
                args.base_url,
                f"/api/sessions/{result['sessionID']}",
                token,
                "PATCH",
                result["fields"],
            )

    live_after = live_before if args.dry_run else collection_map(
        event_graph(args.base_url, token), "Sessions"
    )
    for result in results:
        if args.dry_run:
            live = live_after.get(str(result["sessionID"]), {})
            changes = {
                field: {"current": live.get(field), "proposed": proposed}
                for field, proposed in result["fields"].items()
                if live.get(field) != proposed
            }
            result["verification"] = {
                "status": "would-change" if changes else "already-matched",
                "changes": changes,
            }
            continue
        live = live_after.get(str(result["sessionID"]), {})
        mismatches = {
            field: {"expected": expected, "actual": live.get(field)}
            for field, expected in result["fields"].items()
            if live.get(field) != expected
        }
        result["verification"] = {
            "status": "matched" if not mismatches else "mismatch",
            "mismatches": mismatches,
        }

    output = {
        **plan,
        "status": "applied" if not args.dry_run else plan.get("status"),
        "sessions": results,
        "apply": {
            "baseUrl": args.base_url.rstrip("/"),
            "dryRun": args.dry_run,
            "created": sum(item["action"] == "create" for item in results)
            if not args.dry_run
            else 0,
            "patched": 0 if args.dry_run else len(results),
            "reused": sum(item["action"] == "reuse" for item in results),
        },
    }
    if args.updated_plan and not args.dry_run:
        write_session_plan(args.updated_plan, output)
        print(f"Wrote canonical applied plan to {args.updated_plan}")
    write_audit(args.audit_output, output)
    mismatched = (
        []
        if args.dry_run
        else [
            item for item in results if item["verification"]["status"] == "mismatch"
        ]
    )
    if mismatched:
        raise ApiError(
            "Session verification failed for IDs: "
            + ", ".join(str(item["sessionID"]) for item in mismatched)
        )
    print(
        f"{'Validated' if args.dry_run else 'Applied'} {len(results)} session entries."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
