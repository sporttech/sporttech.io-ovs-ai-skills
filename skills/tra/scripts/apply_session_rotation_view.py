#!/usr/bin/env python3
"""Apply one RotationView mode to all sessions in an applied session plan."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROTATION_VIEW_LABELS = {
    0: "no grouping",
    1: "participant rotations",
    2: "stage and exercise number",
    3: "stage and exercise number, including all stages",
    4: "competition, stage, and exercise number",
    5: "competition, stage, and exercise number, including all stages",
    6: "competition",
    7: "competition, including all stages",
}


class ApiError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply a RotationView mode to sessions from an applied plan."
    )
    parser.add_argument("--base-url", required=True, help="OVS server root URL.")
    parser.add_argument(
        "--session-plan",
        required=True,
        help="Applied session plan containing sessionID values.",
    )
    parser.add_argument(
        "--rotation-view",
        required=True,
        type=int,
        choices=range(8),
        metavar="0..7",
        help="Session.RotationView mode index.",
    )
    parser.add_argument("--token", help="Authorization token value.")
    parser.add_argument("--token-file", help="File containing the authorization token.")
    parser.add_argument("--dry-run", action="store_true", help="Do not patch OVS.")
    parser.add_argument("--output", help="Write the application report to JSON.")
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
    missing = [index for index, session in enumerate(sessions) if "sessionID" not in session]
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


def event_sessions(base_url: str, token: str) -> dict[str, Any]:
    event = request_json(
        base_url,
        "/api/event?fetch_event_sessions=true",
        token,
    )
    return event.get("Sessions", {}) if isinstance(event, dict) else {}


def main() -> int:
    args = parse_args()
    token = read_token(args)
    planned = load_sessions(args.session_plan)
    session_ids = [int(session["sessionID"]) for session in planned]
    if len(session_ids) != len(set(session_ids)):
        raise SystemExit("Session plan contains duplicate sessionID values.")

    before = event_sessions(args.base_url, token)
    missing = [session_id for session_id in session_ids if str(session_id) not in before]
    if missing:
        raise SystemExit(f"Sessions missing from target server: {missing}")

    print(
        f"{'Would set' if args.dry_run else 'Setting'} RotationView="
        f"{args.rotation_view} ({ROTATION_VIEW_LABELS[args.rotation_view]}) "
        f"on {len(session_ids)} sessions."
    )
    if not args.dry_run:
        for index, session_id in enumerate(session_ids, start=1):
            request_json(
                args.base_url,
                f"/api/sessions/{session_id}",
                token,
                "PATCH",
                {"RotationView": args.rotation_view},
            )
            print(f"Patched {index:02d}/{len(session_ids)} session={session_id}")

    after = event_sessions(args.base_url, token)
    sessions = []
    mismatches = []
    for session_id in session_ids:
        current = after[str(session_id)]
        actual = int(current.get("RotationView", -1))
        status = "matched" if actual == args.rotation_view else "mismatch"
        entry = {
            "sessionID": session_id,
            "Number": current.get("Number"),
            "Time": current.get("Time"),
            "SessionTitle": current.get("SessionTitle"),
            "RotationView": actual,
            "status": status,
        }
        sessions.append(entry)
        if status == "mismatch":
            mismatches.append(entry)

    report = {
        "kind": "ovs-tra-session-rotation-view-report",
        "version": 1,
        "source": {
            "sessionPlan": args.session_plan,
            "baseUrl": args.base_url.rstrip("/"),
        },
        "apply": {
            "dryRun": args.dry_run,
            "rotationView": args.rotation_view,
            "rotationViewLabel": ROTATION_VIEW_LABELS[args.rotation_view],
            "sessionCount": len(session_ids),
            "matchedCount": len(session_ids) - len(mismatches),
            "mismatchCount": len(mismatches),
        },
        "sessions": sessions,
    }
    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote rotation-view report to {args.output}")
    if mismatches and not args.dry_run:
        raise ApiError(
            "RotationView verification failed for sessions: "
            + ", ".join(str(session["sessionID"]) for session in mismatches)
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
