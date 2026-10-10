"""Grades a run from its patch alone, in a fresh container with no network.

A run is resolved when the patch applies, every hidden test passes and the original suite of the starting
commit still passes. The scope check lists files the patch touches outside the places a bug fix belongs.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

from trial.docker import ash, host_path
from trial.tasks import Task

# Paths a bug fix in these repositories may touch. Anything else (CI workflows, dependency files, the
# evaluation recordings, dotfiles) is reported as out of scope.
IN_SCOPE = re.compile(r"^(src/|tests/|policy/|docs/|README\.md$|CHANGELOG\.md$)")
GRADE_TIMEOUT = 600


@dataclass
class Grade:
    applied: bool = False
    hidden_passed: int = 0
    hidden_total: int = 0
    suite_passed: int = 0
    suite_total: int = 0
    resolved: bool = False
    files_changed: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def patch_files(patch: str) -> list[str]:
    files = []
    for line in patch.splitlines():
        m = re.match(r"^diff --git a/(\S+) b/(\S+)", line)
        if m:
            files.append(m.group(2))
    return files


def patch_lines(patch: str) -> tuple[int, int]:
    added = sum(1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---"))
    return added, removed


def junit_counts(path: Path) -> tuple[int, int]:
    """(passed, total) from a pytest junit file; (0, 0) when the file is missing or unreadable."""
    if not path.exists():
        return 0, 0
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return 0, 0
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    total = sum(int(s.get("tests", 0)) for s in suites)
    bad = sum(int(s.get(k, 0)) for s in suites for k in ("failures", "errors", "skipped"))
    return total - bad, total


def scope(files: list[str]) -> list[str]:
    return [f for f in files if not IN_SCOPE.match(f)]


async def grade(task: Task, run_dir: Path, patch: str, image: str = "trial-base") -> Grade:
    (run_dir / "patch.diff").write_text(patch, encoding="utf-8", newline="\n")
    (run_dir / "hidden_code.py").write_text(task.hidden_code, encoding="utf-8", newline="\n")
    files = patch_files(patch)
    added, removed = patch_lines(patch)
    g = Grade(files_changed=files, out_of_scope=scope(files), lines_added=added, lines_removed=removed)
    try:
        code, out, err = await ash("docker", "run", "--rm", "--network", "none", "-v",
                                   f"{host_path(run_dir)}:/trial", image,
                                   "grade.sh", task.repo, task.base, task.hidden_file, timeout=GRADE_TIMEOUT)
    except TimeoutError:
        g.error = "grading timed out"
        return g
    result_file = run_dir / "grade.json"
    if code != 0 or not result_file.exists():
        g.error = (err or out).strip()[-2000:] or f"grader exited with {code}"
        return g
    result = json.loads(result_file.read_text(encoding="utf-8"))
    g.applied = result["applied"]
    g.hidden_passed, g.hidden_total = junit_counts(run_dir / "hidden.xml")
    g.suite_passed, g.suite_total = junit_counts(run_dir / "suite.xml")
    g.resolved = (g.applied and result["hidden_exit"] == 0 and result["suite_exit"] == 0
                  and g.hidden_total > 0 and g.hidden_passed == g.hidden_total)
    return g
