"""Docker plumbing: the internal network, the gateway container and one sandbox container per run."""
from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from trial.harnesses import HARNESSES
from trial.tasks import load_all

NETWORK = "trial-net"  # --internal: no route out except through the gateway
GATEWAY = "gateway"
# Every sandbox and grading container gets the same hard limit with no swap, so a runaway process is killed
# inside its container instead of pushing the Docker VM, and with it the host, into swapping.
CONTAINER_MEMORY = "2g"
LIMITS = ("--memory", CONTAINER_MEMORY, "--memory-swap", CONTAINER_MEMORY, "--cpus", "2", "--pids-limit", "512")
KEY_VARS = ("ANTHROPIC_API_KEY", "XAI_API_KEY", "DEEPSEEK_API_KEY")


def sh(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, capture_output=capture, text=True, encoding="utf-8")


async def ash(*args: str, stdin: bytes | None = None, timeout: float | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE if stdin else None,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
    except TimeoutError:
        proc.kill()
        raise
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def build(harnesses: list[str]) -> None:
    commits = sorted({f"{t.repo}@{c}" for t in load_all() for c in (t.base, t.fix)})
    sh("docker", "build", "-f", "sandbox/Dockerfile.base", "-t", "trial-base", "--build-arg",
       f"COMMITS={' '.join(commits)}", ".", capture=False)
    for name in harnesses:
        sh("docker", "build", "-f", f"sandbox/Dockerfile.{name}", "-t", HARNESSES[name].image, ".", capture=False)
    sh("docker", "build", "-f", "sandbox/Dockerfile.gateway", "-t", "trial-gateway", ".", capture=False)
    # HarnessAgent runs (ts/): a sandbox with pnpm for the adapters' installs, and the runner itself.
    sh("docker", "build", "-f", "sandbox/Dockerfile.harness-agent", "-t", "trial-harness-agent", ".", capture=False)
    sh("docker", "build", "-f", "sandbox/Dockerfile.ts-runner", "-t", "trial-ts-runner", ".", capture=False)


def host_path(path: Path) -> str:
    """Docker Desktop on Windows accepts C:/... paths for bind mounts; elsewhere the path is used as is."""
    return path.resolve().as_posix()


def start_gateway(ledger: Path, budget_usd: float, egress_allow: str = "") -> None:
    ledger.mkdir(parents=True, exist_ok=True)
    if sh("docker", "network", "inspect", NETWORK, check=False).returncode != 0:
        sh("docker", "network", "create", "--internal", NETWORK)
    sh("docker", "rm", "-f", GATEWAY, check=False)
    # Keys are passed by name only, so their values never appear on a command line.
    env = [a for k in KEY_VARS if os.environ.get(k) for a in ("-e", k)]
    sh("docker", "create", "--name", GATEWAY, "--network", NETWORK, *env,
       "-e", f"BUDGET_USD={budget_usd}", "-e", f"EGRESS_ALLOW={egress_allow}", "-e", "LEDGER_DIR=/ledger",
       "-v", f"{host_path(ledger)}:/ledger", "trial-gateway")
    sh("docker", "network", "connect", "bridge", GATEWAY)  # the gateway alone has a route out
    sh("docker", "start", GATEWAY)


def stop_gateway() -> None:
    sh("docker", "rm", "-f", GATEWAY, check=False)


async def start_sandbox(name: str, image: str, env: dict[str, str]) -> None:
    args = [a for k, v in env.items() for a in ("-e", f"{k}={v}")]
    code, _, err = await ash("docker", "run", "-d", "--init", "--name", name, "--network", NETWORK, *LIMITS,
                             *args, image, "sleep", "infinity")
    if code != 0:
        raise RuntimeError(f"cannot start {name}: {err.strip()}")


def safe_concurrency(requested: int) -> int:
    """Each concurrent run can hold a sandbox and a grading container at once. Keep their limits, plus about a
    gigabyte for the gateway and the VM itself, inside the memory the Docker VM has."""
    out = sh("docker", "info", "--format", "{{.MemTotal}}", check=False).stdout.strip()
    if not out.isdigit():
        return requested
    per_run = 2 * int(CONTAINER_MEMORY.rstrip("g")) * 1024**3
    return max(1, min(requested, (int(out) - 1024**3) // per_run))


async def remove(name: str) -> None:
    await ash("docker", "rm", "-f", name)


def proxy_env(run_id: str) -> dict[str, str]:
    proxy = f"http://{run_id}@{GATEWAY}:3128"
    return {"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy, "https_proxy": proxy, "http_proxy": proxy,
            "NO_PROXY": GATEWAY, "no_proxy": GATEWAY, "NODE_USE_ENV_PROXY": "1"}
