#!/usr/bin/env python3
"""Read and write canonical TSV plans for the OVS session workflow."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def decode(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def encode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def read_rows(path: str) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, dialect="excel-tab"))
    if not rows:
        raise SystemExit("Plan table must contain at least one data row.")
    required = {"PlanKind", "Version", "Mode", "PlanStatus", "RowType"}
    missing = required - set(rows[0])
    if missing:
        raise SystemExit(f"Plan table is missing columns: {', '.join(sorted(missing))}")
    signatures = {
        (
            row.get("PlanKind"),
            row.get("Version"),
            row.get("Mode"),
            row.get("PlanStatus"),
        )
        for row in rows
    }
    if len(signatures) != 1:
        raise SystemExit(
            "PlanKind, Version, Mode, and PlanStatus must be identical on every row."
        )
    return rows


def field_values(row: dict[str, str], prefix: str) -> dict[str, Any]:
    return {
        name.removeprefix(prefix): decode(value)
        for name, value in row.items()
        if name.startswith(prefix) and value.strip()
    }


def session_source(row: dict[str, str]) -> dict[str, Any]:
    source = decode(row.get("Source", "")) or {}
    if not isinstance(source, dict):
        raise SystemExit("Source must be a JSON object when present.")
    expanded = {
        "items": decode(row.get("Source.items", "")),
        "ignoredItems": decode(row.get("Source.IgnoredItems", "")),
    }
    for key, value in expanded.items():
        if value is not None:
            source[key] = value
    return source


def integer(row: dict[str, str], name: str, required: bool = False) -> int | None:
    raw = (row.get(name) or "").strip()
    if not raw:
        if required:
            raise SystemExit(f"{name} is required for RowType={row.get('RowType')}.")
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {raw!r}.") from exc


def load_session_plan(path: str) -> dict[str, Any]:
    rows = read_rows(path)
    if rows[0]["PlanKind"] != "ovs-session-plan" or rows[0]["Version"] != "2":
        raise SystemExit("Expected an ovs-session-plan version 2 table.")
    sessions = []
    skipped = []
    for row in rows:
        if row["RowType"] == "session":
            sessions.append(
                {
                    "sessionID": integer(row, "SessionID"),
                    "fields": field_values(row, "Field:"),
                    "source": session_source(row),
                    "details": decode(row.get("Details", "")) or {},
                }
            )
        elif row["RowType"] == "skipped":
            skipped.append(
                {
                    "source": decode(row.get("Source", "")) or {},
                    "details": decode(row.get("Details", "")) or {},
                }
            )
        else:
            raise SystemExit(f"Unsupported session RowType: {row['RowType']!r}")
    return {
        "kind": rows[0]["PlanKind"],
        "version": 2,
        "mode": rows[0]["Mode"],
        "status": rows[0]["PlanStatus"],
        "sessions": sessions,
        "skipped": skipped,
        "sourceTable": path,
    }


def load_refs_plan(path: str) -> dict[str, Any]:
    rows = read_rows(path)
    if rows[0]["PlanKind"] != "ovs-session-refs-plan" or rows[0]["Version"] != "2":
        raise SystemExit("Expected an ovs-session-refs-plan version 2 table.")
    plan: dict[str, Any] = {
        "kind": rows[0]["PlanKind"],
        "version": 2,
        "mode": rows[0]["Mode"],
        "status": rows[0]["PlanStatus"],
        "stageCreates": [],
        "refs": [],
        "ambiguous": [],
        "unmatched": [],
        "omitted": [],
        "skipped": [],
        "sourceTable": path,
    }
    for row in rows:
        row_type = row["RowType"]
        source = decode(row.get("Source", "")) or {}
        details = decode(row.get("Details", "")) or {}
        if row_type == "stageCreate":
            target = decode(row.get("Target", "")) or {}
            if not isinstance(target, dict):
                raise SystemExit("Target must be a JSON object when present.")
            plan["stageCreates"].append(
                {
                    "competitionID": (
                        integer(row, "CompetitionID")
                        if (row.get("CompetitionID") or "").strip()
                        else target.get("CompetitionID")
                    ),
                    "stageID": integer(row, "StageID"),
                    "groupIDs": (
                        decode(row.get("GroupIDs", ""))
                        if (row.get("GroupIDs") or "").strip()
                        else target.get("GroupIDs")
                    )
                    or [],
                    "stageKind": (
                        (row.get("StageKind") or "").strip()
                        or target.get("StageKind")
                        or ""
                    ),
                    "fields": field_values(row, "StageField:"),
                    "source": source,
                    "details": details,
                }
            )
        elif row_type == "ref":
            target = decode(row.get("Target", "")) or {}
            if not isinstance(target, dict):
                raise SystemExit("Target must be a JSON object when present.")
            plan["refs"].append(
                {
                    "sessionID": integer(row, "SessionID", True),
                    "GroupID": (
                        integer(row, "GroupID")
                        if (row.get("GroupID") or "").strip()
                        else target.get("GroupID")
                    ),
                    "targetCompetitionID": (
                        integer(row, "TargetCompetitionID")
                        if (row.get("TargetCompetitionID") or "").strip()
                        else target.get("CompetitionID")
                    ),
                    "targetStageKind": (
                        (row.get("TargetStageKind") or "").strip()
                        or target.get("StageKind")
                        or None
                    ),
                    "groupIndex": (
                        integer(row, "GroupIndex")
                        if (row.get("GroupIndex") or "").strip()
                        else target.get("GroupIndex")
                    ),
                    "GroupFrame": (
                        integer(row, "GroupFrame")
                        if (row.get("GroupFrame") or "").strip()
                        else (
                            int(target["GroupFrame"])
                            if target.get("GroupFrame") is not None
                            else integer(row, "ExerciseNumber", True) - 1
                        )
                    ),
                    "expectedExerciseCount": integer(
                        row, "ExpectedExerciseCount", True
                    ),
                    "source": source,
                    **details,
                }
            )
        elif row_type == "omitted":
            target = decode(row.get("Target", "")) or {}
            if not isinstance(target, dict):
                raise SystemExit("Target must be a JSON object when present.")
            plan["omitted"].append(
                {
                    "sessionID": integer(row, "SessionID", True),
                    "GroupID": (
                        integer(row, "GroupID")
                        if (row.get("GroupID") or "").strip()
                        else target.get("GroupID")
                    ),
                    "targetCompetitionID": (
                        integer(row, "TargetCompetitionID")
                        if (row.get("TargetCompetitionID") or "").strip()
                        else target.get("CompetitionID")
                    ),
                    "targetStageKind": (
                        (row.get("TargetStageKind") or "").strip()
                        or target.get("StageKind")
                        or None
                    ),
                    "groupIndex": (
                        integer(row, "GroupIndex")
                        if (row.get("GroupIndex") or "").strip()
                        else target.get("GroupIndex")
                    ),
                    "GroupFrame": (
                        integer(row, "GroupFrame")
                        if (row.get("GroupFrame") or "").strip()
                        else (
                            int(target["GroupFrame"])
                            if target.get("GroupFrame") is not None
                            else integer(row, "ExerciseNumber", True) - 1
                        )
                    ),
                    "expectedExerciseCount": integer(
                        row, "ExpectedExerciseCount", True
                    ),
                    "source": source,
                    **details,
                }
            )
        elif row_type in {"ambiguous", "unmatched", "skipped"}:
            plan[row_type].append({"source": source, **details})
        else:
            raise SystemExit(f"Unsupported refs RowType: {row_type!r}")
    return plan


def load_start_lists_plan(path: str) -> dict[str, Any]:
    rows = read_rows(path)
    if rows[0]["PlanKind"] != "ovs-session-start-lists-plan" or rows[0]["Version"] != "1":
        raise SystemExit("Expected an ovs-session-start-lists-plan version 1 table.")
    sessions = []
    omitted = []
    for row in rows:
        if row["RowType"] == "session":
            sessions.append(
                {
                    "sessionID": integer(row, "SessionID", True),
                    "fields": field_values(row, "Field:"),
                }
            )
        elif row["RowType"] == "omitted":
            details = decode(row.get("Details", "")) or {}
            if not isinstance(details, dict):
                raise SystemExit("Details must be a JSON object for RowType=omitted.")
            reason = str(details.get("reason", "")).strip()
            if not reason:
                raise SystemExit(
                    "Details.reason is required for RowType=omitted."
                )
            omitted.append(
                {
                    "sessionID": integer(row, "SessionID", True),
                    "sessionNumber": integer(row, "SessionNumber"),
                    "sessionTitle": (row.get("SessionTitle") or "").strip(),
                    "source": decode(row.get("Source", "")) or {},
                    "details": details,
                }
            )
        else:
            raise SystemExit(
                "Start-list plans may contain only RowType=session or omitted."
            )
    all_session_ids = [item["sessionID"] for item in sessions] + [
        item["sessionID"] for item in omitted
    ]
    if len(all_session_ids) != len(set(all_session_ids)):
        raise SystemExit(
            "A SessionID may appear only once across session and omitted rows."
        )
    return {
        "kind": rows[0]["PlanKind"],
        "version": 1,
        "mode": rows[0]["Mode"],
        "status": rows[0]["PlanStatus"],
        "sessions": sessions,
        "omitted": omitted,
        "sessionIDs": [item["sessionID"] for item in sessions],
        "sourceTable": path,
    }


def write_rows(path: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("Cannot write an empty plan table.")
    present = {key for row in rows for key in row}
    preferred = [
        "PlanKind",
        "Version",
        "Mode",
        "PlanStatus",
        "RowType",
        "SessionID",
        "SessionNumber",
        "SessionTitle",
        "CompetitionTitle",
        "StageKind",
        "GroupNumber",
        "ExerciseNumber",
        "ExpectedExerciseCount",
    ]
    field_headers = sorted(key for key in present if key.startswith("Field:"))
    source_headers = [
        "Source.items",
        "Source.IgnoredItems",
        "Source",
    ]
    preferred += field_headers
    preferred += [
        "CompetitionID",
        "StageID",
        "GroupIDs",
        "GroupID",
        "TargetCompetitionID",
        "TargetStageKind",
        "GroupIndex",
        "GroupFrame",
        "Target",
    ]
    preferred += sorted(key for key in present if key.startswith("StageField:"))
    preferred += source_headers
    preferred += [
        "Details",
    ]
    headers = [key for key in preferred if key in present]
    headers += sorted(present - set(headers))
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=headers, dialect="excel-tab", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: encode(row.get(key)) for key in headers})


def write_session_plan(path: str, plan: dict[str, Any]) -> None:
    common = {
        "PlanKind": "ovs-session-plan",
        "Version": 2,
        "Mode": plan["mode"],
        "PlanStatus": plan.get("status", "draft"),
    }
    rows = [
        session_row(common, session)
        for session in plan.get("sessions", [])
    ]
    rows.extend(
        {
            **common,
            "RowType": "skipped",
            "Source": item.get("source") or {},
            "Details": item.get("details") or {},
        }
        for item in plan.get("skipped", [])
    )
    write_rows(path, rows)


def session_row(
    common: dict[str, Any], session: dict[str, Any]
) -> dict[str, Any]:
    source = dict(session.get("source") or {})
    items = source.pop("items", None)
    if isinstance(items, list):
        items = [
            item.get("raw") if isinstance(item, dict) and "raw" in item else item
            for item in items
        ]
    ignored_items = source.pop(
        "ignoredItems", source.pop("IgnoredItems", None)
    )
    return {
        **common,
        "RowType": "session",
        "SessionID": session.get("sessionID"),
        **{
            f"Field:{field}": value
            for field, value in (session.get("fields") or {}).items()
        },
        "Source.items": items,
        "Source.IgnoredItems": ignored_items,
        "Source": source,
        "Details": session.get("details") or {},
    }


def write_refs_plan(path: str, plan: dict[str, Any]) -> None:
    common = {
        "PlanKind": "ovs-session-refs-plan",
        "Version": 2,
        "Mode": plan.get("mode", "apply"),
        "PlanStatus": plan.get("status", "draft"),
    }
    rows: list[dict[str, Any]] = []
    technical_source_keys = {
        "competitionID",
        "stageID",
        "qualificationStageID",
        "GroupID",
        "groupID",
    }

    def review_source(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in (item.get("source") or {}).items()
            if key not in technical_source_keys
        }

    for stage in plan.get("stageCreates", []):
        rows.append(
            {
                **common,
                "RowType": "stageCreate",
                "StageID": stage.get("stageID"),
                "StageKind": stage.get("stageKind"),
                **{
                    f"StageField:{field}": value
                    for field, value in (stage.get("fields") or {}).items()
                },
                "Source": review_source(stage),
                "Details": stage.get("details") or {},
                "CompetitionTitle": (stage.get("source") or {}).get(
                    "competitionTitle"
                ),
                "Target": {
                    "CompetitionID": stage.get("competitionID"),
                    "StageKind": stage.get("stageKind"),
                    "GroupIDs": stage.get("groupIDs") or [],
                },
            }
        )
    ref_keys = {
        "sessionID",
        "GroupID",
        "targetCompetitionID",
        "targetStageKind",
        "groupIndex",
        "GroupFrame",
        "expectedExerciseCount",
        "source",
    }
    for ref in plan.get("refs", []):
        rows.append(
            {
                **common,
                "RowType": "ref",
                "SessionID": ref.get("sessionID"),
                "SessionNumber": (ref.get("source") or {}).get("sessionNumber"),
                "SessionTitle": (ref.get("source") or {}).get("sessionTitle"),
                "CompetitionTitle": (ref.get("source") or {}).get(
                    "competitionTitle",
                    (ref.get("source") or {}).get("competitionName"),
                ),
                "StageKind": (ref.get("source") or {}).get("stageKind"),
                "GroupNumber": (ref.get("source") or {}).get("groupNumber"),
                "ExerciseNumber": (
                    int(ref["GroupFrame"]) + 1
                    if ref.get("GroupFrame") is not None
                    else None
                ),
                "ExpectedExerciseCount": ref.get("expectedExerciseCount"),
                "Target": (
                    {"GroupID": ref.get("GroupID")}
                    if ref.get("GroupID") is not None
                    else {
                        "CompetitionID": ref.get("targetCompetitionID"),
                        "StageKind": ref.get("targetStageKind"),
                        "GroupIndex": ref.get("groupIndex"),
                    }
                )
                | {"GroupFrame": ref.get("GroupFrame")},
                "Source": review_source(ref),
                "Details": {
                    key: value for key, value in ref.items() if key not in ref_keys
                },
            }
        )
    omission_keys = {
        "sessionID",
        "GroupID",
        "targetCompetitionID",
        "targetStageKind",
        "groupIndex",
        "GroupFrame",
        "expectedExerciseCount",
        "source",
    }
    for omission in plan.get("omitted", []):
        source = review_source(omission)
        rows.append(
            {
                **common,
                "RowType": "omitted",
                "SessionID": omission.get("sessionID"),
                "SessionNumber": source.get("sessionNumber"),
                "SessionTitle": source.get("sessionTitle"),
                "CompetitionTitle": source.get(
                    "competitionTitle", source.get("competitionName")
                ),
                "StageKind": source.get("stageKind"),
                "GroupNumber": source.get("groupNumber"),
                "ExerciseNumber": (
                    int(omission["GroupFrame"]) + 1
                    if omission.get("GroupFrame") is not None
                    else None
                ),
                "ExpectedExerciseCount": omission.get("expectedExerciseCount"),
                "Target": (
                    {"GroupID": omission.get("GroupID")}
                    if omission.get("GroupID") is not None
                    else {
                        "CompetitionID": omission.get("targetCompetitionID"),
                        "StageKind": omission.get("targetStageKind"),
                        "GroupIndex": omission.get("groupIndex"),
                    }
                )
                | {"GroupFrame": omission.get("GroupFrame")},
                "Source": source,
                "Details": {
                    key: value
                    for key, value in omission.items()
                    if key not in omission_keys
                },
            }
        )
    for category in ("ambiguous", "unmatched", "skipped"):
        for item in plan.get(category, []):
            source = review_source(item)
            rows.append(
                {
                    **common,
                    "RowType": category,
                    "SessionID": source.get("sessionID"),
                    "SessionNumber": source.get("sessionNumber"),
                    "SessionTitle": source.get("sessionTitle"),
                    "CompetitionTitle": source.get(
                        "competitionTitle", source.get("competitionName")
                    ),
                    "StageKind": source.get("stageKind"),
                    "GroupNumber": item.get("candidateGroupNumber"),
                    "ExerciseNumber": item.get("exerciseNumber"),
                    "Source": source,
                    "Details": {
                        key: value for key, value in item.items() if key != "source"
                    },
                }
            )
    write_rows(path, rows)
