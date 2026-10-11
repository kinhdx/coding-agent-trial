# Harness radar, October 2026

One entry per harness measured in two trials on 2026-10-11: `main` (11 tasks whose bug reports name the
behaviour to change, two attempts each) and `symptoms` (4 tasks whose reports describe only what a user sees,
three attempts each). Rings follow the usual radar meaning: **Trial** means use it in a pilot on real work
with review, **Assess** means keep measuring before a pilot, **Hold** means do not start new use.

Neither task set separated the harnesses on quality: all three resolved all 34 of their runs, including the
reports that leave the cause to be found. The calls below rest on cost, time, containment and maturity of the
release, and each one names what would change it.

| Harness | Ring | Registry entry |
|---|---|---|
| Claude Code (claude-sonnet-5-5) | Trial | [validated](https://github.com/kinhdx/agent-asset-registry/blob/main/assets/coding-agent-claude-code/asset.yaml) |
| Grok Build (grok-build-0.1) | Trial, cost-capped | [validated](https://github.com/kinhdx/agent-asset-registry/blob/main/assets/coding-agent-grok-build/asset.yaml) |
| dsh (deepseek-v4-pro) | Assess | [experimental](https://github.com/kinhdx/agent-asset-registry/blob/main/assets/coding-agent-dsh/asset.yaml) |

## Claude Code: Trial

- Fastest in both trials: median 41 s and 5 tool calls in `main`, 48 s and 6 in `symptoms`. 0.113 and
  0.098 USD per fix; the cheapest of the three when the cause had to be found.
- Asks for permission before tools, so the sandbox policy (no fetch tools, no writes outside the workspace)
  applies on top of the network isolation.
- Needs `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`; without it the CLI tries to reach `api.anthropic.com`
  directly, which the proxy refused in the HarnessAgent check.
- Would move to Hold if a harder task set shows a resolved rate below 80%.

## Grok Build: Trial, with a per-run cost cap

- Resolved everything, but cost the most in both trials: 0.192 USD per fix in `main` and 0.302 in
  `symptoms`, against a median of 262 s and 32 tool calls in `main`.
- Cost spread is wide: 0.07 to 0.69 USD per run in `main`, against a median of 0.18 USD. A pilot should set a
  per-run cap.
- The CLI closes some streams before the provider sends usage (11 calls in each trial), so a part of its
  cost is invisible to a gateway that prices from usage. Billing totals from the provider dashboard are the
  check.
- Would move to Assess if the closed-stream share grows, or if a harder set still shows no quality edge to pay
  for.

## dsh: Assess

- Cheapest when the report names the behaviour: 0.078 USD per fix in `main` (DeepSeek peak rate), median
  160 s and 18 tool calls. When the cause had to be found its median rose to 31 tool calls and 0.134 USD per
  fix, above Claude Code.
- Two reasons it is not in Trial despite meeting every threshold: the version measured is 0.2.0-rc.2, a
  release candidate, and in `workspace-write` mode it runs tools without asking for permission, so its
  containment is the sandbox and the network alone.
- Its shipped ACP profile pins `deepseek-v4-flash`; reaching `deepseek-v4-pro` needs a config patch.
- Would move to Trial with a stable release and a permission mode that asks before tools, or once the
  sandbox and network controls are accepted as the only control for this use.

## What to measure next

- Tasks that fail for some harness. Symptom-only reports on single-service bugs were not enough; the next
  step is bugs whose cause sits in a different module from the symptom, or in configuration rather than code.
- Agent time on a machine where runs do not share CPUs.
- Provider billing totals against the gateway's totals, to size the cost Grok Build's closed streams hide.
