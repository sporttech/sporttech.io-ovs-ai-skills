#!/usr/bin/env python3
"""Apply an approved TRA session plan to an OVS server.

This helper intentionally creates and patches sessions only. Session references
to exercises and generated start lists remain separate approval gates.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SESSION_FIELDS = ("Number", "Time", "SessionTitle")


class ApiError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create OVS sessions from an approved JSON plan."
    )
    parser.add_argument("--base-url", required=True, help="OVS server root URL.")
    parser.add_argument("--plan", required=True, help="Path to the approved JSON plan.")
    parser.add_argument("--token", help="Authorization token value.")
    parser.add_argument(
        "--token-file",
        help="File containing the authorization token. Preferred for shared logs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the plan and print what would be created without mutating OVS.",
    )
    parser.add_argument(
        "--allow-nonempty",
        action="store_true",
        help="Allow creating sessions when the event already contains sessions.",
    )
    parser.add_argument(
        "--output",
        help="Write the applied plan with created session IDs to this JSON file.",
    )
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


def load_plan(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"sessions": data}
    if not isinstance(data, dict):
        raise SystemExit("Plan must be a JSON object or a JSON array of sessions.")
    sessions = data.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise SystemExit("Plan must contain a non-empty 'sessions' array.")
    return data


def validate_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    for idx, source in enumerate(plan["sessions"], start=1):
        if not isinstance(source, dict):
            raise SystemExit(f"sessions[{idx}] must be an object.")
        missing = [field for field in SESSION_FIELDS if field not in source]
        if missing:
            raise SystemExit(
                f"sessions[{idx}] is missing required field(s): {', '.join(missing)}"
            )
        try:
            number = int(source["Number"])
        except (TypeError, ValueError):
            raise SystemExit(f"sessions[{idx}].Number must be a positive integer.")
        if number <= 0:
            raise SystemExit(f"sessions[{idx}].Number must be a positive integer.")
        time = str(source["Time"]).strip()
        title = str(source["SessionTitle"]).strip()
        if not time:
            raise SystemExit(f"sessions[{idx}].Time must not be empty.")
        if not title:
            raise SystemExit(f"sessions[{idx}].SessionTitle must not be empty.")
        entry = dict(source)
        entry["Number"] = number
        entry["Time"] = time
        entry["SessionTitle"] = title
        entry["_planIndex"] = idx
        if idx in seen_indexes:
            raise SystemExit(f"Duplicate plan index: {idx}")
        seen_indexes.add(idx)
        validated.append(entry)
    return validated


def url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def request_json(
    base_url: str,
    path: str,
    token: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, str]]:
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url(base_url, path), data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            headers_out = dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise ApiError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"{method} {path} failed: {exc.reason}") from exc

    if not raw:
        return None, headers_out
    try:
        return json.loads(raw.decode("utf-8")), headers_out
    except json.JSONDecodeError:
        return raw.decode("utf-8", "replace"), headers_out


def extract_created_id(location: str | None) -> int:
    if not location:
        raise ApiError("POST /api/sessions/ did not return a Location header.")
    tail = location.rstrip("/").split("/")[-1]
    try:
        return int(tail)
    except ValueError as exc:
        raise ApiError(f"Could not extract session ID from Location: {location}") from exc


def event_sessions(event: dict[str, Any]) -> list[Any]:
    event_obj = event.get("Event", event)
    sessions = event_obj.get("Sessions", [])
    return sessions if isinstance(sessions, list) else []


def print_summary(sessions: list[dict[str, Any]], dry_run: bool) -> None:
    action = "Would create" if dry_run else "Creating"
    print(f"{action} {len(sessions)} sessions:")
    for session in sessions:
        print(
            f"  #{session['_planIndex']:02d} "
            f"Number={session['Number']} "
            f"Time={session['Time']!r} "
            f"SessionTitle={session['SessionTitle']!r}"
        )


def main() -> int:
    args = parse_args()
    token = read_token(args)
    plan = load_plan(args.plan)
    sessions = validate_plan(plan)
    print_summary(sessions, args.dry_run)

    event, _ = request_json(
        args.base_url,
        "/api/event?fetch_event_sessions=true&fetch_session_groups=true&fetch_session_frames=true",
        token,
    )
    existing = event_sessions(event if isinstance(event, dict) else {})
    if existing and not args.allow_nonempty:
        raise SystemExit(
            f"Target event already has {len(existing)} session(s). "
            "Use --allow-nonempty only after confirming this is intentional."
        )

    if args.dry_run:
        print("Dry run complete. No sessions were created.")
        return 0

    created: list[dict[str, Any]] = []
    for session in sessions:
        _, headers = request_json(args.base_url, "/api/sessions/", token, "POST", {})
        session_id = extract_created_id(headers.get("Location"))
        patch = {field: session[field] for field in SESSION_FIELDS}
        request_json(args.base_url, f"/api/sessions/{session_id}", token, "PATCH", patch)
        result = dict(session)
        result["sessionID"] = session_id
        created.append(result)
        print(
            f"Created sessionID={session_id} "
            f"Number={session['Number']} "
            f"Time={session['Time']!r} "
            f"SessionTitle={session['SessionTitle']!r}"
        )

    applied_plan = dict(plan)
    applied_plan["sessions"] = created
    applied_plan["apply"] = {
        "baseUrl": args.base_url.rstrip("/"),
        "createdCount": len(created),
        "script": "skills/tra/scripts/apply_sessions_plan.py",
    }

    output = args.output
    if output:
        Path(output).write_text(
            json.dumps(applied_plan, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote applied plan to {output}")

    verify_event, _ = request_json(
        args.base_url,
        "/api/event?fetch_event_sessions=true&fetch_session_groups=true&fetch_session_frames=true",
        token,
    )
    total = len(event_sessions(verify_event if isinstance(verify_event, dict) else {}))
    print(f"Verified target event now reports {total} session(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
