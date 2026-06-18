#!/usr/bin/env python3
"""Build a draft TRA session plan from simple DOCX schedule tables.

Human-authored schedules are not a stable machine format. The output must be
visually checked against the source document and approved before application.
"""

from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from plan_table import write_rows


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SESSION_RE = re.compile(
    r"session\s+(\d+),\s*([A-Za-z]{3})\s+(\d+)(?:st|nd|rd|th)\s+([A-Za-z]+)",
    re.IGNORECASE,
)
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
NON_COMPETITION_RE = re.compile(
    r"\b(no competition|training(?: hall)? access|break|"
    r"(?:males|females|athletes?) move)\b",
    re.IGNORECASE,
)
COMPETITION_MARKER_RE = re.compile(r"\b(flight\s+\d+|final)\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract TRA schedule rows from DOCX tables into a draft TSV plan."
    )
    parser.add_argument("--source", required=True, help="Source DOCX schedule.")
    parser.add_argument("--output", required=True, help="Output canonical TSV plan.")
    parser.add_argument("--year", type=int, required=True, help="Schedule year.")
    parser.add_argument(
        "--numbering",
        choices=("day-coded", "sequential"),
        default="day-coded",
        help="OVS session numbering scheme.",
    )
    parser.add_argument("--server", help="Target OVS server URL recorded in metadata.")
    return parser.parse_args()


def text_content(node: ET.Element) -> str:
    paragraphs: list[str] = []
    for paragraph in node.findall(f".//{W}p"):
        parts: list[str] = []
        for part in paragraph.iter():
            if part.tag == f"{W}t":
                parts.append(part.text or "")
            elif part.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
            elif part.tag == f"{W}tab":
                parts.append("\t")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def table_rows(source: Path) -> list[list[list[str]]]:
    with zipfile.ZipFile(source) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))

    tables: list[list[list[str]]] = []
    for table in root.findall(f".//{W}tbl"):
        rows: list[list[str]] = []
        for row in table.findall(f"./{W}tr"):
            cells: list[str] = []
            for cell in row.findall(f"./{W}tc"):
                span_node = cell.find(f"./{W}tcPr/{W}gridSpan")
                span = int(span_node.get(f"{W}val", "1")) if span_node is not None else 1
                cells.extend([text_content(cell)] * span)
            rows.append(cells)
        tables.append(rows)
    return tables


def parse_session_label(label: str, year: int) -> dict[str, Any] | None:
    match = SESSION_RE.search(label)
    if not match:
        return None
    source_number = int(match.group(1))
    weekday = match.group(2).title()
    day = int(match.group(3))
    month_name = match.group(4).lower()
    month = MONTHS.get(month_name)
    if month is None:
        raise SystemExit(f"Unsupported month in session label: {label}")
    date = datetime(year, month, day)
    return {
        "sourceSessionNumber": source_number,
        "weekday": weekday,
        "day": day,
        "month": month,
        "date": date.strftime("%Y-%m-%d"),
        "timeLabel": f"{weekday} {day} {date.strftime('%b')}",
    }


def classify_lines(cell_text: str) -> tuple[list[dict[str, str]], list[str]]:
    items: list[dict[str, str]] = []
    ignored: list[str] = []
    for line in (part.strip() for part in cell_text.splitlines()):
        if not line:
            continue
        if NON_COMPETITION_RE.search(line) and not COMPETITION_MARKER_RE.search(line):
            ignored.append(line)
        else:
            items.append({"raw": line})
    return items, ignored


def build_plan(args: argparse.Namespace) -> tuple[list[dict[str, Any]], int, int]:
    source = Path(args.source)
    sessions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    day_indexes: dict[str, int] = {}
    sequential_number = 0

    for table_index, rows in enumerate(table_rows(source)):
        if len(rows) < 3:
            continue
        headers = rows[1]
        for row_index, row in enumerate(rows[2:], start=2):
            if not row:
                continue
            label = row[0].strip()
            parsed = parse_session_label(label, args.year)
            if parsed is None:
                continue
            date = parsed["date"]
            if date not in day_indexes:
                day_indexes[date] = len(day_indexes) + 1
            day_index = day_indexes[date]
            if args.numbering == "day-coded":
                number = day_index * 100 + parsed["sourceSessionNumber"]
            else:
                sequential_number += 1
                number = sequential_number

            width = max(len(headers), len(row))
            for column_index in range(1, width):
                title = (
                    headers[column_index].strip()
                    if column_index < len(headers)
                    else f"COLUMN {column_index}"
                )
                cell_text = row[column_index].strip() if column_index < len(row) else ""
                items, ignored = classify_lines(cell_text)
                if not items:
                    skipped.append(
                        {
                            "sourceLabel": label,
                            "sourceTable": table_index,
                            "sourceRow": row_index,
                            "column": title,
                            "raw": cell_text,
                            "reason": "empty" if not cell_text else "non-competition",
                        }
                    )
                    continue
                sessions.append(
                    {
                        "sourceLabel": label,
                        "sourceTable": table_index,
                        "sourceRow": row_index,
                        "sourceSessionNumber": parsed["sourceSessionNumber"],
                        "dayIndex": day_index,
                        "date": date,
                        "column": title,
                        "Number": number,
                        "Time": parsed["timeLabel"],
                        "SessionTitle": title,
                        "sourceCell": cell_text,
                        "items": items,
                        "ignoredItems": ignored,
                        "unmatched": [],
                    }
                )

    common = {
        "PlanKind": "ovs-session-plan",
        "Version": 2,
        "Mode": "create",
        "PlanStatus": "draft",
    }
    plan_rows = []
    for session in sessions:
        source_metadata = {
            key: value
            for key, value in session.items()
            if key
            not in {
                "Number",
                "Time",
                "SessionTitle",
                "items",
                "ignoredItems",
            }
        }
        plan_rows.append(
            {
                **common,
                "RowType": "session",
                "SessionID": "",
                "Field:Number": session["Number"],
                "Field:Time": session["Time"],
                "Field:SessionTitle": session["SessionTitle"],
                "Source.items": [item["raw"] for item in session["items"]],
                "Source.IgnoredItems": session["ignoredItems"],
                "Source": source_metadata,
                "Details": {
                    "reviewStatus": "draft-extraction",
                    "reviewRequired": True,
                },
            }
        )
    for item in skipped:
        plan_rows.append(
            {
                **common,
                "RowType": "skipped",
                "Source": item,
                "Details": {"reviewStatus": "draft-extraction"},
            }
        )
    return plan_rows, len(sessions), len(skipped)


def main() -> int:
    args = parse_args()
    rows, session_count, skipped_count = build_plan(args)
    write_rows(args.output, rows)
    print(
        f"Wrote {session_count} sessions and {skipped_count} skipped cells "
        f"to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
