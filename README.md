# coding-agent-trial

Runs real bug fixes from three service repositories through coding-agent harnesses, each in its own
sandbox with no network route out, and records for every run whether the fix passes the tests written for
it, what the model calls cost and how long the agent took.

It answers a narrow question before a team lets a harness near its code: on our repositories, with our kind
of bugs, how often does it produce a fix that passes, at what price, and does it try to reach anything it
should not.

## Results

Trial `main`: 11 tasks, one attempt each, three harnesses driven over the Agent Client Protocol.
Full table in [results/main/report.md](results/main/report.md).

| Harness | Model | Resolved | Cost (USD) | USD per resolved | Median agent time (s) | Median tool calls |
|---|---|---|---|---|---|---|
| Claude Code | claude-sonnet-5-5 | 11/11 | 1.09 | 0.099 | 27 | 5 |
| dsh | deepseek-v4-pro | 11/11 | 0.85 | 0.077 | 139 | 17 |
| Grok Build | grok-build-0.1 | 11/11 | 2.18 | 0.199 | 211 | 29 |

What these numbers support:

- All three fixed every task, so this task set does not separate them on quality. It separates them on cost
  and time: dsh was cheapest per fix, Claude Code fastest with the fewest tool calls, Grok Build slowest and
  most expensive.
- No run tried to reach a host outside the provider route.
- Four runs edited files outside `src/` and `tests/`. On the task that adds a staleness check for the
  committed catalog, all three harnesses also regenerated `CATALOG.md` and `catalog.json`. dsh rewrote
  `evals/report.md` on another task by running the evaluation script; the text is unchanged.
- Grok Build's total misses 12 calls whose stream the CLI closed before the provider sent usage. The gateway
  now records this case (see [Cost accounting](#cost-accounting)); those 12 lines predate the change.
- One attempt per task. The agent times were measured with three sandboxes sharing 8 CPUs, so read them as a
  ranking, not as a latency figure.

Trial `sdk-check` runs one task through the AI SDK HarnessAgent adapters for Claude Code and Grok Build
([results/sdk-check/report.md](results/sdk-check/report.md)). Both resolved it. Before the agent's turn, the
adapters spent 161 s (Claude Code) and 58 s (Grok Build) installing their CLI in the sandbox, against 17 s and
103 s for the turn itself.

## How a run works

```
 host: trial CLI ──── starts ───► sandbox (internal network, no DNS out)
                                    harness CLI, placeholder key
                                    base URL http://gateway:8080/<run id>/<provider>
                                    HTTPS_PROXY http://<run id>@gateway:3128
                                          │
                                          ▼
                                  gateway (internal network + bridge)
                                    adds the real key, relays the stream
                                    prices usage, writes results/ledger/calls.jsonl
                                    CONNECT allowlist, writes results/ledger/egress.jsonl
                                    answers 429 once the budget is spent
                                          │
                                          ▼
                                  Anthropic, xAI, DeepSeek APIs
```

1. The sandbox checks out the task's starting commit into a fresh one-commit repository at `/work`, so the
   fix cannot be read from history.
2. The harness gets the bug report as its prompt and one turn to fix it. The ACP client answers permission
   requests by policy: no network fetch tools, no writes outside `/work`.
3. The workspace diff is saved and graded in a new container with no network. The grader applies the diff,
   restores `tests/` from the starting commit, adds the hidden tests that came with the real fix, then runs
   them and the original suite.
4. A run is resolved when the diff applies, every hidden test passes and the original suite still passes.

Each task in [tasks/](tasks/) records the starting commit, the fix commit, the bug report and the hidden
tests. `trial validate` checks that every hidden test fails at the starting commit and passes with the real
fix.

## Harnesses

| Name | Driven through | Version | Model |
|---|---|---|---|
| `claude-code` | ACP, `@agentclientprotocol/claude-agent-acp` | 0.89.1 | claude-sonnet-5-5 |
| `grok-build` | ACP, `@xai-official/grok` | 1.0.49 | grok-build-0.1 |
| `dsh` | ACP, `@deepseek-ai/dsh` | 0.2.0-rc.2 | deepseek-v4-pro |
| `sdk-claude-code` | AI SDK HarnessAgent, `@ai-sdk/harness-claude-code` | 1.0.152 | claude-sonnet-5-5 |
| `sdk-grok-build` | AI SDK HarnessAgent, `@ai-sdk/harness-grok-build` | 1.0.86 | grok-build-0.1 |

Claude Code also sends small background requests to claude-haiku-5-5, and Grok Build to grok-4.6. Both are
priced and included in the totals.

dsh in `workspace-write` mode runs its tools without asking for permission, so for dsh the containment is the
sandbox and the network alone.

## Cost accounting

The gateway prices every call from the usage block in the provider's response, using the dated prices in
[config/prices.yaml](config/prices.yaml); the harnesses' own accounting is not used. DeepSeek is priced at its
peak rate. A call with no usage block is never priced at zero. The report lists it apart:

- unpriced: the response had no usage, or the model has no price entry;
- closed early: the harness closed the stream before the final usage chunk, so the cost is unknown.

## Running it

Requirements: Docker, [uv](https://docs.astral.sh/uv/), and Node 24 for the `ts/` runner's type check.
Put the provider keys in `.env` (`ANTHROPIC_API_KEY`, `XAI_API_KEY`, `DEEPSEEK_API_KEY`); only the gateway
container receives them.

```
uv sync
uv run trial build                      # sandbox, harness, gateway and runner images
uv run trial validate                   # hidden tests fail at the start commit, pass with the fix
uv run trial run main --attempts 3 --concurrency 2 --budget 20
uv run trial run-agent sdk --task registry-deprecation-block
uv run trial report main
```

A trial resumes: runs already in `results/<trial>/runs.jsonl` are skipped. The budget covers every trial that
shares `results/ledger`. Each sandbox is limited to 4 GB of memory and 2 CPUs; size `--concurrency` to the
memory Docker has.

## Layout

```
config/prices.yaml     dated provider prices
sandbox/               images: base with the target repositories, one per harness, gateway, ts runner
src/trial/             CLI, ACP client, gateway, grading, report
tasks/                 one YAML file per bug fix
ts/                    HarnessAgent runner and the Docker sandbox it drives
results/               ledger, one record per run and the reports (run folders with transcripts stay local)
docs/decisions/        why it is built this way
```

## Harness radar

[docs/harness-radar.md](docs/harness-radar.md) turns the results into a call per harness: Claude Code and
Grok Build in Trial, dsh in Assess, with what would change each call. The three configurations are
registered in [agent-asset-registry](https://github.com/kinhdx/agent-asset-registry/blob/main/CATALOG.md).

## Decisions

- [0001: The gateway holds the keys, the sandbox gets placeholders](docs/decisions/0001-gateway-holds-the-keys.md)
- [0002: Tasks come from real fixes, graded by the tests written for them](docs/decisions/0002-tasks-from-fix-history.md)
- [0003: ACP for the trial, HarnessAgent alongside it](docs/decisions/0003-acp-and-harness-agent.md)
