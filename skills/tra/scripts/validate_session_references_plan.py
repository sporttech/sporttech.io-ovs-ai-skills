#!/usr/bin/env python3
"""Validate a phase-2 review TSV without contacting OVS."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from plan_table import decode, read_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate an ovs-session-refs-plan v2 review TSV offline."
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--json-output", help="Optional machine-readable report.")
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Return failure when heuristic warnings are present.",
    )
    return parser.parse_args()


def integer_at_least(
    row: dict[str, str],
    name: str,
    row_number: int,
    errors: list[dict[str, Any]],
    minimum: int,
) -> int | None:
    raw = (row.get(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        errors.append(
            {
                "code": "invalid-integer",
                "row": row_number,
                "message": (
                    f"{name} must be an integer >= {minimum}, got {raw!r}."
                ),
            }
        )
        return None
    if value < minimum:
        errors.append(
            {
                "code": "invalid-integer",
                "row": row_number,
                "message": f"{name} must be >= {minimum}, got {value}.",
            }
        )
        return None
    return value


def validate_plan(path: str) -> dict[str, Any]:
    rows = read_rows(path)
    if rows[0]["PlanKind"] != "ovs-session-refs-plan" or rows[0]["Version"] != "2":
        raise SystemExit("Expected an ovs-session-refs-plan version 2 table.")

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    confirmed_exceptions: list[dict[str, Any]] = []
    blocks: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    logical_refs: dict[tuple[int, str, str, int, int], int] = {}
    session_numbers: dict[int, set[int]] = defaultdict(set)
    ref_count = 0

    for row_number, row in enumerate(rows, start=2):
        if row["RowType"] != "ref":
            continue
        ref_count += 1
        session_id = integer_at_least(
            row, "SessionID", row_number, errors, 0
        )
        session_number = integer_at_least(
            row, "SessionNumber", row_number, errors, 1
        )
        group_number = integer_at_least(
            row, "GroupNumber", row_number, errors, 1
        )
        exercise_number = integer_at_least(
            row, "ExerciseNumber", row_number, errors, 1
        )
        competition_title = (row.get("CompetitionTitle") or "").strip()
        stage_kind = (row.get("StageKind") or "").strip()
        for name, value in (
            ("CompetitionTitle", competition_title),
            ("StageKind", stage_kind),
        ):
            if not value:
                errors.append(
                    {
                        "code": "missing-review-field",
                        "row": row_number,
                        "message": f"{name} is required for RowType=ref.",
                    }
                )
        if None in (session_id, session_number, group_number, exercise_number):
            continue
        if not competition_title or not stage_kind:
            continue

        session_numbers[session_id].add(session_number)
        item = {
            "row": row_number,
            "group": group_number,
            "exercise": exercise_number,
        }
        block_key = (session_id, competition_title, stage_kind)
        blocks[block_key].append(item)
        logical_key = (
            session_id,
            competition_title,
            stage_kind,
            group_number,
            exercise_number,
        )
        if logical_key in logical_refs:
            errors.append(
                {
                    "code": "duplicate-ref",
                    "row": row_number,
                    "message": (
                        f"Duplicate ref; first occurrence is row "
                        f"{logical_refs[logical_key]}."
                    ),
                }
            )
        else:
            logical_refs[logical_key] = row_number

        target = decode(row.get("Target", "")) or {}
        if not isinstance(target, dict):
            errors.append(
                {
                    "code": "invalid-target",
                    "row": row_number,
                    "message": "Target must be a JSON object.",
                }
            )
        else:
            group_frame = target.get("GroupFrame")
            if group_frame is not None and group_frame != exercise_number - 1:
                errors.append(
                    {
                        "code": "exercise-target-mismatch",
                        "row": row_number,
                        "message": (
                            f"ExerciseNumber={exercise_number} requires "
                            f"Target.GroupFrame={exercise_number - 1}, got "
                            f"{group_frame!r}."
                        ),
                    }
                )
            group_index = target.get("GroupIndex")
            if group_index is not None and group_index != group_number - 1:
                errors.append(
                    {
                        "code": "group-target-mismatch",
                        "row": row_number,
                        "message": (
                            f"GroupNumber={group_number} requires "
                            f"Target.GroupIndex={group_number - 1}, got "
                            f"{group_index!r}."
                        ),
                    }
                )

        source = decode(row.get("Source", "")) or {}
        details = decode(row.get("Details", "")) or {}
        raw = str(source.get("raw", "")) if isinstance(source, dict) else ""
        mapping_mode = (
            str(details.get("mappingMode", "")) if isinstance(details, dict) else ""
        )
        is_final_to_qualification = (
            stage_kind.casefold() == "qualification"
            and "FINAL" in raw.upper()
        ) or mapping_mode.casefold().startswith("final-to-qualification")
        if is_final_to_qualification:
            explicitly_requested = (
                isinstance(details, dict)
                and details.get("finalInQualificationExplicitlyRequested") is True
            )
            basis = (
                str(details.get("finalMappingBasis", "")).strip()
                if isinstance(details, dict)
                else ""
            )
            if not explicitly_requested or not basis:
                errors.append(
                    {
                        "code": "final-mapped-to-qualification",
                        "row": row_number,
                        "message": (
                            "FINAL must not be mapped to Qualification based on "
                            "PerfomanceFramesLimit, GroupFrame, or the live graph. "
                            "Use an ambiguous row until the user explicitly requests "
                            "this exception, then record both "
                            "Details.finalInQualificationExplicitlyRequested=true "
                            "and a non-empty Details.finalMappingBasis."
                        ),
                    }
                )
            else:
                confirmed_exceptions.append(
                    {
                        "row": row_number,
                        "sessionID": session_id,
                        "competitionTitle": competition_title,
                        "basis": basis,
                    }
                )
        if isinstance(source, dict):
            comparisons = (
                ("groupNumber", group_number, "GroupNumber"),
                ("stageKind", stage_kind, "StageKind"),
                ("competitionTitle", competition_title, "CompetitionTitle"),
                ("sessionNumber", session_number, "SessionNumber"),
            )
            for source_name, visible, visible_name in comparisons:
                source_value = source.get(source_name)
                if source_value is not None and source_value != visible:
                    warnings.append(
                        {
                            "code": "source-review-mismatch",
                            "row": row_number,
                            "message": (
                                f"Source.{source_name}={source_value!r} differs "
                                f"from {visible_name}={visible!r}."
                            ),
                        }
                    )

    for block_key, block in blocks.items():
        actual = [(item["group"], item["exercise"]) for item in block]
        if len({group for group, _ in actual}) < 2:
            continue
        if len({exercise for _, exercise in actual}) < 2:
            continue
        expected = sorted(actual)
        if actual == expected:
            continue
        session_id, competition_title, stage_kind = block_key
        display = lambda values: ", ".join(
            f"G{group}/R{exercise}" for group, exercise in values
        )
        errors.append(
            {
                "code": "noncanonical-order",
                "rows": [item["row"] for item in block],
                "message": (
                    f"SessionID={session_id}, {competition_title}, "
                    f"{stage_kind}: actual [{display(actual)}], expected "
                    f"group-major [{display(expected)}]."
                ),
            }
        )

    for session_id, values in session_numbers.items():
        if len(values) > 1:
            errors.append(
                {
                    "code": "session-number-mismatch",
                    "message": (
                        f"SessionID={session_id} has multiple SessionNumber "
                        f"values: {sorted(values)}."
                    ),
                }
            )

    ref_session_sequence = [
        int(row["SessionID"])
        for row in rows
        if row["RowType"] == "ref" and (row.get("SessionID") or "").isdigit()
    ]
    closed: set[int] = set()
    previous = None
    fragmented: set[int] = set()
    for session_id in ref_session_sequence:
        if session_id != previous:
            if previous is not None:
                closed.add(previous)
            if session_id in closed:
                fragmented.add(session_id)
        previous = session_id
    for session_id in sorted(fragmented):
        warnings.append(
            {
                "code": "fragmented-session-block",
                "message": (
                    f"SessionID={session_id} appears in multiple disjoint row "
                    "blocks. Verify that cross-stage interleaving is intentional."
                ),
            }
        )

    return {
        "kind": "ovs-session-refs-plan-validation",
        "version": 1,
        "plan": str(Path(path)),
        "planStatus": rows[0]["PlanStatus"],
        "summary": {
            "refRows": ref_count,
            "blocks": len(blocks),
            "errors": len(errors),
            "warnings": len(warnings),
            "confirmedFinalQualificationExceptions": len(confirmed_exceptions),
        },
        "errors": errors,
        "warnings": warnings,
        "confirmedFinalQualificationExceptions": confirmed_exceptions,
    }


def validation_error(report: dict[str, Any]) -> str | None:
    errors = report.get("errors") or []
    if not errors:
        return None
    preview = "; ".join(
        f"{item['code']}: {item['message']}" for item in errors[:5]
    )
    remaining = len(errors) - 5
    if remaining > 0:
        preview += f"; and {remaining} more errors"
    return f"Reference plan validation failed: {preview}"


def print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        f"Validated {summary['refRows']} refs in {summary['blocks']} blocks: "
        f"{summary['errors']} errors, {summary['warnings']} warnings, "
        f"{summary['confirmedFinalQualificationExceptions']} confirmed "
        "FINAL-to-Qualification exceptions."
    )
    for severity in ("errors", "warnings"):
        for item in report[severity]:
            location = ""
            if item.get("row"):
                location = f" row {item['row']}:"
            elif item.get("rows"):
                location = f" rows {item['rows']}:"
            print(
                f"{severity[:-1].upper()} {item['code']}{location} "
                f"{item['message']}"
            )
    for item in report["confirmedFinalQualificationExceptions"]:
        print(
            "CONFIRMED final-to-qualification"
            f" row {item['row']}: SessionID={item['sessionID']}, "
            f"{item['competitionTitle']}: {item['basis']}"
        )


def main() -> int:
    args = parse_args()
    report = validate_plan(args.plan)
    print_report(report)
    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if report["errors"] or (args.strict_warnings and report["warnings"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
