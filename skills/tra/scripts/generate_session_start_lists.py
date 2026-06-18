#!/usr/bin/env python3
"""Generate and verify start lists for sessions from an applied session plan."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class ApiError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate OVS session frames from approved session references."
    )
    parser.add_argument("--base-url", required=True, help="OVS server root URL.")
    parser.add_argument(
        "--session-plan",
        required=True,
        help="Applied session plan containing sessionID values.",
    )
    parser.add_argument("--token", help="Authorization token value.")
    parser.add_argument("--token-file", help="File containing the authorization token.")
    parser.add_argument(
        "--mode",
        choices=("create", "append"),
        default="create",
        help="sessions.generate mode. Use create for normal regeneration.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report target sessions without mutating OVS.",
    )
    parser.add_argument("--output", help="Write the generation report to this JSON file.")
    return parser.parse_args()


def read_token(args: argparse.Namespace) -> str:
    if args.token and args.token_file:
        raise SystemExit("Use either --token or --token-file, not both.")
    if args.token_file:
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
    else:
        token = (args.token or "").strip()
    if not token:
        raise SystemExit("A token is required. Pass --token or --token-file.")
    return token


def load_sessions(path: str) -> list[dict[str, Any]]:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    sessions = plan.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise SystemExit("Session plan must contain a non-empty sessions array.")
    missing = [idx for idx, session in enumerate(sessions) if "sessionID" not in session]
    if missing:
        raise SystemExit(f"Session plan entries without sessionID: {missing}")
    return sessions


def url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def request_json(
    base_url: str,
    path: str,
    token: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> Any:
    headers = {"Authorization": f"token {token}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url(base_url, path), data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise ApiError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"{method} {path} failed: {exc.reason}") from exc
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def main() -> int:
    args = parse_args()
    token = read_token(args)
    sessions = load_sessions(args.session_plan)
    session_ids = [int(session["sessionID"]) for session in sessions]
    if len(session_ids) != len(set(session_ids)):
        raise SystemExit("Session plan contains duplicate sessionID values.")

    before = request_json(
        args.base_url,
        "/api/event?fetch_event_sessions=true&fetch_session_groups=true"
        "&fetch_session_frames=true",
        token,
    )
    live_sessions = before.get("Sessions", {})
    missing_live = [session_id for session_id in session_ids if str(session_id) not in live_sessions]
    if missing_live:
        raise SystemExit(f"Sessions missing from target server: {missing_live}")

    targets = []
    for session in sessions:
        session_id = int(session["sessionID"])
        live = live_sessions[str(session_id)]
        targets.append(
            {
                "sessionID": session_id,
                "Number": live.get("Number"),
                "Time": live.get("Time"),
                "SessionTitle": live.get("SessionTitle"),
                "referenceCount": len(live.get("Groups") or []),
                "framesBefore": len(live.get("Frames") or []),
            }
        )

    print(
        f"{'Would generate' if args.dry_run else 'Generating'} start lists for "
        f"{len(targets)} sessions with mode={args.mode}."
    )
    if not args.dry_run:
        for index, target in enumerate(targets, start=1):
            request_json(
                args.base_url,
                f"/api/sessions/{target['sessionID']}/generate",
                token,
                "POST",
                {"mode": args.mode},
            )
            print(
                f"Generated {index:02d}/{len(targets)} "
                f"session={target['sessionID']} refs={target['referenceCount']}"
            )

    after = request_json(
        args.base_url,
        "/api/event?fetch_event_sessions=true&fetch_session_groups=true"
        "&fetch_session_frames=true",
        token,
    )
    after_sessions = after.get("Sessions", {})
    report_sessions = []
    for target in targets:
        live = after_sessions[str(target["sessionID"])]
        frames_after = len(live.get("Frames") or [])
        referenced_performances = None
        if target["referenceCount"] > 0 and frames_after == 0:
            detail = request_json(
                args.base_url,
                f"/api/sessions/{target['sessionID']}?fetch_session_groups=true"
                "&fetch_group_performances=true&fetch_session_frames=true",
                token,
            )
            groups = detail.get("Groups", {})
            referenced_performances = sum(
                len(group.get("Performances") or []) for group in groups.values()
            )
        if target["referenceCount"] == 0:
            status = "no-refs"
        elif frames_after > 0:
            status = "generated"
        elif referenced_performances == 0:
            status = "refs-without-performances"
        else:
            status = "performances-without-frames"
        report_sessions.append(
            {
                **target,
                "framesAfter": frames_after,
                "referencedPerformanceCount": referenced_performances,
                "status": status,
            }
        )

    report = {
        "kind": "ovs-tra-session-start-lists-report",
        "version": 1,
        "source": {
            "sessionPlan": args.session_plan,
            "baseUrl": args.base_url.rstrip("/"),
        },
        "apply": {
            "mode": args.mode,
            "dryRun": args.dry_run,
            "sessionCount": len(report_sessions),
            "sessionsWithRefs": sum(
                session["referenceCount"] > 0 for session in report_sessions
            ),
            "sessionsWithoutRefs": sum(
                session["referenceCount"] == 0 for session in report_sessions
            ),
            "sessionsWithFrames": sum(
                session["framesAfter"] > 0 for session in report_sessions
            ),
            "sessionsWithEmptyReferencedGroups": sum(
                session["status"] == "refs-without-performances"
                for session in report_sessions
            ),
            "totalFrames": sum(
                session["framesAfter"] for session in report_sessions
            ),
        },
        "sessions": report_sessions,
    }
    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote generation report to {args.output}")

    failed = [
        session
        for session in report_sessions
        if session["status"] == "performances-without-frames"
    ]
    if failed and not args.dry_run:
        raise ApiError(
            "Sessions with referenced performances but no generated frames: "
            + ", ".join(str(session["sessionID"]) for session in failed)
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
