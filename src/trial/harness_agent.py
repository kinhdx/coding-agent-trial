"""Runs tasks through AI SDK HarnessAgent adapters (the ts/ runner) and records them like ACP runs.

The Python side owns everything around the agent turn: it writes the jobs file, starts the gateway with the
npm registry on the egress allowlist (the adapters install their CLI when a session starts), runs the ts/
runner in a container on the internal network, then grades each run folder and appends it to runs.jsonl,
so `trial report` covers both kinds of run in one table.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from trial import docker
from trial.grade import grade
from trial.harnesses import GATEWAY, PLACEHOLDER_KEY
from trial.run import ledger_totals, spent
from trial.tasks import Task

SANDBOX_IMAGE = "trial-harness-agent"
RUNNER_IMAGE = "trial-ts-runner"
EGRESS_ALLOW = "registry.npmjs.org"


@dataclass(frozen=True)
class AgentHarness:
    name: str  # recorded harness name; the "sdk-" prefix keeps these rows apart from the ACP runs
    adapter: str  # ts/ adapter id
    model: str


AGENT_HARNESSES = {h.name: h for h in (
    AgentHarness("sdk-claude-code", "claude-code", "claude-sonnet-5-5"),
    AgentHarness("sdk-grok-build", "grok-build", "grok-build-0.1"),
)}


def run_id(trial: str, task: Task, harness: AgentHarness, attempt: int) -> str:
    return f"{trial}.{task.id}.{harness.name}.{attempt}"


def write_jobs(trial_dir: Path, trial: str, jobs: list[tuple[Task, AgentHarness, int]], concurrency: int,
               time_limit: float) -> Path:
    spec = {
        "gateway": GATEWAY, "placeholderKey": PLACEHOLDER_KEY, "image": SANDBOX_IMAGE, "network": docker.NETWORK,
        "runsDir": f"/results/{trial}/runs", "concurrency": concurrency, "timeLimitSeconds": time_limit,
        "jobs": [{"run": run_id(trial, t, h, n), "repo": t.repo, "base": t.base, "harness": h.adapter,
                  "model": h.model, "prompt": t.agent_prompt, "sandboxEnv": docker.proxy_env(run_id(trial, t, h, n))}
                 for t, h, n in jobs],
    }
    # Run folders are created here, on the host, as for ACP runs: a folder the runner creates as root in its
    # container is not writable by the grader, which runs as the sandbox user.
    for job in spec["jobs"]:
        (trial_dir / "runs" / job["run"]).mkdir(parents=True, exist_ok=True)
    path = trial_dir / "jobs.json"
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


def run_runner(results: Path, trial: str) -> int:
    """Runs the ts/ runner to completion, streaming its output; returns its exit code."""
    return docker.sh(
        "docker", "run", "--rm", "--name", "trial-ts-runner", "--network", docker.NETWORK,
        "-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", f"{docker.host_path(results)}:/results",
        "-e", f"ANTHROPIC_API_KEY={PLACEHOLDER_KEY}", "-e", f"XAI_API_KEY={PLACEHOLDER_KEY}",
        RUNNER_IMAGE, f"/results/{trial}/jobs.json", check=False, capture=False).returncode


async def collect(trial_dir: Path, ledger: Path, jobs: list[tuple[Task, AgentHarness, int]]) -> None:
    """Grades every finished run folder that runs.jsonl does not list yet and appends its record."""
    results = trial_dir / "runs.jsonl"
    done = {json.loads(line)["run"] for line in results.read_text(encoding="utf-8").splitlines() if line} \
        if results.exists() else set()
    trial = trial_dir.name
    for task, harness, attempt in jobs:
        rid = run_id(trial, task, harness, attempt)
        run_dir = trial_dir / "runs" / rid
        meta_path = run_dir / "agent-run.json"
        if rid in done or not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        patch = (run_dir / "patch.diff").read_text(encoding="utf-8", errors="replace")
        record = {"run": rid, "task": task.id, "repo": task.repo, "harness": harness.name, "attempt": attempt,
                  "model": harness.model, "error": meta.get("error"), "stop_reason": meta.get("stop_reason"),
                  "agent": f"ai-sdk harness {harness.adapter}", "agent_seconds": meta.get("agent_seconds"),
                  "setup_seconds": meta.get("setup_seconds"),
                  "tool_calls": meta.get("tool_calls", 0), "grade": (await grade(task, run_dir, patch)).to_dict()}
        record.update(ledger_totals(ledger, rid))
        with results.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        g = record["grade"]
        print(f"{rid}: {'resolved' if g['resolved'] else 'not resolved'}, {record['cost_usd']:.3f} USD")


def run_agent_trial(results: Path, trial: str, jobs: list[tuple[Task, AgentHarness, int]], budget: float,
                    concurrency: int, time_limit: float) -> None:
    trial_dir = results / trial
    trial_dir.mkdir(parents=True, exist_ok=True)
    ledger = results / "ledger"
    if spent(ledger) >= budget:
        print(f"budget of {budget:.2f} USD spent; nothing started")
        return
    recorded = {json.loads(line)["run"] for line in (trial_dir / "runs.jsonl").read_text(encoding="utf-8")
                .splitlines() if line} if (trial_dir / "runs.jsonl").exists() else set()
    pending = [j for j in jobs if run_id(trial, *j) not in recorded]
    print(f"{len(pending)} runs to do, {len(jobs) - len(pending)} already recorded")
    if pending:
        write_jobs(trial_dir, trial, pending, concurrency, time_limit)
        docker.start_gateway(ledger, budget, EGRESS_ALLOW)
        try:
            run_runner(results, trial)
        finally:
            docker.stop_gateway()
    asyncio.run(collect(trial_dir, ledger, jobs))
