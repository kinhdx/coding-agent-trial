"""One trial: every selected task through every selected harness, `attempts` times, in parallel sandboxes.

Each run gets its own container on the internal network. The runner drives the harness over ACP through
`docker exec -i`, takes the workspace diff when the agent stops (or the time limit is reached), removes the
container and grades the diff in a fresh one. Results are appended to <trial>/runs.jsonl as runs finish,
so an interrupted trial keeps its completed runs and `--resume` skips them.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

from acp import PROTOCOL_VERSION, spawn_agent_process, text_block
from acp.schema import ClientCapabilities, Implementation

from trial.agent_client import TrialClient
from trial.docker import ash, proxy_env, remove, start_sandbox
from trial.grade import grade
from trial.harnesses import Harness
from trial.tasks import Task

STDIO_LIMIT = 16 * 1024 * 1024  # ACP frames carry whole file contents; the asyncio default of 64 KiB is too small


@dataclass(frozen=True)
class RunSpec:
    trial: str
    task: Task
    harness: Harness
    attempt: int

    @property
    def run_id(self) -> str:
        # The ledger is shared by every trial, so the id carries the trial name to keep runs apart.
        return f"{self.trial}.{self.task.id}.{self.harness.name}.{self.attempt}"


async def select_model(conn, session, model: str) -> str | None:
    """Selects the trial model through the session's model option when the agent offers one."""
    for option in session.config_options or []:
        data = option.model_dump(mode="json", exclude_none=True)
        if data.get("id") == "model" or data.get("category") == "model":
            values = {o.get("value") for o in data.get("options", []) if isinstance(o, dict)}
            if not values or model in values:
                await conn.set_config_option(config_id=data["id"], session_id=session.session_id, value=model)
                return model
            return f"not offered ({', '.join(sorted(v for v in values if v))})"
    return None


async def drive(spec: RunSpec, container: str, client: TrialClient, time_limit: float, stderr_log: Path) -> dict:
    h = spec.harness
    info: dict = {"stop_reason": None, "model_option": None, "agent": None}
    # The agent's stderr goes to a file: an unread pipe would fill up and stall the agent.
    with stderr_log.open("wb") as stderr:
        async with spawn_agent_process(client, "docker", "exec", "-i", "-w", "/work", container, *h.command,
                                       transport_kwargs={"limit": STDIO_LIMIT, "stderr": stderr}) as (conn, _):
            init = await asyncio.wait_for(conn.initialize(
                protocol_version=PROTOCOL_VERSION, client_capabilities=ClientCapabilities(),
                client_info=Implementation(name="coding-agent-trial", version="0.1.0")), timeout=180)
            if init.agent_info:
                info["agent"] = f"{init.agent_info.name} {init.agent_info.version}"
            if h.auth_method:
                await conn.authenticate(method_id=h.auth_method)
            session = await asyncio.wait_for(conn.new_session(cwd="/work", mcp_servers=[]), timeout=180)
            info["model_option"] = await select_model(conn, session, h.model)
            try:
                response = await asyncio.wait_for(
                    conn.prompt(session_id=session.session_id, prompt=[text_block(spec.task.agent_prompt)]),
                    timeout=time_limit)
                info["stop_reason"] = response.stop_reason
            except TimeoutError:
                info["stop_reason"] = "time_limit"
                try:
                    await asyncio.wait_for(conn.cancel(session_id=session.session_id), timeout=15)
                except Exception:  # noqa: BLE001 - the container is removed next anyway
                    pass
    return info


def ledger_totals(ledger: Path, run_id: str) -> dict:
    calls = [json.loads(line) for line in (ledger / "calls.jsonl").read_text(encoding="utf-8").splitlines()
             if line and json.loads(line)["run"] == run_id] if (ledger / "calls.jsonl").exists() else []
    egress = [json.loads(line) for line in (ledger / "egress.jsonl").read_text(encoding="utf-8").splitlines()
              if line and json.loads(line)["run"] == run_id] if (ledger / "egress.jsonl").exists() else []
    priced = [c["cost_usd"] for c in calls if c["cost_usd"] is not None]
    # Requests that name no model (model listing, key checks) are not billed and do not count as unpriced.
    inference = [c for c in calls if c["model"]]
    return {
        "model_calls": len(inference),
        "models": sorted({c["model"] for c in inference}),
        "failed_calls": sum(1 for c in calls if c["status"] >= 400),
        # A stream the harness closed before the final usage chunk has an unknown cost; ledger lines written
        # before the gateway recorded "complete" count as unpriced.
        "closed_early_calls": sum(1 for c in inference if c["cost_usd"] is None and c.get("complete") is False),
        "unpriced_calls": sum(1 for c in inference if c["cost_usd"] is None and c.get("complete") is not False),
        "input_tokens": sum(c["input"] for c in calls),
        "cache_read_tokens": sum(c["cache_read"] for c in calls),
        "cache_write_tokens": sum(c["cache_write"] for c in calls),
        "output_tokens": sum(c["output"] for c in calls),
        "cost_usd": round(sum(priced), 6),
        "egress_denied": sorted({e["target"] for e in egress if not e["allowed"]}),
    }


