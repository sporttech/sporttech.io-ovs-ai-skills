from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "tra" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from ovs_plan_utils import ApiError  # noqa: E402
from plan_table import (  # noqa: E402
    load_refs_plan,
    load_session_plan,
    write_refs_plan,
    write_rows,
    write_session_plan,
)

apply_sessions = importlib.import_module("apply_sessions_plan")
apply_refs = importlib.import_module("apply_session_references_plan")
generate_lists = importlib.import_module("generate_session_start_lists")
inspect_workflow = importlib.import_module("inspect_session_workflow")


def api_ai() -> dict:
    return {
        "constants": [
            {
                "id": "StageKinds",
                "values": [
                    {"name": "Qualification", "value": 0},
                    {"name": "Final1", "value": 8},
                ],
            }
        ],
        "entityTypes": [
            {"id": "sessions"},
            {"id": "stages"},
        ],
        "fieldDocs": [
            {
                "entity": "Session",
                "field": "Number",
                "writeFormat": "Positive integer.",
            },
            {
                "entity": "Session",
                "field": "Time",
                "writeFormat": "Use a plain string.",
            },
            {
                "entity": "Session",
                "field": "SessionTitle",
                "writeFormat": "PATCH as SessionTitle with a plain string.",
            },
            {
                "entity": "Session",
                "field": "RotationView",
                "writeFormat": "PATCH as RotationView; modes 0 through 7.",
            },
            {
                "entity": "Session",
                "field": "Groups",
                "writeFormat": "Use session actions instead of patching.",
            },
            {
                "entity": "Session",
                "field": "ReadOnlyValue",
                "readOnly": True,
                "writeFormat": "Integer.",
            },
            {
                "entity": "Stage",
                "field": "Kind",
                "writeFormat": "Use values from StageKinds.",
            },
            {
                "entity": "Stage",
                "field": "PerfomanceFramesLimit",
                "writeFormat": "PATCH with an integer from 0 to 4.",
            },
        ],
    }


class MockOVS:
    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.competitions = {
            "10": {"ID": 10, "Stages": [20]},
            "11": {"ID": 11, "Stages": []},
        }
        self.stages = {"20": {"ID": 20, "ParentID": 10, "Groups": [200]}}
        self.groups = {
            "200": {"ID": 200, "Performances": [1, 2]},
            "201": {"ID": 201, "Performances": []},
            "202": {"ID": 202, "Performances": [3], "FailGeneration": True},
        }
        self.next_session = 1
        self.next_stage = 21
        self.next_group = 203
        self.mutations: list[tuple[str, str, dict | None]] = []

    def add_session(
        self, session_id: int, groups: list[int] | None = None, frames: list[int] | None = None
    ) -> None:
        self.sessions[str(session_id)] = {
            "ID": session_id,
            "Number": session_id,
            "Time": "",
            "SessionTitle": "",
            "RotationView": 0,
            "Groups": list(groups or []),
            "GroupFrame": [0 for _ in groups or []],
            "Frames": list(frames or []),
        }
        self.next_session = max(self.next_session, session_id + 1)

    def graph(self) -> dict:
        return {
            "Sessions": self.sessions,
            "Competitions": self.competitions,
            "Stages": self.stages,
            "Groups": self.groups,
        }

    def request(
        self,
        _base_url: str,
        raw_path: str,
        _token: str,
        method: str = "GET",
        body: dict | None = None,
    ):
        path = urlparse(raw_path).path
        body = body or {}
        if method != "GET":
            self.mutations.append((method, path, body))
        if method == "GET" and path == "/api/ai":
            return api_ai(), {}
        if method == "GET" and path == "/api/event":
            return self.graph(), {}
        if method == "GET" and path.startswith("/api/stages/"):
            stage_id = path.rstrip("/").split("/")[-1]
            stage = self.stages[stage_id]
            groups = {
                str(group_id): self.groups[str(group_id)]
                for group_id in stage["Groups"]
            }
            return {"Stages": {stage_id: stage}, "Groups": groups}, {}
        if method == "GET" and path.startswith("/api/sessions/"):
            session_id = path.rstrip("/").split("/")[-1]
            session = self.sessions[session_id]
            groups = {
                str(group_id): self.groups[str(group_id)]
                for group_id in session["Groups"]
            }
            return {"Sessions": {session_id: session}, "Groups": groups}, {}
        if method == "POST" and path == "/api/sessions/":
            session_id = self.next_session
            self.add_session(session_id)
            return {}, {"Location": f"/api/sessions/{session_id}"}
        if method == "POST" and path == "/api/stages/":
            stage_id = self.next_stage
            group_id = self.next_group
            self.next_stage += 1
            self.next_group += 1
            self.stages[str(stage_id)] = {
                "ID": stage_id,
                "ParentID": body["ParentID"],
                "Groups": [group_id],
            }
            self.groups[str(group_id)] = {"ID": group_id, "Performances": []}
            self.competitions[str(body["ParentID"])]["Stages"].append(stage_id)
            return {}, {"Location": f"/api/stages/{stage_id}"}
        parts = path.strip("/").split("/")
        if method == "PATCH" and parts[:2] == ["api", "sessions"]:
            self.sessions[parts[2]].update(body)
            return {}, {}
        if method == "PATCH" and parts[:2] == ["api", "stages"]:
            self.stages[parts[2]].update(body)
            return {}, {}
        if method == "POST" and len(parts) == 4 and parts[:2] == ["api", "sessions"]:
            session = self.sessions[parts[2]]
            action = parts[3]
            pair = (body.get("GroupID"), body.get("GroupFrame"))
            if action == "addRef":
                session["Groups"].append(pair[0])
                session["GroupFrame"].append(pair[1])
            elif action == "removeRef":
                pairs = list(zip(session["Groups"], session["GroupFrame"]))
                pairs.remove(pair)
                session["Groups"] = [item[0] for item in pairs]
                session["GroupFrame"] = [item[1] for item in pairs]
            elif action == "generate":
                generated = []
                for group_id in session["Groups"]:
                    group = self.groups[str(group_id)]
                    if group.get("Performances") and not group.get("FailGeneration"):
                        generated.extend(group["Performances"])
                session["Frames"] = generated
            else:
                raise AssertionError(f"Unexpected action: {action}")
            return {}, {}
        raise AssertionError(f"Unexpected request: {method} {raw_path} {body}")


class WorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ovs = MockOVS()
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_main(self, module, *arguments: str, error=None):
        argv = [module.__file__, "--base-url", "http://mock", *arguments, "--token", "test"]
        with mock.patch.object(module, "request_json", self.ovs.request), mock.patch.object(
            sys, "argv", argv
        ):
            if error:
                with self.assertRaises(error):
                    module.main()
                return None
            self.assertEqual(module.main(), 0)

    def test_create_arbitrary_fields_and_reapply_without_duplicates(self) -> None:
        source = self.directory / "sessions.tsv"
        applied = self.directory / "sessions.applied.tsv"
        write_session_plan(
            str(source),
            {
                "mode": "create",
                "status": "approved",
                "sessions": [
                    {
                        "sessionID": None,
                        "fields": {
                            "Number": 102,
                            "Time": "Tue 7 Jul",
                            "SessionTitle": "TRA 1",
                            "RotationView": 4,
                        },
                        "source": {
                            "label": "Session 2",
                            "column": "TRAMPOLINE 1",
                            "date": "2026-07-07",
                            "items": [
                                {"raw": "Flight 1"},
                                {"raw": "FINAL"},
                            ],
                            "ignoredItems": ["BREAK"],
                        },
                    }
                ],
                "skipped": [],
            },
        )
        self.run_main(
            apply_sessions,
            "--plan",
            str(source),
            "--updated-plan",
            str(applied),
        )
        self.assertEqual(len(self.ovs.sessions), 1)
        self.assertEqual(self.ovs.sessions["1"]["RotationView"], 4)
        applied_plan = load_session_plan(str(applied))
        self.assertEqual(applied_plan["sessions"][0]["sessionID"], 1)
        self.assertEqual(
            applied_plan["sessions"][0]["source"],
            {
                "label": "Session 2",
                "column": "TRAMPOLINE 1",
                "date": "2026-07-07",
                "items": ["Flight 1", "FINAL"],
                "ignoredItems": ["BREAK"],
            },
        )
        self.assertEqual(applied_plan["sessions"][0]["details"], {})
        self.run_main(
            apply_sessions,
            "--plan",
            str(applied),
            "--updated-plan",
            str(applied),
        )
        self.assertEqual(len(self.ovs.sessions), 1)

    def test_patch_rejects_unknown_fields_before_mutation(self) -> None:
        self.ovs.add_session(1)
        plan = self.directory / "invalid.tsv"
        write_session_plan(
            str(plan),
            {
                "mode": "patch",
                "status": "approved",
                "sessions": [
                    {
                        "sessionID": 1,
                        "fields": {"ReadOnlyValue": 9},
                        "source": {},
                    }
                ],
                "skipped": [],
            },
        )
        self.run_main(
            apply_sessions, "--plan", str(plan), error=SystemExit
        )
        self.assertEqual(self.ovs.mutations, [])

    def test_session_dry_run_does_not_mutate(self) -> None:
        plan = self.directory / "dry.tsv"
        write_session_plan(
            str(plan),
            {
                "mode": "create",
                "status": "draft",
                "sessions": [
                    {
                        "sessionID": None,
                        "fields": {"Number": 1, "Time": "Day", "SessionTitle": "A"},
                        "source": {},
                    }
                ],
                "skipped": [],
            },
        )
        self.run_main(apply_sessions, "--plan", str(plan), "--dry-run")
        self.assertEqual(self.ovs.mutations, [])
        self.run_main(
            apply_sessions, "--plan", str(plan), error=SystemExit
        )
        self.assertEqual(self.ovs.mutations, [])

    def test_patch_dry_run_reports_expected_change_without_failure(self) -> None:
        self.ovs.add_session(1)
        plan = self.directory / "patch-dry.tsv"
        audit = self.directory / "patch-dry.json"
        write_session_plan(
            str(plan),
            {
                "mode": "patch",
                "status": "approved",
                "sessions": [
                    {
                        "sessionID": 1,
                        "fields": {"RotationView": 3},
                        "source": {},
                    }
                ],
                "skipped": [],
            },
        )
        self.run_main(
            apply_sessions,
            "--plan",
            str(plan),
            "--dry-run",
            "--audit-output",
            str(audit),
        )
        result = json.loads(audit.read_text())
        self.assertEqual(
            result["sessions"][0]["verification"]["status"], "would-change"
        )
        self.assertEqual(self.ovs.sessions["1"]["RotationView"], 0)
        self.assertEqual(self.ovs.mutations, [])

    def test_session_create_requires_updated_plan(self) -> None:
        plan = self.directory / "create.tsv"
        write_session_plan(
            str(plan),
            {
                "mode": "create",
                "status": "approved",
                "sessions": [
                    {
                        "sessionID": None,
                        "fields": {"Number": 1, "Time": "Day", "SessionTitle": "A"},
                        "source": {},
                        "details": {"reviewer": "operator"},
                    }
                ],
                "skipped": [],
            },
        )
        loaded = load_session_plan(str(plan))
        self.assertEqual(loaded["sessions"][0]["details"], {"reviewer": "operator"})
        self.run_main(apply_sessions, "--plan", str(plan), error=SystemExit)
        self.assertEqual(self.ovs.mutations, [])

    def test_declarative_stage_creation_and_scoped_recreate(self) -> None:
        self.ovs.add_session(1, [200])
        self.ovs.sessions["1"]["GroupFrame"] = [9]
        self.ovs.add_session(2, [200])
        self.ovs.sessions["2"]["GroupFrame"] = [0]
        source = self.directory / "refs.tsv"
        applied = self.directory / "refs.applied.tsv"
        write_refs_plan(
            str(source),
            {
                "mode": "recreate",
                "status": "approved",
                "stageCreates": [
                    {
                        "competitionID": 10,
                        "stageID": None,
                        "groupIDs": [],
                        "stageKind": "Final1",
                        "fields": {"PerfomanceFramesLimit": 2},
                        "source": {"raw": "FINAL"},
                    }
                ],
                "refs": [
                    {
                        "sessionID": 1,
                        "targetCompetitionID": 10,
                        "targetStageKind": "Final1",
                        "groupIndex": 0,
                        "GroupFrame": 0,
                        "source": {"raw": "Exercise 1"},
                    },
                    {
                        "sessionID": 1,
                        "targetCompetitionID": 10,
                        "targetStageKind": "Final1",
                        "groupIndex": 0,
                        "GroupFrame": 1,
                        "source": {"raw": "Exercise 2"},
                    },
                ],
                "ambiguous": [{"source": {"raw": "Maybe"}, "reason": "review"}],
                "unmatched": [],
                "skipped": [],
            },
        )
        self.run_main(
            apply_refs,
            "--plan",
            str(source),
            "--updated-plan",
            str(applied),
        )
        plan = load_refs_plan(str(applied))
        created = plan["stageCreates"][0]
        group_id = created["groupIDs"][0]
        self.assertIsNotNone(created["stageID"])
        self.assertEqual(
            list(zip(self.ovs.sessions["1"]["Groups"], self.ovs.sessions["1"]["GroupFrame"])),
            [(group_id, 0), (group_id, 1)],
        )
        self.assertEqual(
            list(zip(self.ovs.sessions["2"]["Groups"], self.ovs.sessions["2"]["GroupFrame"])),
            [(200, 0)],
        )
        self.assertEqual(len(plan["ambiguous"]), 1)
        header = applied.read_text(encoding="utf-8-sig").splitlines()[0].split("\t")
        self.assertIn("CompetitionTitle", header)
        self.assertIn("GroupNumber", header)
        self.assertIn("ExerciseNumber", header)
        self.assertIn("Target", header)
        self.assertNotIn("CompetitionID", header)
        self.assertNotIn("GroupID", header)
        self.assertNotIn("GroupFrame", header)

    def test_stage_create_requires_updated_plan_and_validates_live_identity(self) -> None:
        self.ovs.add_session(1)
        create = self.directory / "create-stage.tsv"
        write_refs_plan(
            str(create),
            {
                "mode": "apply",
                "status": "approved",
                "stageCreates": [
                    {
                        "competitionID": 10,
                        "stageID": None,
                        "groupIDs": [],
                        "stageKind": "Final1",
                        "fields": {"PerfomanceFramesLimit": 2},
                        "source": {},
                        "details": {"reviewer": "operator"},
                    }
                ],
                "refs": [],
                "ambiguous": [],
                "unmatched": [],
                "skipped": [],
            },
        )
        loaded = load_refs_plan(str(create))
        self.assertEqual(
            loaded["stageCreates"][0]["details"], {"reviewer": "operator"}
        )
        self.run_main(apply_refs, "--plan", str(create), error=SystemExit)
        self.assertEqual(self.ovs.mutations, [])

        wrong_parent = self.directory / "wrong-parent.tsv"
        write_refs_plan(
            str(wrong_parent),
            {
                "mode": "apply",
                "status": "approved",
                "stageCreates": [
                    {
                        "competitionID": 11,
                        "stageID": 20,
                        "groupIDs": [200],
                        "stageKind": "Final1",
                        "fields": {"PerfomanceFramesLimit": 2},
                        "source": {},
                    }
                ],
                "refs": [],
                "ambiguous": [],
                "unmatched": [],
                "skipped": [],
            },
        )
        self.run_main(apply_refs, "--plan", str(wrong_parent), error=SystemExit)
        self.assertEqual(self.ovs.mutations, [])

        wrong_groups = self.directory / "wrong-groups.tsv"
        write_refs_plan(
            str(wrong_groups),
            {
                "mode": "apply",
                "status": "approved",
                "stageCreates": [
                    {
                        "competitionID": 10,
                        "stageID": 20,
                        "groupIDs": [201],
                        "stageKind": "Final1",
                        "fields": {"PerfomanceFramesLimit": 2},
                        "source": {},
                    }
                ],
                "refs": [],
                "ambiguous": [],
                "unmatched": [],
                "skipped": [],
            },
        )
        self.run_main(apply_refs, "--plan", str(wrong_groups), error=SystemExit)
        self.assertEqual(self.ovs.mutations, [])

    def test_start_list_statuses_and_real_failure(self) -> None:
        self.ovs.add_session(1)
        self.ovs.add_session(2, [201])
        self.ovs.add_session(3, [200])
        source = self.directory / "start.tsv"
        write_rows(
            str(source),
            [
                {
                    "PlanKind": "ovs-session-start-lists-plan",
                    "Version": 1,
                    "Mode": "create",
                    "PlanStatus": "approved",
                    "RowType": "session",
                    "SessionID": session_id,
                }
                for session_id in (1, 2, 3)
            ],
        )
        audit = self.directory / "start.json"
        self.run_main(
            generate_lists,
            "--plan",
            str(source),
            "--audit-output",
            str(audit),
        )
        statuses = {
            item["sessionID"]: item["status"]
            for item in json.loads(audit.read_text())["sessions"]
        }
        self.assertEqual(
            statuses,
            {1: "no-refs", 2: "refs-without-performances", 3: "generated"},
        )

        self.ovs.add_session(4, [202])
        failure = self.directory / "failure.tsv"
        write_rows(
            str(failure),
            [
                {
                    "PlanKind": "ovs-session-start-lists-plan",
                    "Version": 1,
                    "Mode": "create",
                    "PlanStatus": "approved",
                    "RowType": "session",
                    "SessionID": 4,
                }
            ],
        )
        self.run_main(
            generate_lists,
            "--plan",
            str(failure),
            error=ApiError,
        )

    def test_read_only_inspector_builds_reusable_catalog(self) -> None:
        self.ovs.add_session(1)
        snapshot = self.directory / "inspection.json"
        argv = [
            inspect_workflow.__file__,
            "--base-url",
            "http://mock",
            "--output",
            str(snapshot),
        ]
        with mock.patch.object(
            inspect_workflow, "request_json", self.ovs.request
        ), mock.patch.object(sys, "argv", argv):
            self.assertEqual(inspect_workflow.main(), 0)
        result = json.loads(snapshot.read_text())
        self.assertTrue(result["readOnly"])
        self.assertEqual(result["kind"], "ovs-session-workflow-snapshot")
        self.assertEqual(result["catalog"]["summary"]["sessionCount"], 1)
        self.assertEqual(
            result["catalog"]["relations"]["competitionStages"]["10"], [20]
        )
        self.assertIn("SessionTitle", result["catalog"]["writableFields"]["Session"])
        self.assertEqual(self.ovs.mutations, [])


if __name__ == "__main__":
    unittest.main()
