# Harness radar, October 2026

One entry per harness measured in trial `main` (11 tasks, one attempt each, 2026-10-11). Rings follow the
usual radar meaning: **Trial** means use it in a pilot on real work with review, **Assess** means keep
measuring before a pilot, **Hold** means do not start new use.

The task set did not separate the harnesses on quality: all three resolved 11 of 11. The calls below rest
on cost, time, containment and maturity of the release, and each one names what would change it.

| Harness | Ring | Registry entry |
|---|---|---|
| Claude Code (claude-sonnet-5-5) | Trial | [validated](https://github.com/kinhdx/agent-asset-registry/blob/main/assets/coding-agent-claude-code/asset.yaml) |
| Grok Build (grok-build-0.1) | Trial, cost-capped | [validated](https://github.com/kinhdx/agent-asset-registry/blob/main/assets/coding-agent-grok-build/asset.yaml) |
| dsh (deepseek-v4-pro) | Assess | [experimental](https://github.com/kinhdx/agent-asset-registry/blob/main/assets/coding-agent-dsh/asset.yaml) |

## Claude Code: Trial

- Median 27 s and 5 tool calls per task, the shortest of the three; 0.099 USD per fix.
- Asks for permission before tools, so the sandbox policy (no fetch tools, no writes outside the workspace)
  applies on top of the network isolation.
- Needs `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`; without it the CLI tries to reach `api.anthropic.com`
  directly, which the proxy refused in the HarnessAgent check.
- Would move to Hold if a harder task set shows a resolved rate below 80%.

## Grok Build: Trial, with a per-run cost cap

- Resolved everything, but at 0.199 USD per fix, twice Claude Code, with a median of 211 s and 29 tool calls.
- Cost spread is wide: one run cost 0.69 USD against a median of 0.17 USD. A pilot should set a per-run cap.
- The CLI closes some streams before the provider sends usage (12 calls in the trial), so a part of its cost
  is invisible to a gateway that prices from usage. Billing totals from the provider dashboard are the check.
- Would move to Assess if the closed-stream share grows, or if a harder set shows no quality edge to pay for.

## dsh: Assess

- Cheapest at 0.077 USD per fix (DeepSeek peak rate), median 139 s and 17 tool calls.
- Two reasons it is not in Trial despite meeting every threshold: the version measured is 0.2.0-rc.2, a
  release candidate, and in `workspace-write` mode it runs tools without asking for permission, so its
  containment is the sandbox and the network alone.
- Its shipped ACP profile pins `deepseek-v4-flash`; reaching `deepseek-v4-pro` needs a config patch.
- Would move to Trial with a stable release and a permission mode that asks before tools, or once the
  sandbox and network controls are accepted as the only control for this use.

## What to measure next

- A harder task set: fixes that span several files, or bug reports that leave the cause to be found. With
  every harness at 100%, the current set cannot show a quality difference.
- Attempts 2 and 3 on each task, to see how stable the results and costs are.
- Agent time on a machine where runs do not share CPUs.
