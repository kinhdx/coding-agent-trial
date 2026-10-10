"""Task definitions: a bug report taken from a real fix commit, the commit it starts from, and hidden tests.

The hidden tests are the tests written with the original fix, reduced to the one behaviour the task asks
for. The grader appends them to the starting commit's version of the test file, so they can use that
file's fixtures and imports, and runs only the functions whose names contain "hidden".
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "tasks"
REPO_URL = "https://github.com/kinhdx/{repo}"

INSTRUCTIONS = """You are working in a Python repository checked out at /work. Fix the issue described below.
Dependencies are installed; run the test suite with `uv run pytest`. There is no network access.
Change the code and add or update tests as you see fit, but do not commit.

Issue:
"""


@dataclass(frozen=True)
class Task:
    id: str
    repo: str
    base: str
    fix: str
    prompt: str
    hidden_file: str
    hidden_code: str

    @property
    def agent_prompt(self) -> str:
        return INSTRUCTIONS + self.prompt


def load(path: Path) -> Task:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Task(d["id"], d["repo"], str(d["base"]), str(d["fix"]), d["prompt"].strip(), d["hidden"]["file"],
                d["hidden"]["code"])


def load_all(ids: list[str] | None = None) -> list[Task]:
    tasks = [load(p) for p in sorted(TASKS.glob("*.yaml"))]
    if ids:
        missing = set(ids) - {t.id for t in tasks}
        if missing:
            raise SystemExit(f"unknown task ids: {', '.join(sorted(missing))}")
        tasks = [t for t in tasks if t.id in ids]
    return tasks