async def run_one(spec: RunSpec, trial_dir: Path, time_limit: float) -> dict:
    run_dir = trial_dir / "runs" / spec.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    container = "trial-" + spec.run_id.replace(".", "-")
    client = TrialClient(run_dir / "transcript.jsonl")
    record: dict = {"run": spec.run_id, "task": spec.task.id, "repo": spec.task.repo, "harness": spec.harness.name,
                    "attempt": spec.attempt, "model": spec.harness.model, "error": None}
    started = time.monotonic()
    patch = ""
    try:
        await remove(container)
        await start_sandbox(container, spec.harness.image,
                            {**spec.harness.environment(spec.run_id), **proxy_env(spec.run_id)})
        code, _, err = await ash("docker", "exec", container, "prepare-workspace.sh", spec.task.repo, spec.task.base,
                                 timeout=300)
        if code != 0:
            raise RuntimeError(f"workspace setup failed: {err.strip()[-500:]}")
        agent_started = time.monotonic()
        try:
            record.update(await drive(spec, container, client, time_limit, run_dir / "agent-stderr.log"))
        except Exception as e:  # noqa: BLE001 - an agent crash is a result, not a trial failure
            record["error"] = f"{type(e).__name__}: {e}"[:1000]
        record["agent_seconds"] = round(time.monotonic() - agent_started, 1)
        code, patch, err = await ash("docker", "exec", "-w", "/work", container, "bash", "-c",
                                     "git add -A && git diff --cached --binary HEAD", timeout=120)
        if code != 0:
            record["error"] = (record["error"] or "") + f" diff failed: {err.strip()[-300:]}"
    except Exception as e:  # noqa: BLE001
        record["error"] = f"{type(e).__name__}: {e}"[:1000]
    finally:
        await remove(container)
    record["tool_calls"] = len(client.tool_calls)
    record["permission_requests"] = client.permission_requests
    record["permissions_denied"] = client.denied
    record["grade"] = (await grade(spec.task, run_dir, patch)).to_dict()
    record["wall_seconds"] = round(time.monotonic() - started, 1)
    return record


def spent(ledger: Path) -> float:
    path = ledger / "calls.jsonl"
    if not path.exists():
        return 0.0
    return sum(json.loads(line)["cost_usd"] or 0 for line in path.read_text(encoding="utf-8").splitlines() if line)


async def run_trial(specs: list[RunSpec], trial_dir: Path, ledger: Path, budget: float, concurrency: int,
                    time_limit: float) -> None:
    trial_dir.mkdir(parents=True, exist_ok=True)
    results = trial_dir / "runs.jsonl"
    done = {json.loads(line)["run"] for line in results.read_text(encoding="utf-8").splitlines() if line} \
        if results.exists() else set()
    pending = [s for s in specs if s.run_id not in done]
    gate = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    print(f"{len(pending)} runs to do, {len(specs) - len(pending)} already recorded")

    async def one(spec: RunSpec) -> None:
        async with gate:
            # The gateway refuses model calls once the budget is spent; starting more runs would only wait on 429s.
            # Skipped runs are not recorded, so a later invocation with a larger budget picks them up.
            if spent(ledger) >= budget:
                print(f"{spec.run_id}: skipped, budget of {budget:.2f} USD spent")
                return
            record = await run_one(spec, trial_dir, time_limit)
        record.update(ledger_totals(ledger, spec.run_id))
        async with lock:
            with results.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        g = record["grade"]
        print(f"{spec.run_id}: {'resolved' if g['resolved'] else 'not resolved'}, "
              f"{record.get('cost_usd', 0):.3f} USD, {record['wall_seconds']} s"
              + (f", error: {record['error'][:120]}" if record["error"] else ""))

    # Fan out over all runs; fan in through runs.jsonl, which the report reads.
    await asyncio.gather(*(one(s) for s in pending))
