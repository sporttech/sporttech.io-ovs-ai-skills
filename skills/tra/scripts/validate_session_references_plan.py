#!/usr/bin/env python3
"""Validate a phase-2 review TSV by running independent validation rules."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from plan_table import decode, read_rows


Finding = dict[str, Any]


@dataclass
class RuleResult:
    rule: str
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "status": "failed" if self.errors else "passed",
            "errors": self.errors,
            "warnings": self.warnings,
            "data": self.data,
        }


@dataclass(frozen=True)
class ValidationContext:
    path: str
    rows: list[dict[str, str]]
    plan_status: str


Rule = Callable[[ValidationContext], RuleResult]


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


def finding(code: str, message: str, **location: Any) -> Finding:
    return {"code": code, **location, "message": message}


def integer(
    row: dict[str, str],
    name: str,
    row_number: int,
    minimum: int,
) -> tuple[int | None, Finding | None]:
    raw = (row.get(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return None, finding(
            "invalid-integer",
            f"{name} must be an integer >= {minimum}, got {raw!r}.",
            row=row_number,
        )
    if value < minimum:
        return None, finding(
            "invalid-integer",
            f"{name} must be >= {minimum}, got {value}.",
            row=row_number,
        )
    return value, None


def json_object(
    row: dict[str, str], name: str
) -> dict[str, Any] | None:
    value = decode(row.get(name, "")) or {}
    return value if isinstance(value, dict) else None


def target_group_identity(row: dict[str, str]) -> tuple[Any, ...] | None:
    target = json_object(row, "Target")
    if target is None:
        return None
    group_id = target.get("GroupID")
    has_group_id = isinstance(group_id, int) and not isinstance(group_id, bool)
    planned_values = (
        target.get("CompetitionID"),
        target.get("StageKind"),
        target.get("GroupIndex"),
    )
    has_planned_target = (
        isinstance(planned_values[0], int)
        and not isinstance(planned_values[0], bool)
        and bool(str(planned_values[1] or "").strip())
        and isinstance(planned_values[2], int)
        and not isinstance(planned_values[2], bool)
    )
    if has_group_id == has_planned_target:
        return None
    if has_group_id:
        return ("group", group_id)
    return ("planned", *planned_values)


def ref_identity(
    row: dict[str, str], row_number: int
) -> tuple[tuple[int, str, str, int, int] | None, list[Finding]]:
    errors: list[Finding] = []
    values: dict[str, int] = {}
    for name, minimum in (
        ("SessionID", 0),
        ("GroupNumber", 1),
        ("ExerciseNumber", 1),
    ):
        value, error = integer(row, name, row_number, minimum)
        if error:
            errors.append(error)
        elif value is not None:
            values[name] = value
    competition_title = (row.get("CompetitionTitle") or "").strip()
    stage_kind = (row.get("StageKind") or "").strip()
    for name, value in (
        ("CompetitionTitle", competition_title),
        ("StageKind", stage_kind),
    ):
        if not value:
            errors.append(
                finding(
                    "missing-review-field",
                    f"{name} is required for RowType={row['RowType']}.",
                    row=row_number,
                )
            )
    if errors:
        return None, errors
    return (
        values["SessionID"],
        competition_title,
        stage_kind,
        values["GroupNumber"],
        values["ExerciseNumber"],
    ), []


def rule_row_types(context: ValidationContext) -> RuleResult:
    result = RuleResult("row-types")
    unresolved_rows: list[dict[str, Any]] = []
    for row_number, row in enumerate(context.rows, start=2):
        row_type = row["RowType"]
        if row_type not in {
            "stageCreate",
            "ref",
            "omitted",
            "ambiguous",
            "unmatched",
            "skipped",
        }:
            result.errors.append(
                finding(
                    "unsupported-row-type",
                    f"Unsupported RowType={row_type!r}.",
                    row=row_number,
                )
            )
            continue
        if row_type not in {"ambiguous", "unmatched"}:
            continue
        source = json_object(row, "Source") or {}
        raw = str(source.get("raw", "")).strip()
        unresolved_rows.append(
            {
                "row": row_number,
                "rowType": row_type,
                "sessionID": (row.get("SessionID") or "").strip() or None,
                "raw": raw,
            }
        )
        target = (
            result.errors if context.plan_status != "draft" else result.warnings
        )
        target.append(
            finding(
                "unresolved-row",
                f"RowType={row_type} is review-only. Resolve it to stageCreate + "
                "ref, omitted, or skipped before approval, dry-run, apply, "
                "adoption, or phase 3.",
                row=row_number,
            )
        )
    result.data["unresolvedRows"] = unresolved_rows
    return result


def rule_ambiguous_rows(context: ValidationContext) -> RuleResult:
    result = RuleResult("ambiguous-row-details")
    for row_number, row in enumerate(context.rows, start=2):
        if row["RowType"] != "ambiguous":
            continue
        source = json_object(row, "Source") or {}
        details = json_object(row, "Details") or {}
        proposed_action = str(details.get("proposedAction", "")).strip()
        if not str(source.get("raw", "")).strip():
            result.warnings.append(
                finding(
                    "ambiguous-missing-source",
                    "An ambiguous row should preserve the original schedule "
                    "text in Source.raw.",
                    row=row_number,
                )
            )
        if proposed_action not in {"stageCreate", "omitted", "skipped"}:
            result.warnings.append(
                finding(
                    "ambiguous-missing-proposal",
                    "Details.proposedAction should be stageCreate, omitted, or "
                    "skipped so the user can approve a concrete outcome.",
                    row=row_number,
                )
            )
        if (
            proposed_action == "stageCreate"
            and not str(details.get("proposedStageKind", "")).strip()
        ):
            result.warnings.append(
                finding(
                    "ambiguous-missing-stage-kind",
                    "A stageCreate proposal requires Details.proposedStageKind.",
                    row=row_number,
                )
            )
        if not str(details.get("proposalBasis", "")).strip():
            result.warnings.append(
                finding(
                    "ambiguous-missing-basis",
                    "Details.proposalBasis should explain the schedule and "
                    "live-graph evidence behind the proposal.",
                    row=row_number,
                )
            )
    return result


def rule_skipped_rows(context: ValidationContext) -> RuleResult:
    result = RuleResult("skipped-row-details")
    for row_number, row in enumerate(context.rows, start=2):
        if row["RowType"] != "skipped":
            continue
        details = json_object(row, "Details") or {}
        if not str(details.get("reason", "")).strip():
            result.errors.append(
                finding(
                    "skipped-missing-reason",
                    "RowType=skipped requires a non-empty Details.reason.",
                    row=row_number,
                )
            )
    return result


def rule_ref_review_fields(context: ValidationContext) -> RuleResult:
    result = RuleResult("ref-review-fields")
    for row_number, row in enumerate(context.rows, start=2):
        if row["RowType"] != "ref":
            continue
        _, errors = ref_identity(row, row_number)
        result.errors.extend(errors)
        _, session_error = integer(row, "SessionNumber", row_number, 1)
        if session_error:
            result.errors.append(session_error)
        _, count_error = integer(
            row, "ExpectedExerciseCount", row_number, 1
        )
        if count_error:
            result.errors.append(count_error)
    return result


def rule_duplicate_refs(context: ValidationContext) -> RuleResult:
    result = RuleResult("duplicate-refs")
    seen: dict[tuple[int, str, str, int, int], int] = {}
    for row_number, row in enumerate(context.rows, start=2):
        if row["RowType"] != "ref":
            continue
        identity, errors = ref_identity(row, row_number)
        if errors or identity is None:
            continue
        if identity in seen:
            result.errors.append(
                finding(
                    "duplicate-ref",
                    f"Duplicate ref; first occurrence is row {seen[identity]}.",
                    row=row_number,
                )
            )
        else:
            seen[identity] = row_number
    return result


def rule_target_indexes(context: ValidationContext) -> RuleResult:
    result = RuleResult("target-indexes")
    for row_number, row in enumerate(context.rows, start=2):
        if row["RowType"] not in {"ref", "omitted"}:
            continue
        exercise_number, exercise_error = integer(
            row, "ExerciseNumber", row_number, 1
        )
        group_number, group_error = integer(
            row, "GroupNumber", row_number, 1
        )
        if exercise_error:
            result.errors.append(exercise_error)
        if group_error:
            result.errors.append(group_error)
        target = json_object(row, "Target")
        if target is None:
            result.errors.append(
                finding(
                    "invalid-target",
                    "Target must be a JSON object.",
                    row=row_number,
                )
            )
            continue
        if target_group_identity(row) is None:
            result.errors.append(
                finding(
                    "invalid-target-identity",
                    "Target must contain exactly one group identity: GroupID, "
                    "or CompetitionID + StageKind + GroupIndex.",
                    row=row_number,
                )
            )
        group_frame = target.get("GroupFrame")
        if (
            exercise_number is not None
            and group_frame is not None
            and group_frame != exercise_number - 1
        ):
            result.errors.append(
                finding(
                    "exercise-target-mismatch",
                    f"ExerciseNumber={exercise_number} requires "
                    f"Target.GroupFrame={exercise_number - 1}, got "
                    f"{group_frame!r}.",
                    row=row_number,
                )
            )
        group_index = target.get("GroupIndex")
        if (
            group_number is not None
            and group_index is not None
            and group_index != group_number - 1
        ):
            result.errors.append(
                finding(
                    "group-target-mismatch",
                    f"GroupNumber={group_number} requires "
                    f"Target.GroupIndex={group_number - 1}, got "
                    f"{group_index!r}.",
                    row=row_number,
                )
            )
    return result


def rule_omitted_exercises(context: ValidationContext) -> RuleResult:
    result = RuleResult("omitted-exercise-details")
    for row_number, row in enumerate(context.rows, start=2):
        if row["RowType"] != "omitted":
            continue
        _, identity_errors = ref_identity(row, row_number)
        result.errors.extend(identity_errors)
        _, session_error = integer(row, "SessionNumber", row_number, 1)
        if session_error:
            result.errors.append(session_error)
        expected_count, count_error = integer(
            row, "ExpectedExerciseCount", row_number, 1
        )
        if count_error:
            result.errors.append(count_error)
        exercise_number, exercise_error = integer(
            row, "ExerciseNumber", row_number, 1
        )
        if (
            expected_count is not None
            and exercise_number is not None
            and exercise_number > expected_count
        ):
            result.errors.append(
                finding(
                    "omitted-exercise-out-of-range",
                    f"ExerciseNumber={exercise_number} exceeds "
                    f"ExpectedExerciseCount={expected_count}.",
                    row=row_number,
                )
            )
        details = json_object(row, "Details") or {}
        if details.get("omittedIntentionally") is not True:
            result.errors.append(
                finding(
                    "omission-not-explicit",
                    "RowType=omitted requires "
                    "Details.omittedIntentionally=true from a direct user "
                    "instruction.",
                    row=row_number,
                )
            )
        if not str(details.get("reason", "")).strip():
            result.errors.append(
                finding(
                    "omission-missing-reason",
                    "RowType=omitted requires a non-empty Details.reason that "
                    "records the user's instruction.",
                    row=row_number,
                )
            )
    return result


def rule_exercise_completeness(context: ValidationContext) -> RuleResult:
    result = RuleResult("exercise-completeness")
    groups: dict[
        tuple[int, str, str, int, tuple[Any, ...]],
        dict[str, Any],
    ] = {}
    for row_number, row in enumerate(context.rows, start=2):
        if row["RowType"] not in {"ref", "omitted"}:
            continue
        identity, errors = ref_identity(row, row_number)
        count, count_error = integer(
            row, "ExpectedExerciseCount", row_number, 1
        )
        if errors or count_error or identity is None or count is None:
            continue
        session_id, competition_title, stage_kind, group_number, exercise = identity
        target_identity = target_group_identity(row)
        if target_identity is None:
            continue
        key = (
            session_id,
            competition_title,
            stage_kind,
            group_number,
            target_identity,
        )
        group = groups.setdefault(
            key,
            {
                "counts": {},
                "refs": {},
                "omitted": {},
            },
        )
        group["counts"].setdefault(count, []).append(row_number)
        bucket = "refs" if row["RowType"] == "ref" else "omitted"
        if exercise in group[bucket]:
            result.errors.append(
                finding(
                    "duplicate-exercise-representation",
                    f"ExerciseNumber={exercise} is represented more than once "
                    f"as RowType={row['RowType']}.",
                    rows=[group[bucket][exercise], row_number],
                )
            )
        else:
            group[bucket][exercise] = row_number

    checked_groups = 0
    for key, group in groups.items():
        (
            session_id,
            competition_title,
            stage_kind,
            group_number,
            _target_identity,
        ) = key
        if not group["refs"]:
            result.errors.append(
                finding(
                    "orphan-omitted-exercise",
                    f"SessionID={session_id}, {competition_title}, {stage_kind}, "
                    f"GroupNumber={group_number} has omitted exercises but no "
                    "included exercise.",
                    rows=sorted(group["omitted"].values()),
                )
            )
            continue
        checked_groups += 1
        if len(group["counts"]) != 1:
            result.errors.append(
                finding(
                    "inconsistent-expected-exercise-count",
                    f"SessionID={session_id}, {competition_title}, {stage_kind}, "
                    f"GroupNumber={group_number} has conflicting "
                    f"ExpectedExerciseCount values: "
                    f"{sorted(group['counts'])}.",
                    rows=sorted(
                        row
                        for rows in group["counts"].values()
                        for row in rows
                    ),
                )
            )
            continue
        expected_count = next(iter(group["counts"]))
        represented = set(group["refs"]) | set(group["omitted"])
        missing = sorted(set(range(1, expected_count + 1)) - represented)
        if missing:
            result.errors.append(
                finding(
                    "missing-group-exercises",
                    f"SessionID={session_id}, {competition_title}, {stage_kind}, "
                    f"GroupNumber={group_number} includes an exercise but is "
                    f"missing exercises {missing}. Add ref rows or explicit "
                    "RowType=omitted rows with "
                    "Details.omittedIntentionally=true.",
                    rows=sorted(group["refs"].values()),
                )
            )
        overlap = sorted(set(group["refs"]) & set(group["omitted"]))
        if overlap:
            result.errors.append(
                finding(
                    "exercise-both-included-and-omitted",
                    f"SessionID={session_id}, {competition_title}, {stage_kind}, "
                    f"GroupNumber={group_number} marks exercises {overlap} as "
                    "both ref and omitted.",
                    rows=sorted(
                        group["refs"][exercise]
                        for exercise in overlap
                    )
                    + sorted(
                        group["omitted"][exercise]
                        for exercise in overlap
                    ),
                )
            )
    result.data["checkedGroups"] = checked_groups
    return result


def rule_final_to_qualification(context: ValidationContext) -> RuleResult:
    result = RuleResult("final-to-qualification")
    confirmed: list[dict[str, Any]] = []
    for row_number, row in enumerate(context.rows, start=2):
        if row["RowType"] != "ref":
            continue
        source = json_object(row, "Source") or {}
        details = json_object(row, "Details") or {}
        raw = str(source.get("raw", ""))
        mapping_mode = str(details.get("mappingMode", ""))
        is_final_to_qualification = (
            (row.get("StageKind") or "").strip().casefold() == "qualification"
            and "FINAL" in raw.upper()
        ) or mapping_mode.casefold().startswith("final-to-qualification")
        if not is_final_to_qualification:
            continue
        explicitly_requested = (
            details.get("finalInQualificationExplicitlyRequested") is True
        )
        basis = str(details.get("finalMappingBasis", "")).strip()
        if not explicitly_requested or not basis:
            result.errors.append(
                finding(
                    "final-mapped-to-qualification",
                    "FINAL must not be mapped to Qualification based on "
                    "PerfomanceFramesLimit, GroupFrame, or the live graph. Use "
                    "an ambiguous row until the user explicitly requests this "
                    "exception, then record both "
                    "Details.finalInQualificationExplicitlyRequested=true and "
                    "a non-empty Details.finalMappingBasis.",
                    row=row_number,
                )
            )
        else:
            session_id, _ = integer(row, "SessionID", row_number, 0)
            confirmed.append(
                {
                    "row": row_number,
                    "sessionID": session_id,
                    "competitionTitle": (
                        row.get("CompetitionTitle") or ""
                    ).strip(),
                    "basis": basis,
                }
            )
    result.data["confirmedExceptions"] = confirmed
    return result


def rule_source_consistency(context: ValidationContext) -> RuleResult:
    result = RuleResult("source-consistency")
    for row_number, row in enumerate(context.rows, start=2):
        if row["RowType"] != "ref":
            continue
        source = json_object(row, "Source")
        if source is None:
            continue
        session_number, _ = integer(row, "SessionNumber", row_number, 1)
        group_number, _ = integer(row, "GroupNumber", row_number, 1)
        comparisons = (
            ("groupNumber", group_number, "GroupNumber"),
            ("stageKind", (row.get("StageKind") or "").strip(), "StageKind"),
            (
                "competitionTitle",
                (row.get("CompetitionTitle") or "").strip(),
                "CompetitionTitle",
            ),
            ("sessionNumber", session_number, "SessionNumber"),
        )
        for source_name, visible, visible_name in comparisons:
            source_value = source.get(source_name)
            if source_value is not None and source_value != visible:
                result.warnings.append(
                    finding(
                        "source-review-mismatch",
                        f"Source.{source_name}={source_value!r} differs from "
                        f"{visible_name}={visible!r}.",
                        row=row_number,
                    )
                )
    return result


def rule_group_major_order(context: ValidationContext) -> RuleResult:
    result = RuleResult("group-major-order")
    blocks: dict[tuple[int, str, str], list[dict[str, int]]] = defaultdict(list)
    for row_number, row in enumerate(context.rows, start=2):
        if row["RowType"] != "ref":
            continue
        identity, errors = ref_identity(row, row_number)
        if errors or identity is None:
            continue
        session_id, competition_title, stage_kind, group, exercise = identity
        blocks[(session_id, competition_title, stage_kind)].append(
            {"row": row_number, "group": group, "exercise": exercise}
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

        def display(values: list[tuple[int, int]]) -> str:
            return ", ".join(
                f"G{group}/R{exercise}" for group, exercise in values
            )

        result.errors.append(
            finding(
                "noncanonical-order",
                f"SessionID={session_id}, {competition_title}, {stage_kind}: "
                f"actual [{display(actual)}], expected group-major "
                f"[{display(expected)}].",
                rows=[item["row"] for item in block],
            )
        )
    result.data["blocks"] = len(blocks)
    return result


def rule_session_numbers(context: ValidationContext) -> RuleResult:
    result = RuleResult("session-number-consistency")
    session_numbers: dict[int, set[int]] = defaultdict(set)
    for row_number, row in enumerate(context.rows, start=2):
        if row["RowType"] not in {"ref", "omitted"}:
            continue
        session_id, session_error = integer(
            row, "SessionID", row_number, 0
        )
        session_number, number_error = integer(
            row, "SessionNumber", row_number, 1
        )
        if session_error or number_error:
            continue
        session_numbers[session_id].add(session_number)
    for session_id, values in session_numbers.items():
        if len(values) > 1:
            result.errors.append(
                finding(
                    "session-number-mismatch",
                    f"SessionID={session_id} has multiple SessionNumber values: "
                    f"{sorted(values)}.",
                )
            )
    return result


def rule_fragmented_sessions(context: ValidationContext) -> RuleResult:
    result = RuleResult("fragmented-session-blocks")
    sequence = [
        int(row["SessionID"])
        for row in context.rows
        if row["RowType"] == "ref"
        and (row.get("SessionID") or "").isdigit()
    ]
    closed: set[int] = set()
    previous = None
    fragmented: set[int] = set()
    for session_id in sequence:
        if session_id != previous:
            if previous is not None:
                closed.add(previous)
            if session_id in closed:
                fragmented.add(session_id)
        previous = session_id
    for session_id in sorted(fragmented):
        result.warnings.append(
            finding(
                "fragmented-session-block",
                f"SessionID={session_id} appears in multiple disjoint row "
                "blocks. Verify that cross-stage interleaving is intentional.",
            )
        )
    return result


RULES: tuple[Rule, ...] = (
    rule_row_types,
    rule_ambiguous_rows,
    rule_skipped_rows,
    rule_ref_review_fields,
    rule_duplicate_refs,
    rule_target_indexes,
    rule_omitted_exercises,
    rule_exercise_completeness,
    rule_final_to_qualification,
    rule_source_consistency,
    rule_group_major_order,
    rule_session_numbers,
    rule_fragmented_sessions,
)


def validate_plan(path: str) -> dict[str, Any]:
    rows = read_rows(path)
    if rows[0]["PlanKind"] != "ovs-session-refs-plan" or rows[0]["Version"] != "2":
        raise SystemExit("Expected an ovs-session-refs-plan version 2 table.")
    context = ValidationContext(
        path=path,
        rows=rows,
        plan_status=rows[0]["PlanStatus"],
    )
    results = [rule(context) for rule in RULES]
    errors = [item for result in results for item in result.errors]
    warnings = [item for result in results for item in result.warnings]
    unresolved_rows = next(
        (
            result.data["unresolvedRows"]
            for result in results
            if result.rule == "row-types"
        ),
        [],
    )
    confirmed_exceptions = next(
        (
            result.data["confirmedExceptions"]
            for result in results
            if result.rule == "final-to-qualification"
        ),
        [],
    )
    ref_count = sum(row["RowType"] == "ref" for row in rows)
    blocks = next(
        (
            result.data["blocks"]
            for result in results
            if result.rule == "group-major-order"
        ),
        0,
    )
    return {
        "kind": "ovs-session-refs-plan-validation",
        "version": 2,
        "plan": str(Path(path)),
        "planStatus": context.plan_status,
        "summary": {
            "refRows": ref_count,
            "blocks": blocks,
            "rules": len(results),
            "failedRules": sum(bool(result.errors) for result in results),
            "errors": len(errors),
            "warnings": len(warnings),
            "confirmedFinalQualificationExceptions": len(confirmed_exceptions),
            "unresolvedRows": len(unresolved_rows),
        },
        "ruleResults": [result.as_dict() for result in results],
        "errors": errors,
        "warnings": warnings,
        "confirmedFinalQualificationExceptions": confirmed_exceptions,
        "unresolvedRows": unresolved_rows,
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
        f"Validated {summary['refRows']} refs in {summary['blocks']} blocks "
        f"with {summary['rules']} rules: {summary['failedRules']} failed rules, "
        f"{summary['errors']} errors, {summary['warnings']} warnings, "
        f"{summary['unresolvedRows']} unresolved rows, "
        f"{summary['confirmedFinalQualificationExceptions']} confirmed "
        "FINAL-to-Qualification exceptions."
    )
    for rule in report["ruleResults"]:
        print(
            f"RULE {rule['rule']}: {rule['status']} "
            f"({len(rule['errors'])} errors, {len(rule['warnings'])} warnings)"
        )
        for severity in ("errors", "warnings"):
            for item in rule[severity]:
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
