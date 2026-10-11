"""Summarises <trial>/runs.jsonl into a Markdown report: one row per harness, then one row per task."""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path


def load_runs(trial_dir: Path) -> list[dict]:
    path = trial_dir / "runs.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _median(values: list[float]) -> str:
    return f"{statistics.median(values):.0f}" if values else "-"


def summarise(runs: list[dict]) -> list[dict]:
    by_harness: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by_harness[r["harness"]].append(r)
    rows = []
    for name, rs in sorted(by_harness.items()):
        resolved = [r for r in rs if r["grade"]["resolved"]]
        cost = sum(r.get("cost_usd", 0) for r in rs)
        rows.append({
            "harness": name,
            "model": ", ".join(sorted({m for r in rs for m in r.get("models", [])})) or rs[0]["model"],
            "runs": len(rs),
            "resolved": len(resolved),
            "rate": len(resolved) / len(rs),
            "cost_usd": cost,
            "cost_per_resolved": cost / len(resolved) if resolved else None,
            "median_agent_s": _median([r["agent_seconds"] for r in rs if r.get("agent_seconds")]),
            "median_setup_s": _median([r["setup_seconds"] for r in rs if r.get("setup_seconds")]),
            "median_tool_calls": _median([r["tool_calls"] for r in rs]),
            "out_of_scope_runs": sum(1 for r in rs if r["grade"]["out_of_scope"]),
            "regressions": sum(1 for r in rs if r["grade"]["applied"] and r["grade"]["hidden_total"]
                               and r["grade"]["hidden_passed"] == r["grade"]["hidden_total"]
                               and not r["grade"]["resolved"]),
            "egress_denied_runs": sum(1 for r in rs if r.get("egress_denied")),
            "errors": sum(1 for r in rs if r.get("error")),
            "time_limit": sum(1 for r in rs if r.get("stop_reason") == "time_limit"),
            "unpriced_calls": sum(r.get("unpriced_calls", 0) for r in rs),
            "closed_early_calls": sum(r.get("closed_early_calls", 0) for r in rs),
        })
    return rows


def render(trial_dir: Path) -> str:
    runs = load_runs(trial_dir)
    rows = summarise(runs)
    harnesses = [row["harness"] for row in rows]
    lines = [f"# Trial {trial_dir.name}", "",
             f"{len(runs)} runs over {len({r['task'] for r in runs})} tasks. Resolved means the patch applies, "
             "every hidden test passes and the original suite still passes. Costs are computed by the gateway "
             "from the usage each provider returned.", "",
             "| Harness | Model | Resolved | Cost (USD) | USD per resolved | Median agent time (s) | "
             "Median tool calls | Out-of-scope edits | Hidden pass, suite broken | Blocked egress | Errors | Time limit |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        per = f"{row['cost_per_resolved']:.3f}" if row["cost_per_resolved"] is not None else "-"
        lines.append(f"| {row['harness']} | {row['model']} | {row['resolved']}/{row['runs']} ({row['rate']:.0%}) "
                     f"| {row['cost_usd']:.2f} | {per} | {row['median_agent_s']} | {row['median_tool_calls']} "
                     f"| {row['out_of_scope_runs']} | {row['regressions']} | {row['egress_denied_runs']} "
                     f"| {row['errors']} | {row['time_limit']} |")
    if any(row["median_setup_s"] for row in rows):
        lines += ["", "Median session setup before the agent's turn, mostly the adapter installing its CLI in the "
                  "sandbox (s): " + ", ".join(f"{row['harness']} {row['median_setup_s']}"
                                             for row in rows if row["median_setup_s"])]
    if any(row["unpriced_calls"] for row in rows):
        lines += ["", "Unpriced model calls (no usage in the response or no price entry): "
                  + ", ".join(f"{row['harness']} {row['unpriced_calls']}" for row in rows if row["unpriced_calls"])]
    if any(row["closed_early_calls"] for row in rows):
        lines += ["", "Model calls the harness closed before the provider sent usage (cost unknown, not in the "
                  "totals): " + ", ".join(f"{row['harness']} {row['closed_early_calls']}"
                                          for row in rows if row["closed_early_calls"])]
    lines += ["", "## By task", "", "| Task | " + " | ".join(harnesses) + " |",
              "|---|" + "---|" * len(harnesses)]
    cells: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in sorted(runs, key=lambda r: r["attempt"]):
        g = r["grade"]
        mark = "pass" if g["resolved"] else ("error" if r.get("error") and not g["files_changed"] else
                                             f"fail {g['hidden_passed']}/{g['hidden_total']}")
        cells[(r["task"], r["harness"])].append(mark)
    for task in sorted({r["task"] for r in runs}):
        lines.append(f"| {task} | " + " | ".join(", ".join(cells[(task, h)]) or "-" for h in harnesses) + " |")
    notes = [(r["run"], r["error"]) for r in runs if r.get("error")]
    if notes:
        lines += ["", "## Errors", ""] + [f"- {run}: {err[:300]}" for run, err in notes]
    scope = [(r["run"], r["grade"]["out_of_scope"]) for r in runs if r["grade"]["out_of_scope"]]
    if scope:
        lines += ["", "## Out-of-scope edits", ""] + [f"- {run}: {', '.join(files)}" for run, files in scope]
    egress = sorted({t for r in runs for t in r.get("egress_denied", [])})
    if egress:
        lines += ["", "## Blocked egress targets", "", ", ".join(egress)]
    return "\n".join(lines) + "\n"
