#!/usr/bin/env python3
"""Apply an approved TRA session references plan to an OVS server."""

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
        description="Apply an OVS TRA session references plan."
    )
    parser.add_argument("--base-url", required=True, help="OVS server root URL.")
    parser.add_argument("--plan", required=True, help="Path to the references JSON plan.")
    parser.add_argument("--token", help="Authorization token value.")
    parser.add_argument(
        "--token-file",
        help="File containing the authorization token. Preferred for shared logs.",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("add-proposed", "create-missing-finals", "recreate-proposed"),
        help="Application mode for the approved plan.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print planned mutations without changing OVS.",
    )
    parser.add_argument(
        "--output",
        help="Write the applied or updated plan to this JSON file.",
    )
    parser.add_argument(
        "--final-kind-name",
        default="Final1",
        help="StageKinds constant name to use for created final stages.",
    )
    parser.add_argument(
        "--final-performance-frames-limit",
        type=int,
        default=1,
        help="PerfomanceFramesLimit to patch on created final stages.",
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
    if not isinstance(data, dict):
        raise SystemExit("Plan must be a JSON object.")
    if data.get("kind") != "ovs-tra-session-refs-plan":
        raise SystemExit("Plan kind must be 'ovs-tra-session-refs-plan'.")
    if not isinstance(data.get("refs"), list):
        raise SystemExit("Plan must contain a 'refs' array.")
    return data


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
        raise ApiError("Create request did not return a Location header.")
    tail = location.rstrip("/").split("/")[-1]
    try:
        return int(tail)
    except ValueError as exc:
        raise ApiError(f"Could not extract resource ID from Location: {location}") from exc


def stage_kind_value(api_ai: dict[str, Any], name: str) -> int:
    constants = api_ai.get("constants") or api_ai.get("model", {}).get("constants") or []
    for constant in constants:
        if constant.get("id") != "StageKinds":
            continue
        for value in constant.get("values", []):
            if value.get("name") == name:
                return int(value["value"])
    raise SystemExit(f"StageKinds constant {name!r} was not found in /api/ai.")


def grouped_missing_finals(plan: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    missing = (
        plan.get("userDecisionRequired", {})
        .get("missingFinals", {})
        .get("items", [])
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for item in missing:
        competition_id = item.get("competitionID")
        if competition_id is None:
            continue
        grouped.setdefault(int(competition_id), []).append(item)
    return grouped


def first_group_for_stage(base_url: str, token: str, stage_id: int) -> int:
    stage, _ = request_json(
        base_url,
        f"/api/stages/{stage_id}?fetch_stage_groups=true",
        token,
    )
    groups = stage.get("Stages", {}).get(str(stage_id), {}).get("Groups")
    if groups is None:
        groups = stage.get("Groups")
    if not groups:
        raise ApiError(f"Created final stage {stage_id} has no groups after refetch.")
    return int(groups[0])


def mode_create_missing_finals(
    args: argparse.Namespace, token: str, plan: dict[str, Any]
) -> dict[str, Any]:
    grouped = grouped_missing_finals(plan)
    print(f"Missing-final competitions: {len(grouped)}")
    if not grouped:
        return plan | {"apply": {"mode": args.mode, "createdFinalStages": []}}

    api_ai, _ = request_json(args.base_url, "/api/ai", token)
    final_kind = stage_kind_value(api_ai if isinstance(api_ai, dict) else {}, args.final_kind_name)

    for competition_id, items in sorted(grouped.items()):
        title = items[0].get("competitionTitle", "")
        print(
            f"{'Would create' if args.dry_run else 'Creating'} final stage "
            f"for competitionID={competition_id} {title!r} items={len(items)}"
        )

    if args.dry_run:
        return plan | {
            "apply": {
                "mode": args.mode,
                "dryRun": True,
                "finalKindName": args.final_kind_name,
                "finalKind": final_kind,
                "finalPerformanceFramesLimit": args.final_performance_frames_limit,
                "createdFinalStages": [],
            }
        }

    updated = json.loads(json.dumps(plan))
    missing_container = updated.setdefault("userDecisionRequired", {}).setdefault(
        "missingFinals", {}
    )
    missing_items = missing_container.get("items", [])
    created_final_stages: list[dict[str, Any]] = []
    refs = updated.setdefault("refs", [])

    by_competition = grouped_missing_finals(updated)
    for competition_id, items in sorted(by_competition.items()):
        _, headers = request_json(
            args.base_url, "/api/stages/", token, "POST", {"ParentID": competition_id}
        )
        stage_id = extract_created_id(headers.get("Location"))
        patch = {
            "Kind": final_kind,
            "PerfomanceFramesLimit": args.final_performance_frames_limit,
        }
        request_json(args.base_url, f"/api/stages/{stage_id}", token, "PATCH", patch)
        group_id = first_group_for_stage(args.base_url, token, stage_id)
        created_final_stages.append(
            {
                "competitionID": competition_id,
                "competitionTitle": items[0].get("competitionTitle", ""),
                "stageID": stage_id,
                "stageKind": final_kind,
                "stageKindName": args.final_kind_name,
                "groupID": group_id,
                "items": [item.get("raw") for item in items],
            }
        )
        print(
            f"Created final stage {stage_id} group {group_id} "
            f"for competitionID={competition_id}"
        )
        for item in items:
            refs.append(
                {
                    **{
                        k: item.get(k)
                        for k in (
                            "sessionID",
                            "sessionNumber",
                            "sessionTime",
                            "sessionTitle",
                            "sourceLabel",
                            "sourceOrder",
                            "raw",
                            "parsedCompetitionTitle",
                            "competitionMatchScore",
                            "competitionMatchMethod",
                            "competitionID",
                            "competitionTitle",
                        )
                    },
                    "status": "proposed",
                    "confidence": "medium",
                    "stageID": stage_id,
                    "stageKind": final_kind,
                    "stagePerfomanceFramesLimit": args.final_performance_frames_limit,
                    "stageGroups": [group_id],
                    "GroupID": group_id,
                    "GroupFrame": 0,
                    "groupSelectionMode": "created-final-stage-first-group",
                    "groupSelectionIndex": 0,
                    "mappingMode": "created-missing-final-stage",
                    "notes": [
                        "Created by apply_session_references_plan.py mode=create-missing-finals.",
                        "Review before adding session references.",
                    ],
                }
            )

    created_competitions = {entry["competitionID"] for entry in created_final_stages}
    missing_container["items"] = [
        item
        for item in missing_items
        if int(item.get("competitionID", -1)) not in created_competitions
    ]
    missing_container["count"] = len(missing_container["items"])

    updated["apply"] = {
        "mode": args.mode,
        "dryRun": False,
        "finalKindName": args.final_kind_name,
        "finalKind": final_kind,
        "finalPerformanceFramesLimit": args.final_performance_frames_limit,
        "createdFinalStages": created_final_stages,
    }
    refresh_summary(updated)
    return updated


def mode_add_proposed(
    args: argparse.Namespace, token: str, plan: dict[str, Any]
) -> dict[str, Any]:
    refs = [ref for ref in plan.get("refs", []) if ref.get("status") == "proposed"]
    existing = existing_session_references(args.base_url, token)
    new_refs = [
        ref
        for ref in refs
        if (int(ref["sessionID"]), int(ref["GroupID"]), int(ref["GroupFrame"]))
        not in existing
    ]
    skipped_existing = [
        ref
        for ref in refs
        if (int(ref["sessionID"]), int(ref["GroupID"]), int(ref["GroupFrame"]))
        in existing
    ]
    print(
        f"{'Would add' if args.dry_run else 'Adding'} {len(new_refs)} "
        f"new proposed references; skipping {len(skipped_existing)} already present."
    )
    applied: list[dict[str, Any]] = []
    if not args.dry_run:
        for idx, ref in enumerate(new_refs, start=1):
            body = {"GroupID": ref["GroupID"], "GroupFrame": ref["GroupFrame"]}
            request_json(
                args.base_url,
                f"/api/sessions/{ref['sessionID']}/addRef",
                token,
                "POST",
                body,
            )
            result = dict(ref)
            result["appliedOrder"] = idx
            applied.append(result)
            print(
                f"Added {idx:03d}/{len(new_refs)} session={ref['sessionID']} "
                f"group={ref['GroupID']} frame={ref['GroupFrame']} {ref['raw']}"
            )
    updated = dict(plan)
    updated["apply"] = {
        "mode": args.mode,
        "dryRun": args.dry_run,
        "proposedReferences": len(refs),
        "skippedExistingReferences": len(skipped_existing),
        "newReferences": len(new_refs),
        "addedReferences": len(applied),
    }
    updated["appliedRefs"] = applied
    updated["skippedExistingRefs"] = skipped_existing
    return updated


def mode_recreate_proposed(
    args: argparse.Namespace, token: str, plan: dict[str, Any]
) -> dict[str, Any]:
    refs = ordered_proposed_references(plan)
    existing = sorted(existing_session_references(args.base_url, token))
    print(
        f"{'Would recreate' if args.dry_run else 'Recreating'} references: "
        f"remove {len(existing)} existing, add {len(refs)} proposed."
    )
    removed: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    if not args.dry_run:
        for session_id, group_id, group_frame in existing:
            body = {"GroupID": group_id, "GroupFrame": group_frame}
            request_json(
                args.base_url,
                f"/api/sessions/{session_id}/removeRef",
                token,
                "POST",
                body,
            )
            removed.append(
                {
                    "sessionID": session_id,
                    "GroupID": group_id,
                    "GroupFrame": group_frame,
                }
            )
        for idx, ref in enumerate(refs, start=1):
            body = {"GroupID": ref["GroupID"], "GroupFrame": ref["GroupFrame"]}
            request_json(
                args.base_url,
                f"/api/sessions/{ref['sessionID']}/addRef",
                token,
                "POST",
                body,
            )
            result = dict(ref)
            result["appliedOrder"] = idx
            applied.append(result)
            print(
                f"Added {idx:03d}/{len(refs)} session={ref['sessionID']} "
                f"group={ref['GroupID']} frame={ref['GroupFrame']} {ref['raw']}"
            )
    updated = dict(plan)
    updated["apply"] = {
        "mode": args.mode,
        "dryRun": args.dry_run,
        "removedExistingReferences": len(removed),
        "proposedReferences": len(refs),
        "addedReferences": len(applied),
        "ordering": "group-first within each session competition/stage block",
    }
    updated["removedRefs"] = removed
    updated["appliedRefs"] = applied
    return updated


def ordered_proposed_references(plan: dict[str, Any]) -> list[dict[str, Any]]:
    refs = [ref for ref in plan.get("refs", []) if ref.get("status") == "proposed"]
    by_session: dict[int, list[dict[str, Any]]] = {}
    for ref in refs:
        by_session.setdefault(int(ref["sessionID"]), []).append(ref)

    ordered: list[dict[str, Any]] = []
    for session_id in sorted(by_session):
        session_refs = by_session[session_id]
        block_order: dict[tuple[int, int], int] = {}
        for ref in session_refs:
            key = (int(ref.get("competitionID") or -1), int(ref.get("stageID") or -1))
            block_order[key] = min(block_order.get(key, 10**9), int(ref.get("sourceOrder") or 0))

        def sort_key(ref: dict[str, Any]) -> tuple[int, int, int, int, int]:
            block = (int(ref.get("competitionID") or -1), int(ref.get("stageID") or -1))
            return (
                block_order[block],
                int(ref.get("stageID") or -1),
                int(ref.get("groupSelectionIndex") or 0),
                int(ref.get("GroupID") or -1),
                int(ref.get("GroupFrame") or 0),
            )

        ordered.extend(sorted(session_refs, key=sort_key))
    return ordered


def existing_session_references(base_url: str, token: str) -> set[tuple[int, int, int]]:
    event, _ = request_json(
        base_url,
        "/api/event?fetch_event_sessions=true&fetch_session_groups=true&fetch_session_frames=true",
        token,
    )
    sessions = event.get("Sessions", {}) if isinstance(event, dict) else {}
    existing: set[tuple[int, int, int]] = set()
    for session_id, session in sessions.items():
        groups = session.get("Groups") or []
        frames = session.get("GroupFrame") or []
        for group_id, group_frame in zip(groups, frames):
            existing.add((int(session_id), int(group_id), int(group_frame)))
    return existing


def refresh_summary(plan: dict[str, Any]) -> None:
    status_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    for ref in plan.get("refs", []):
        status = str(ref.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        mode = str(ref.get("mappingMode", "unknown"))
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
    missing = (
        plan.get("userDecisionRequired", {})
        .get("missingFinals", {})
        .get("items", [])
    )
    unmatched = plan.get("userDecisionRequired", {}).get("unmatched", [])
    if missing:
        status_counts["blocked-missing-final"] = len(missing)
    if unmatched:
        status_counts["unmatched"] = len(unmatched)
    summary = plan.setdefault("summary", {})
    summary["refsToAddIfApproved"] = len(plan.get("refs", []))
    summary["unresolvedItems"] = len(missing) + len(unmatched)
    summary["unmatchedItems"] = len(unmatched)
    summary["statusCounts"] = status_counts
    summary["mappingModeCounts"] = mode_counts
    summary["missingFinalDecisionCount"] = len(missing)


def main() -> int:
    args = parse_args()
    token = read_token(args)
    plan = load_plan(args.plan)
    if args.mode == "create-missing-finals":
        updated = mode_create_missing_finals(args, token, plan)
    elif args.mode == "add-proposed":
        updated = mode_add_proposed(args, token, plan)
    elif args.mode == "recreate-proposed":
        updated = mode_recreate_proposed(args, token, plan)
    else:
        raise SystemExit(f"Unsupported mode: {args.mode}")

    if args.output:
        Path(args.output).write_text(
            json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote plan to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
