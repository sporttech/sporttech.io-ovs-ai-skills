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

from ovs_plan_utils import ApiError, refs_for_session  # noqa: E402
from plan_table import (  # noqa: E402
    load_refs_plan,
    load_session_plan,
    read_rows,
    write_refs_plan,
    write_rows,
    write_session_plan,
)

apply_sessions = importlib.import_module("apply_sessions_plan")
apply_refs = importlib.import_module("apply_session_references_plan")
build_adopted_refs = importlib.import_module(
    "build_adopted_session_references_plan"
)
validate_refs = importlib.import_module("validate_session_references_plan")
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
        self.stages = {
            "20": {
                "ID": 20,
                "ParentID": 10,
                "Groups": [200],
                "PerfomanceFramesLimit": 1,
            }
        }
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
                with self.assertRaises(error) as caught:
                    module.main()
                return caught.exception
            self.assertEqual(module.main(), 0)

    def add_live_stage(
        self,
        stage_id: int,
        competition_id: int,
        group_ids: list[int],
        frames_limit: int = 2,
    ) -> None:
        self.ovs.stages[str(stage_id)] = {
            "ID": stage_id,
            "ParentID": competition_id,
            "Groups": list(group_ids),
            "PerfomanceFramesLimit": frames_limit,
        }
        stages = self.ovs.competitions[str(competition_id)]["Stages"]
        if stage_id not in stages:
            stages.append(stage_id)
        for group_id in group_ids:
            self.ovs.groups.setdefault(
                str(group_id), {"ID": group_id, "Performances": []}
            )
        self.ovs.next_stage = max(self.ovs.next_stage, stage_id + 1)
        self.ovs.next_group = max(self.ovs.next_group, max(group_ids) + 1)

    def write_reference_plan(
        self,
        name: str,
        refs: list[dict],
        mode: str = "recreate",
        stage_creates: list[dict] | None = None,
        status: str = "approved",
        omitted: list[dict] | None = None,
    ) -> Path:
        expected_counts: dict[tuple, int] = {}
        for ref in refs:
            identity = (
                ref.get("GroupID"),
                ref.get("targetCompetitionID"),
                ref.get("targetStageKind"),
                ref.get("groupIndex"),
            )
            expected_counts[identity] = max(
                expected_counts.get(identity, 0),
                int(ref["GroupFrame"]) + 1,
            )
        canonical_refs = []
        for ref in refs:
            item = dict(ref)
            identity = (
                item.get("GroupID"),
                item.get("targetCompetitionID"),
                item.get("targetStageKind"),
                item.get("groupIndex"),
            )
            item.setdefault(
                "expectedExerciseCount", expected_counts[identity]
            )
            source = dict(item.get("source") or {})
            session_id = int(item["sessionID"])
            source.setdefault("sessionNumber", session_id + 100)
            source.setdefault("sessionTitle", f"Session {session_id}")
            if item.get("targetCompetitionID") is not None:
                source.setdefault(
                    "competitionTitle",
                    f"Competition {item['targetCompetitionID']}",
                )
                source.setdefault("stageKind", item["targetStageKind"])
                source.setdefault("groupNumber", int(item["groupIndex"]) + 1)
            else:
                group_id = int(item["GroupID"])
                candidates = [
                    stage
                    for stage in self.ovs.stages.values()
                    if group_id in (stage.get("Groups") or [])
                ]
                if candidates:
                    stage = candidates[0]
                    source.setdefault(
                        "competitionTitle",
                        f"Competition {stage['ParentID']}",
                    )
                    source.setdefault(
                        "groupNumber",
                        list(stage["Groups"]).index(group_id) + 1,
                    )
                else:
                    source.setdefault("competitionTitle", "Competition")
                    source.setdefault("groupNumber", 1)
                source.setdefault("stageKind", "Qualification")
            item["source"] = source
            canonical_refs.append(item)
        path = self.directory / name
        write_refs_plan(
            str(path),
            {
                "mode": mode,
                "status": status,
                "stageCreates": stage_creates or [],
                "refs": canonical_refs,
                "ambiguous": [],
                "unmatched": [],
                "omitted": omitted or [],
                "skipped": [],
            },
        )
        return path

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
                        "expectedExerciseCount": 2,
                        "source": {
                            "raw": "Exercise 1",
                            "sessionNumber": 101,
                            "sessionTitle": "Session 1",
                            "competitionTitle": "Competition 10",
                            "stageKind": "Final1",
                            "groupNumber": 1,
                        },
                    },
                    {
                        "sessionID": 1,
                        "targetCompetitionID": 10,
                        "targetStageKind": "Final1",
                        "groupIndex": 0,
                        "GroupFrame": 1,
                        "expectedExerciseCount": 2,
                        "source": {
                            "raw": "Exercise 2",
                            "sessionNumber": 101,
                            "sessionTitle": "Session 1",
                            "competitionTitle": "Competition 10",
                            "stageKind": "Final1",
                            "groupNumber": 1,
                        },
                    },
                ],
                "ambiguous": [],
                "unmatched": [],
                "skipped": [
                    {
                        "source": {"raw": "Maybe"},
                        "reason": "User approved omitting this schedule item.",
                    }
                ],
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
        self.assertEqual(len(plan["skipped"]), 1)
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

    def test_reference_order_accepts_group_major_and_recreate_applies_it(self) -> None:
        self.add_live_stage(20, 10, [200, 201])
        self.ovs.add_session(1, [200, 201, 200, 201])
        self.ovs.sessions["1"]["GroupFrame"] = [0, 0, 1, 1]
        refs = [
            {"sessionID": 1, "GroupID": group_id, "GroupFrame": group_frame}
            for group_id, group_frame in (
                (200, 0),
                (200, 1),
                (201, 0),
                (201, 1),
            )
        ]
        plan = self.write_reference_plan("group-major.tsv", refs)

        self.run_main(apply_refs, "--plan", str(plan), "--dry-run")
        self.assertEqual(self.ovs.mutations, [])
        self.run_main(apply_refs, "--plan", str(plan))
        self.assertEqual(
            refs_for_session(self.ovs.sessions["1"]),
            [(200, 0), (200, 1), (201, 0), (201, 1)],
        )

    def test_reference_order_rejects_round_major_before_mutation(self) -> None:
        self.add_live_stage(20, 10, [200, 201])
        self.ovs.add_session(1)
        refs = [
            {"sessionID": 1, "GroupID": group_id, "GroupFrame": group_frame}
            for group_id, group_frame in (
                (200, 0),
                (201, 0),
                (200, 1),
                (201, 1),
            )
        ]
        plan = self.write_reference_plan("round-major.tsv", refs)

        error = self.run_main(
            apply_refs, "--plan", str(plan), "--dry-run", error=SystemExit
        )
        self.assertIn("noncanonical-order", str(error))
        self.assertIn("G1/R1, G1/R2, G2/R1, G2/R2", str(error))
        self.assertEqual(self.ovs.mutations, [])

    def test_reference_order_allows_interleaved_stages(self) -> None:
        self.add_live_stage(20, 10, [200, 201])
        self.add_live_stage(21, 11, [202, 203])
        self.ovs.add_session(1)
        refs = [
            {"sessionID": 1, "GroupID": group_id, "GroupFrame": group_frame}
            for group_id, group_frame in (
                (200, 0),
                (202, 0),
                (200, 1),
                (202, 1),
                (201, 0),
                (203, 0),
                (201, 1),
                (203, 1),
            )
        ]
        plan = self.write_reference_plan("interleaved-stages.tsv", refs)

        self.run_main(apply_refs, "--plan", str(plan), "--dry-run")
        self.assertEqual(self.ovs.mutations, [])

    def test_reference_order_validates_new_stage_group_indexes(self) -> None:
        self.ovs.add_session(1)
        stage_create = {
            "competitionID": 11,
            "stageID": None,
            "groupIDs": [],
            "stageKind": "Final1",
            "fields": {"PerfomanceFramesLimit": 2},
            "source": {},
        }
        refs = [
            {
                "sessionID": 1,
                "targetCompetitionID": 11,
                "targetStageKind": "Final1",
                "groupIndex": group_index,
                "GroupFrame": group_frame,
            }
            for group_index, group_frame in ((0, 0), (0, 1), (1, 0), (1, 1))
        ]
        plan = self.write_reference_plan(
            "new-stage-order.tsv", refs, stage_creates=[stage_create]
        )

        self.run_main(apply_refs, "--plan", str(plan), "--dry-run")
        self.assertEqual(self.ovs.mutations, [])

        invalid_refs = [
            {
                "sessionID": 1,
                "targetCompetitionID": 11,
                "targetStageKind": "Final1",
                "groupIndex": group_index,
                "GroupFrame": group_frame,
            }
            for group_index, group_frame in ((0, 0), (1, 0), (0, 1), (1, 1))
        ]
        invalid = self.write_reference_plan(
            "new-stage-round-major.tsv",
            invalid_refs,
            stage_creates=[stage_create],
        )
        error = self.run_main(
            apply_refs, "--plan", str(invalid), "--dry-run", error=SystemExit
        )
        self.assertIn("noncanonical-order", str(error))
        self.assertEqual(self.ovs.mutations, [])

    def test_apply_rejects_projected_noncanonical_order_and_requires_recreate(
        self,
    ) -> None:
        self.add_live_stage(20, 10, [200, 201])
        self.ovs.add_session(1, [200, 201])
        plan = self.write_reference_plan(
            "apply-cannot-reorder.tsv",
            [
                {"sessionID": 1, "GroupID": 200, "GroupFrame": 0},
                {"sessionID": 1, "GroupID": 200, "GroupFrame": 1},
                {"sessionID": 1, "GroupID": 201, "GroupFrame": 0},
                {"sessionID": 1, "GroupID": 201, "GroupFrame": 1},
            ],
            mode="apply",
        )

        error = self.run_main(
            apply_refs, "--plan", str(plan), error=SystemExit
        )
        self.assertIn("Mode=recreate", str(error))
        self.assertEqual(self.ovs.mutations, [])

    def test_reference_order_requires_unique_stage_membership(self) -> None:
        self.add_live_stage(21, 11, [200])
        self.ovs.add_session(1)
        plan = self.write_reference_plan(
            "ambiguous-stage.tsv",
            [{"sessionID": 1, "GroupID": 200, "GroupFrame": 0}],
        )

        error = self.run_main(
            apply_refs, "--plan", str(plan), "--dry-run", error=SystemExit
        )
        self.assertIn("Ask the user", str(error))
        self.assertIn("multiple stages", str(error))
        self.assertEqual(self.ovs.mutations, [])

    def test_offline_reference_validator_runs_after_each_draft_transform(
        self,
    ) -> None:
        base = {
            "PlanKind": "ovs-session-refs-plan",
            "Version": 2,
            "Mode": "recreate",
            "PlanStatus": "draft",
            "RowType": "ref",
            "SessionID": 1,
            "SessionNumber": 101,
            "SessionTitle": "TRA 1",
            "CompetitionTitle": "National 6 TRP Female",
            "StageKind": "Qualification",
            "ExpectedExerciseCount": 2,
        }

        def row(group: int, exercise: int) -> dict:
            return {
                **base,
                "GroupNumber": group,
                "ExerciseNumber": exercise,
                "Target": {
                    "GroupID": 200 + group,
                    "GroupFrame": exercise - 1,
                },
                "Source": {
                    "competitionTitle": base["CompetitionTitle"],
                    "stageKind": base["StageKind"],
                    "groupNumber": group,
                    "sessionNumber": base["SessionNumber"],
                },
            }

        invalid = self.directory / "review-order-invalid.tsv"
        write_rows(
            str(invalid),
            [row(group, exercise) for group, exercise in ((1, 1), (2, 1), (1, 2), (2, 2))],
        )
        invalid_report = validate_refs.validate_plan(str(invalid))
        self.assertEqual(invalid_report["summary"]["errors"], 1)
        self.assertEqual(
            invalid_report["errors"][0]["code"], "noncanonical-order"
        )

        valid = self.directory / "review-order-valid.tsv"
        write_rows(
            str(valid),
            [row(group, exercise) for group, exercise in ((1, 1), (1, 2), (2, 1), (2, 2))],
        )
        valid_report = validate_refs.validate_plan(str(valid))
        self.assertEqual(valid_report["summary"]["errors"], 0)
        self.assertEqual(valid_report["summary"]["warnings"], 0)

    def test_reference_validator_blocks_missing_second_exercise(self) -> None:
        plan = self.write_reference_plan(
            "missing-second-exercise.tsv",
            [
                {
                    "sessionID": 1,
                    "GroupID": 200,
                    "GroupFrame": 0,
                    "expectedExerciseCount": 2,
                }
            ],
            status="draft",
        )

        report = validate_refs.validate_plan(str(plan))

        self.assertIn(
            "missing-group-exercises",
            {item["code"] for item in report["errors"]},
        )
        completeness = next(
            result
            for result in report["ruleResults"]
            if result["rule"] == "exercise-completeness"
        )
        self.assertEqual(completeness["status"], "failed")
        self.assertEqual(
            completeness["errors"][0]["code"],
            "missing-group-exercises",
        )

    def test_reference_validator_accepts_explicit_exercise_omission(self) -> None:
        source = {
            "raw": "National 6 TUM Female exercise 2 omitted",
            "sessionNumber": 101,
            "sessionTitle": "TUM",
            "competitionTitle": "Competition 10",
            "stageKind": "Qualification",
            "groupNumber": 1,
        }
        plan = self.write_reference_plan(
            "second-exercise-omitted.tsv",
            [
                {
                    "sessionID": 1,
                    "GroupID": 200,
                    "GroupFrame": 0,
                    "expectedExerciseCount": 2,
                }
            ],
            status="draft",
            omitted=[
                {
                    "sessionID": 1,
                    "GroupID": 200,
                    "GroupFrame": 1,
                    "expectedExerciseCount": 2,
                    "source": source,
                    "omittedIntentionally": True,
                    "reason": (
                        "User explicitly requested omitting exercise 2 for "
                        "this group."
                    ),
                }
            ],
        )

        report = validate_refs.validate_plan(str(plan))

        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["summary"]["rules"], len(validate_refs.RULES))
        self.assertTrue(
            all(
                {"rule", "status", "errors", "warnings", "data"} <= set(result)
                for result in report["ruleResults"]
            )
        )

    def test_reference_validator_rejects_unconfirmed_omission(self) -> None:
        plan = self.write_reference_plan(
            "second-exercise-unconfirmed.tsv",
            [
                {
                    "sessionID": 1,
                    "GroupID": 200,
                    "GroupFrame": 0,
                    "expectedExerciseCount": 2,
                }
            ],
            status="draft",
            omitted=[
                {
                    "sessionID": 1,
                    "GroupID": 200,
                    "GroupFrame": 1,
                    "expectedExerciseCount": 2,
                    "source": {
                        "sessionNumber": 101,
                        "sessionTitle": "TUM",
                        "competitionTitle": "Competition 10",
                        "stageKind": "Qualification",
                        "groupNumber": 1,
                    },
                    "reason": "The schedule did not mention exercise 2.",
                }
            ],
        )

        report = validate_refs.validate_plan(str(plan))

        self.assertIn(
            "omission-not-explicit",
            {item["code"] for item in report["errors"]},
        )

    def test_final_to_qualification_requires_explicit_user_exception(self) -> None:
        base = {
            "PlanKind": "ovs-session-refs-plan",
            "Version": 2,
            "Mode": "recreate",
            "PlanStatus": "draft",
            "RowType": "ref",
            "SessionID": 1,
            "SessionNumber": 101,
            "SessionTitle": "TRA 1",
            "CompetitionTitle": "National 6 TRP Female",
            "StageKind": "Qualification",
            "GroupNumber": 1,
            "ExerciseNumber": 1,
            "ExpectedExerciseCount": 1,
            "Target": {"GroupID": 200, "GroupFrame": 0},
            "Source": {
                "raw": "National 6 TRP Female FINAL",
                "competitionTitle": "National 6 TRP Female",
                "stageKind": "Qualification",
                "groupNumber": 1,
                "sessionNumber": 101,
            },
            "Details": {"mappingMode": "final-to-qualification-frame-1"},
        }

        invalid = self.directory / "final-qualification-invalid.tsv"
        write_rows(str(invalid), [base])
        report = validate_refs.validate_plan(str(invalid))
        self.assertEqual(
            [item["code"] for item in report["errors"]],
            ["final-mapped-to-qualification"],
        )

        first_routine = self.directory / "final-qualification-frame-zero.tsv"
        write_rows(
            str(first_routine),
            [
                {
                    **base,
                    "Details": {},
                }
            ],
        )
        self.assertEqual(
            validate_refs.validate_plan(str(first_routine))["errors"][0]["code"],
            "final-mapped-to-qualification",
        )

        mode_only = self.directory / "final-mode-only.tsv"
        write_rows(str(mode_only), [{**base, "Source": {}}])
        self.assertEqual(
            validate_refs.validate_plan(str(mode_only))["errors"][0]["code"],
            "final-mapped-to-qualification",
        )

        confirmed = self.directory / "final-qualification-confirmed.tsv"
        write_rows(
            str(confirmed),
            [
                {
                    **base,
                    "Details": {
                        "mappingMode": "final-to-qualification-frame-1",
                        "finalInQualificationExplicitlyRequested": True,
                        "finalMappingBasis": (
                            "User explicitly requested Qualification routine 1 "
                            "for National 6 TRP Female."
                        ),
                    },
                }
            ],
        )
        confirmed_report = validate_refs.validate_plan(str(confirmed))
        self.assertEqual(confirmed_report["summary"]["errors"], 0)
        self.assertEqual(
            confirmed_report["summary"]["confirmedFinalQualificationExceptions"],
            1,
        )

        missing_basis = self.directory / "final-confirmation-without-basis.tsv"
        write_rows(
            str(missing_basis),
            [
                {
                    **base,
                    "Details": {
                        "finalInQualificationExplicitlyRequested": True,
                    },
                }
            ],
        )
        self.assertEqual(
            validate_refs.validate_plan(str(missing_basis))["errors"][0]["code"],
            "final-mapped-to-qualification",
        )

        final_stage = self.directory / "final-stage.tsv"
        write_rows(
            str(final_stage),
            [
                {
                    **base,
                    "StageKind": "Final1",
                    "ExerciseNumber": 1,
                    "ExpectedExerciseCount": 1,
                    "Target": {
                        "CompetitionID": 10,
                        "StageKind": "Final1",
                        "GroupIndex": 0,
                        "GroupFrame": 0,
                    },
                    "Source": {
                        **base["Source"],
                        "stageKind": "Final1",
                    },
                    "Details": {"mappingMode": "final-to-created-final1-stage"},
                }
            ],
        )
        self.assertEqual(
            validate_refs.validate_plan(str(final_stage))["summary"]["errors"],
            0,
        )

        ambiguous = self.directory / "final-ambiguous.tsv"
        write_rows(
            str(ambiguous),
            [
                {
                    "PlanKind": "ovs-session-refs-plan",
                    "Version": 2,
                    "Mode": "recreate",
                    "PlanStatus": "draft",
                    "RowType": "ambiguous",
                    "SessionID": 1,
                    "Source": {"raw": "National 6 TRP Female FINAL"},
                    "Details": {"reason": "Final stage structure requires user input."},
                }
            ],
        )
        self.assertEqual(
            validate_refs.validate_plan(str(ambiguous))["summary"]["errors"],
            0,
        )
        ambiguous_report = validate_refs.validate_plan(str(ambiguous))
        self.assertEqual(ambiguous_report["summary"]["unresolvedRows"], 1)
        self.assertIn(
            "unresolved-row",
            {item["code"] for item in ambiguous_report["warnings"]},
        )

    def test_phase_two_rejects_unresolved_approved_plan_before_network(self) -> None:
        for row_type in ("ambiguous", "unmatched"):
            plan = self.directory / f"{row_type}-approved.tsv"
            write_rows(
                str(plan),
                [
                    {
                        "PlanKind": "ovs-session-refs-plan",
                        "Version": 2,
                        "Mode": "recreate",
                        "PlanStatus": "approved",
                        "RowType": row_type,
                        "SessionID": 1,
                        "Source": {"raw": "Women Final B"},
                        "Details": {
                            "proposedAction": "stageCreate",
                            "proposedStageKind": "Final2",
                            "proposalBasis": (
                                "The schedule label most likely names a second final."
                            ),
                        },
                    }
                ],
            )
            report = validate_refs.validate_plan(str(plan))
            self.assertIn(
                "unresolved-row", {item["code"] for item in report["errors"]}
            )
            argv = [
                apply_refs.__file__,
                "--base-url",
                "http://mock",
                "--plan",
                str(plan),
                "--dry-run",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                apply_refs, "request_json"
            ) as request:
                with self.assertRaises(SystemExit):
                    apply_refs.main()
            request.assert_not_called()

    def test_phase_two_print_example_is_canonical_and_valid(self) -> None:
        output = self.directory / "example.tsv"
        argv = [apply_refs.__file__, "--print-example"]
        with mock.patch.object(sys, "argv", argv), mock.patch(
            "sys.stdout.write"
        ) as write:
            self.assertEqual(apply_refs.main(), 0)
        rendered = "".join(call.args[0] for call in write.call_args_list)
        output.write_text(rendered, encoding="utf-8")
        rows = read_rows(str(output))
        self.assertEqual(
            {row["RowType"] for row in rows},
            {"stageCreate", "ref", "omitted", "skipped"},
        )
        self.assertEqual(
            validate_refs.validate_plan(str(output))["summary"]["errors"], 0
        )

    def test_phase_two_semantic_validation_precedes_token_and_network(self) -> None:
        plan = self.directory / "phase-two-semantic-error.tsv"
        write_rows(
            str(plan),
            [
                {
                    "PlanKind": "ovs-session-refs-plan",
                    "Version": 2,
                    "Mode": "recreate",
                    "PlanStatus": "approved",
                    "RowType": "ref",
                    "SessionID": 1,
                    "SessionNumber": 101,
                    "SessionTitle": "TRA 1",
                    "CompetitionTitle": "Competition 10",
                    "StageKind": "Qualification",
                    "GroupNumber": 1,
                    "ExerciseNumber": 2,
                    "ExpectedExerciseCount": 2,
                    "Target": {"GroupID": 200, "GroupFrame": 1},
                    "Source": {"raw": "Competition 10 FINAL"},
                    "Details": {},
                }
            ],
        )
        argv = [
            apply_refs.__file__,
            "--base-url",
            "http://mock",
            "--plan",
            str(plan),
            "--dry-run",
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            apply_refs, "request_json"
        ) as request:
            with self.assertRaises(SystemExit) as caught:
                apply_refs.main()
        self.assertIn("final-mapped-to-qualification", str(caught.exception))
        request.assert_not_called()

    def test_start_list_statuses_and_real_failure(self) -> None:
        self.ovs.add_session(1)
        self.ovs.add_session(2, [201])
        self.ovs.add_session(3, [200])
        self.ovs.sessions["3"]["RotationView"] = 4
        references = self.write_reference_plan(
            "refs.applied.tsv",
            [
                {"sessionID": 2, "GroupID": 201, "GroupFrame": 0},
                {"sessionID": 3, "GroupID": 200, "GroupFrame": 0},
            ],
            status="applied",
        )
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
                    "Field:RotationView": 0,
                }
                for session_id in (2, 3)
            ],
        )
        start_rows = read_rows(str(source))
        start_rows.append(
            {
                **{
                    key: value
                    for key, value in start_rows[0].items()
                    if key not in {"Field:RotationView"}
                },
                "RowType": "omitted",
                "SessionID": "1",
                "SessionNumber": "101",
                "SessionTitle": "Empty final",
                "Details": json.dumps(
                    {"reason": "No refs were approved in phase 2."}
                ),
            }
        )
        write_rows(str(source), start_rows)
        audit = self.directory / "start.json"
        self.run_main(
            generate_lists,
            "--plan",
            str(source),
            "--references-plan",
            str(references),
            "--audit-output",
            str(audit),
        )
        statuses = {
            item["sessionID"]: item["status"]
            for item in json.loads(audit.read_text())["sessions"]
        }
        self.assertEqual(
            statuses,
            {2: "refs-without-performances", 3: "generated"},
        )
        audit_data = json.loads(audit.read_text())
        self.assertEqual(audit_data["omittedSessions"][0]["sessionID"], 1)
        self.assertEqual(
            [self.ovs.sessions[str(session_id)]["RotationView"] for session_id in (1, 2, 3)],
            [0, 0, 0],
        )
        mutation_paths = [
            path
            for method, path, _body in self.ovs.mutations
            if path.startswith("/api/sessions/")
        ]
        self.assertNotIn("/api/sessions/1", mutation_paths)
        self.assertNotIn("/api/sessions/1/generate", mutation_paths)
        self.assertLess(
            mutation_paths.index("/api/sessions/3"),
            mutation_paths.index("/api/sessions/3/generate"),
        )

    def test_phase_three_rejects_zero_ref_target_before_network(self) -> None:
        references = self.directory / "empty-refs.applied.tsv"
        write_rows(
            str(references),
            [
                {
                    "PlanKind": "ovs-session-refs-plan",
                    "Version": 2,
                    "Mode": "recreate",
                    "PlanStatus": "applied",
                    "RowType": "skipped",
                    "SessionID": 1,
                    "Source": {"raw": "Unresolved final"},
                    "Details": {
                        "reason": "User approved omitting the missing final stage."
                    },
                }
            ],
        )
        start = self.directory / "zero-ref-start.tsv"
        write_rows(
            str(start),
            [
                {
                    "PlanKind": "ovs-session-start-lists-plan",
                    "Version": 1,
                    "Mode": "create",
                    "PlanStatus": "approved",
                    "RowType": "session",
                    "SessionID": 1,
                    "Field:RotationView": 0,
                }
            ],
        )
        argv = [
            generate_lists.__file__,
            "--base-url",
            "http://mock",
            "--plan",
            str(start),
            "--references-plan",
            str(references),
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            generate_lists, "request_json"
        ) as request:
            with self.assertRaises(SystemExit) as caught:
                generate_lists.main()
        self.assertIn("RowType=omitted", str(caught.exception))
        request.assert_not_called()

        self.ovs.add_session(4, [202])
        failure_references = self.write_reference_plan(
            "failure-refs.applied.tsv",
            [{"sessionID": 4, "GroupID": 202, "GroupFrame": 0}],
            status="applied",
        )
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
                    "Field:RotationView": 0,
                }
            ],
        )
        self.run_main(
            generate_lists,
            "--plan",
            str(failure),
            "--references-plan",
            str(failure_references),
            error=ApiError,
        )

    def test_phase_three_requires_valid_applied_references_plan(self) -> None:
        self.ovs.add_session(1)
        start = self.directory / "start-guard.tsv"
        write_rows(
            str(start),
            [
                {
                    "PlanKind": "ovs-session-start-lists-plan",
                    "Version": 1,
                    "Mode": "create",
                    "PlanStatus": "approved",
                    "RowType": "session",
                    "SessionID": 1,
                    "Field:RotationView": 0,
                }
            ],
        )
        draft_refs = self.write_reference_plan(
            "refs.draft.tsv",
            [{"sessionID": 1, "GroupID": 200, "GroupFrame": 0}],
            status="draft",
        )

        error = self.run_main(
            generate_lists,
            "--plan",
            str(start),
            "--references-plan",
            str(draft_refs),
            error=SystemExit,
        )
        self.assertIn("applied apply/recreate", str(error))
        self.assertEqual(self.ovs.mutations, [])

        missing_rotation = self.directory / "start-missing-rotation.tsv"
        write_rows(
            str(missing_rotation),
            [
                {
                    "PlanKind": "ovs-session-start-lists-plan",
                    "Version": 1,
                    "Mode": "create",
                    "PlanStatus": "approved",
                    "RowType": "session",
                    "SessionID": 1,
                }
            ],
        )
        error = self.run_main(
            generate_lists,
            "--plan",
            str(missing_rotation),
            "--references-plan",
            str(draft_refs),
            error=SystemExit,
        )
        self.assertIn("Field:RotationView", str(error))

        semantic_error = self.directory / "refs.semantic-error.applied.tsv"
        write_rows(
            str(semantic_error),
            [
                {
                    "PlanKind": "ovs-session-refs-plan",
                    "Version": 2,
                    "Mode": "recreate",
                    "PlanStatus": "applied",
                    "RowType": "ref",
                    "SessionID": 1,
                    "SessionNumber": 101,
                    "SessionTitle": "TRA 1",
                    "CompetitionTitle": "Competition 10",
                    "StageKind": "Qualification",
                    "GroupNumber": 1,
                    "ExerciseNumber": 2,
                    "ExpectedExerciseCount": 2,
                    "Target": {"GroupID": 200, "GroupFrame": 1},
                    "Source": {"raw": "Competition 10 FINAL"},
                    "Details": {},
                }
            ],
        )
        with mock.patch.object(
            generate_lists, "read_token"
        ) as read_token, mock.patch.object(
            generate_lists, "request_json"
        ) as request, mock.patch.object(
            sys,
            "argv",
            [
                generate_lists.__file__,
                "--base-url",
                "http://mock",
                "--plan",
                str(start),
                "--references-plan",
                str(semantic_error),
            ],
        ):
            with self.assertRaises(SystemExit) as caught:
                generate_lists.main()
        self.assertIn("final-mapped-to-qualification", str(caught.exception))
        read_token.assert_not_called()
        request.assert_not_called()

        with mock.patch.object(
            sys,
            "argv",
            [
                generate_lists.__file__,
                "--base-url",
                "http://mock",
                "--plan",
                str(start),
            ],
        ):
            with self.assertRaises(SystemExit):
                generate_lists.parse_args()

    def test_standalone_phase_three_adopts_and_verifies_live_refs(self) -> None:
        self.ovs.competitions["10"]["Title"] = "Competition 10"
        self.ovs.stages["20"]["Kind"] = 0
        self.ovs.add_session(1, [200])
        self.ovs.sessions["1"]["Number"] = 101
        self.ovs.sessions["1"]["SessionTitle"] = "TRA 1"
        self.ovs.sessions["1"]["RotationView"] = 4

        snapshot = self.directory / "standalone-snapshot.json"
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

        adopted_draft = self.directory / "refs.adopted.draft.tsv"
        argv = [
            build_adopted_refs.__file__,
            "--snapshot",
            str(snapshot),
            "--output",
            str(adopted_draft),
            "--session-id",
            "1",
        ]
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(build_adopted_refs.main(), 0)
        adopted = load_refs_plan(str(adopted_draft))
        self.assertEqual(adopted["mode"], "adopt")
        self.assertEqual(adopted["status"], "draft")
        self.assertEqual(
            [(item["GroupID"], item["GroupFrame"]) for item in adopted["refs"]],
            [(200, 0)],
        )

        adopted_approved = self.directory / "refs.adopted.approved.tsv"
        rows = read_rows(str(adopted_draft))
        for row in rows:
            row["PlanStatus"] = "approved"
        write_rows(str(adopted_approved), rows)

        start = self.directory / "standalone-start.tsv"
        write_rows(
            str(start),
            [
                {
                    "PlanKind": "ovs-session-start-lists-plan",
                    "Version": 1,
                    "Mode": "create",
                    "PlanStatus": "approved",
                    "RowType": "session",
                    "SessionID": 1,
                    "Field:RotationView": 0,
                }
            ],
        )
        self.run_main(
            generate_lists,
            "--plan",
            str(start),
            "--references-plan",
            str(adopted_approved),
            "--dry-run",
        )
        self.assertEqual(self.ovs.sessions["1"]["RotationView"], 4)

        self.ovs.sessions["1"]["GroupFrame"] = [1]
        error = self.run_main(
            generate_lists,
            "--plan",
            str(start),
            "--references-plan",
            str(adopted_approved),
            "--dry-run",
            error=SystemExit,
        )
        self.assertIn("Live session references differ", str(error))

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
        self.assertNotIn("Sessions", result)
        self.assertNotIn("Competitions", result)
        self.assertEqual(self.ovs.mutations, [])


if __name__ == "__main__":
    unittest.main()
