"""Command line.

    trial build [--harness NAME ...]          build the sandbox, harness and gateway images
    trial validate [--task ID ...]            check that each task's hidden tests fail at the start commit and
                                              pass with the original fix
    trial run NAME [--harness ...] [--task ...] [--attempts N] [--concurrency N] [--budget USD] [--time-limit S]
    trial report NAME                         write results/NAME/report.md from results/NAME/runs.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from trial import docker
from trial.grade import grade
from trial.harnesses import HARNESSES
from trial.report import render
from trial.run import RunSpec, run_trial
from trial.tasks import ROOT, load_all

RESULTS = ROOT / "results"


async def validate(task_ids: list[str] | None) -> int:
    work = ROOT / "runs" / "validate"
    shutil.rmtree(work, ignore_errors=True)
    failures = 0
    for task in load_all(task_ids):
        code, fix_patch, err = await docker.ash("docker", "run", "--rm", "trial-base", "git", "-C",
                                                f"/opt/src/{task.repo}", "diff", "--binary", task.base, task.fix)
        if code != 0:
            print(f"{task.id}: cannot diff {task.base}..{task.fix}: {err.strip()}")
            failures += 1
            continue
        at_start = await grade(task, _fresh(work / task.id / "start"), "")
        with_fix = await grade(task, _fresh(work / task.id / "fix"), fix_patch)
        ok = (at_start.hidden_total > 0 and at_start.hidden_passed < at_start.hidden_total and with_fix.resolved)
        failures += not ok
        print(f"{task.id}: {'ok' if ok else 'INVALID'} (start {at_start.hidden_passed}/{at_start.hidden_total}, "
              f"fix {with_fix.hidden_passed}/{with_fix.hidden_total}, suite {with_fix.suite_passed}/"
              f"{with_fix.suite_total}{', ' + with_fix.error if with_fix.error else ''})")
    return 1 if failures else 0


def _fresh(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="trial")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--harness", nargs="*", default=list(HARNESSES), choices=list(HARNESSES))
    v = sub.add_parser("validate")
    v.add_argument("--task", nargs="*")
    r = sub.add_parser("run")
    r.add_argument("name")
    r.add_argument("--harness", nargs="*", default=list(HARNESSES), choices=list(HARNESSES))
    r.add_argument("--task", nargs="*")
    r.add_argument("--attempts", type=int, default=1)
    r.add_argument("--concurrency", type=int, default=3)
    r.add_argument("--budget", type=float, default=20.0, help="USD across all trials sharing results/ledger")
    r.add_argument("--time-limit", type=float, default=900, help="seconds per run")
    p = sub.add_parser("report")
    p.add_argument("name")
    args = parser.parse_args(argv)

    if args.command == "build":
        docker.build(args.harness)
        return 0
    if args.command == "validate":
        return asyncio.run(validate(args.task))
    if args.command == "report":
        out = RESULTS / args.name / "report.md"
        out.write_text(render(RESULTS / args.name), encoding="utf-8", newline="\n")
        print(out)
        return 0

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.name):
        parser.error("trial name: lower-case letters, digits and hyphens (it is part of URLs and container names)")
    trial_dir = RESULTS / args.name
    specs = [RunSpec(args.name, t, HARNESSES[h], n) for n in range(1, args.attempts + 1) for t in load_all(args.task)
             for h in args.harness]
    # One ledger for every trial, so the budget covers the whole study, not each trial separately.
    ledger = RESULTS / "ledger"
    docker.start_gateway(ledger, args.budget)
    try:
        asyncio.run(run_trial(specs, trial_dir, ledger, args.budget, args.concurrency, args.time_limit))
    finally:
        docker.stop_gateway()
    (trial_dir / "report.md").write_text(render(trial_dir), encoding="utf-8", newline="\n")
    print(json.dumps({"report": str(trial_dir / "report.md")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
