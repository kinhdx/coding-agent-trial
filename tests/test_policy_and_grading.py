from __future__ import annotations

import json

from acp.schema import PermissionOption, ToolCallLocation, ToolCallUpdate

from trial.agent_client import decide, pick
from trial.grade import junit_counts, patch_files, patch_lines, scope
from trial.harnesses import HARNESSES, PLACEHOLDER_KEY
from trial.report import summarise
from trial.run import ledger_totals, spent
from trial.tasks import load_all


def call(kind: str, *paths: str) -> ToolCallUpdate:
    return ToolCallUpdate(tool_call_id="t1", kind=kind, locations=[ToolCallLocation(path=p) for p in paths])


def test_writes_inside_the_workspace_are_allowed():
    assert decide(call("edit", "/work/src/a.py"))[0]
    assert decide(call("execute"))[0]
    assert decide(call("read", "/etc/passwd"))[0]  # reading is contained by the sandbox, not the policy


def test_fetch_and_writes_elsewhere_are_refused():
    assert not decide(call("fetch"))[0]
    assert not decide(call("edit", "/etc/hosts"))[0]
    assert not decide(call("edit", "/work/../etc/hosts"))[0]
    assert not decide(call("delete", "/home/agent/.bashrc"))[0]
    assert not decide(call("move", "/work/a.py", "/tmp/a.py"))[0]
    assert not decide(call("edit", "/workspace/a.py"))[0]


def test_pick_prefers_one_time_answers():
    options = [PermissionOption(option_id="always", name="Always", kind="allow_always"),
               PermissionOption(option_id="once", name="Once", kind="allow_once"),
               PermissionOption(option_id="no", name="No", kind="reject_once")]
    assert pick(options, True) == "once"
    assert pick(options, False) == "no"
    assert pick(options[:1], False) is None


PATCH = """diff --git a/src/service/redact.py b/src/service/redact.py
--- a/src/service/redact.py
+++ b/src/service/redact.py
@@ -1,2 +1,3 @@
-old
+new
+more
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1 +1 @@
-x
+y
"""


def test_patch_files_lines_and_scope():
    files = patch_files(PATCH)
    assert files == ["src/service/redact.py", ".github/workflows/ci.yml"]
    assert patch_lines(PATCH) == (3, 2)
    assert scope(files) == [".github/workflows/ci.yml"]
    assert scope(["tests/test_x.py", "policy/thresholds.json", "README.md", "uv.lock"]) == ["uv.lock"]


def test_junit_counts(tmp_path):
    path = tmp_path / "r.xml"
    path.write_text('<testsuites><testsuite tests="5" failures="1" errors="1" skipped="0"/></testsuites>',
                    encoding="utf-8")
    assert junit_counts(path) == (3, 5)
    assert junit_counts(tmp_path / "missing.xml") == (0, 0)


def test_harness_environment_points_at_the_gateway_with_a_placeholder_key():
    for h in HARNESSES.values():
        env = h.environment("run-1")
        assert any(v.startswith("http://gateway:8080/run-1/") for v in env.values()), h.name
        assert PLACEHOLDER_KEY in env.values(), h.name


def test_tasks_load_and_hidden_tests_are_named_for_selection():
    tasks = load_all()
    assert len(tasks) == 11 and len({t.id for t in tasks}) == 11
    for t in tasks:
        assert "def test_hidden_" in t.hidden_code, t.id
        assert t.hidden_file.startswith("tests/test_"), t.id


def test_summary_counts_resolved_runs_and_cost():
    def run(harness, resolved, cost):
        return {"harness": harness, "model": "m", "models": ["m"], "attempt": 1, "agent_seconds": 10,
                "tool_calls": 4, "cost_usd": cost, "error": None, "egress_denied": [],
                "grade": {"resolved": resolved, "out_of_scope": [], "applied": True, "hidden_total": 1,
                          "hidden_passed": 1 if resolved else 0, "files_changed": ["src/a.py"]}}
    rows = summarise([run("a", True, 0.5), run("a", False, 0.3), run("b", True, 0.1)])
    a = next(r for r in rows if r["harness"] == "a")
    assert (a["resolved"], a["runs"], round(a["cost_usd"], 2), round(a["cost_per_resolved"], 2)) == (1, 2, 0.8, 0.8)


def test_ledger_totals_keep_runs_apart_and_skip_unbilled_requests(tmp_path):
    def call(run, model, cost):
        return json.dumps({"run": run, "model": model, "status": 200, "cost_usd": cost, "input": 10,
                           "cache_read": 0, "cache_write": 0, "output": 5}) + "\n"
    (tmp_path / "calls.jsonl").write_text(
        call("a.t.h.1", "m", 0.5) + call("a.t.h.1", None, None) + call("a.t.h.1", "m", None)
        + call("b.t.h.1", "m", 2.0), encoding="utf-8")
    totals = ledger_totals(tmp_path, "a.t.h.1")
    assert (totals["model_calls"], totals["unpriced_calls"], totals["cost_usd"]) == (2, 1, 0.5)
    assert spent(tmp_path) == 2.5
