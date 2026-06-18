#!/usr/bin/env python3
"""Export OVS TRA technical JSON plans as human-readable TSV review tables."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a TRA session workflow JSON artifact as a TSV table."
    )
    parser.add_argument("--plan", required=True, help="Input JSON plan or report.")
    parser.add_argument("--output", required=True, help="Output TSV review table.")
    return parser.parse_args()


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " | ".join(text(item) for item in value)
    return str(value)


def session_rows(plan: dict[str, Any]) -> tuple[list[str], Iterable[list[Any]]]:
    headers = [
        "Plan Row",
        "Status",
        "Source Session",
        "Date",
        "OVS Number",
        "Time",
        "Session Title",
        "Schedule Items",
        "Ignored Items",
        "Session ID",
    ]
    rows = []
    status = plan.get("review", {}).get("status", "draft")
    for index, session in enumerate(plan.get("sessions", []), start=1):
        rows.append(
            [
                index,
                status,
                session.get("sourceLabel"),
                session.get("date"),
                session.get("Number"),
                session.get("Time"),
                session.get("SessionTitle"),
                [item.get("raw") for item in session.get("items", [])],
                session.get("ignoredItems", []),
                session.get("sessionID"),
            ]
        )
    for skipped in plan.get("skipped", []):
        rows.append(
            [
                "",
                f"skipped: {skipped.get('reason', '')}",
                skipped.get("sourceLabel"),
                "",
                "",
                "",
                skipped.get("column"),
                skipped.get("raw"),
                "",
                "",
            ]
        )
    return headers, rows


def ref_row(ref: dict[str, Any], status: str | None = None) -> list[Any]:
    return [
        status or ref.get("status"),
        ref.get("sessionID"),
        ref.get("sessionNumber"),
        ref.get("sessionTime"),
        ref.get("sessionTitle"),
        ref.get("sourceOrder"),
        ref.get("raw"),
        ref.get("competitionTitle") or ref.get("parsedCompetitionTitle"),
        ref.get("competitionID"),
        ref.get("stageID"),
        ref.get("GroupID"),
        ref.get("GroupFrame"),
        ref.get("confidence"),
        ref.get("mappingMode") or ref.get("reason"),
        ref.get("notes") or ref.get("decisionRequired"),
    ]


def refs_rows(plan: dict[str, Any]) -> tuple[list[str], Iterable[list[Any]]]:
    headers = [
        "Status",
        "Session ID",
        "Session Number",
        "Time",
        "Session Title",
        "Source Order",
        "Schedule Text",
        "OVS Competition",
        "Competition ID",
        "Stage ID",
        "Group ID",
        "Exercise Index",
        "Confidence",
        "Mapping / Reason",
        "Notes / Decision",
    ]
    rows = [ref_row(ref) for ref in plan.get("refs", [])]
    decisions = plan.get("userDecisionRequired", {})
    for item in decisions.get("missingFinals", {}).get("items", []):
        rows.append(ref_row(item, "blocked-missing-final"))
    for item in decisions.get("unmatched", []):
        rows.append(ref_row(item, "unmatched"))
    return headers, rows


def start_list_rows(plan: dict[str, Any]) -> tuple[list[str], Iterable[list[Any]]]:
    headers = [
        "Session ID",
        "OVS Number",
        "Time",
        "Session Title",
        "Reference Count",
        "Frames Before",
        "Frames After",
        "Referenced Performances",
        "Status",
    ]
    rows = []
    for session in plan.get("sessions", []):
        rows.append(
            [
                session.get("sessionID"),
                session.get("Number"),
                session.get("Time"),
                session.get("SessionTitle"),
                session.get("referenceCount"),
                session.get("framesBefore"),
                session.get("framesAfter"),
                session.get("referencedPerformanceCount"),
                session.get("status"),
            ]
        )
    return headers, rows


def rotation_view_rows(plan: dict[str, Any]) -> tuple[list[str], Iterable[list[Any]]]:
    headers = [
        "Session ID",
        "OVS Number",
        "Time",
        "Session Title",
        "Rotation View",
        "Status",
    ]
    rows = []
    for session in plan.get("sessions", []):
        rows.append(
            [
                session.get("sessionID"),
                session.get("Number"),
                session.get("Time"),
                session.get("SessionTitle"),
                session.get("RotationView"),
                session.get("status"),
            ]
        )
    return headers, rows


def detect_table(plan: dict[str, Any]) -> tuple[list[str], Iterable[list[Any]]]:
    kind = plan.get("kind")
    if kind == "ovs-tra-session-plan":
        return session_rows(plan)
    if kind == "ovs-tra-session-refs-plan":
        return refs_rows(plan)
    if kind == "ovs-tra-session-start-lists-report":
        return start_list_rows(plan)
    if kind == "ovs-tra-session-rotation-view-report":
        return rotation_view_rows(plan)
    raise SystemExit(f"Unsupported plan kind: {kind!r}")


def main() -> int:
    args = parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    headers, rows = detect_table(plan)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, dialect="excel-tab", lineterminator="\n")
        writer.writerow(headers)
        for row in rows:
            writer.writerow([text(value) for value in row])
            row_count += 1
    print(f"Wrote {row_count} review rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
