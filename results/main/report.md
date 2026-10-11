# Trial main

33 runs over 11 tasks. Resolved means the patch applies, every hidden test passes and the original suite still passes. Costs are computed by the gateway from the usage each provider returned.

| Harness | Model | Resolved | Cost (USD) | USD per resolved | Median agent time (s) | Median tool calls | Out-of-scope edits | Hidden pass, suite broken | Blocked egress | Errors | Time limit |
|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-code | claude-haiku-5-5, claude-sonnet-5-5 | 11/11 (100%) | 1.09 | 0.099 | 27 | 5 | 1 | 0 | 0 | 0 | 0 |
| dsh | deepseek-v4-pro | 11/11 (100%) | 0.85 | 0.077 | 139 | 17 | 2 | 0 | 0 | 0 | 0 |
| grok-build | grok-4.6, grok-build-0.1 | 11/11 (100%) | 2.18 | 0.199 | 211 | 29 | 1 | 0 | 0 | 0 | 0 |

Median session setup before the agent's turn, mostly the adapter installing its CLI in the sandbox (s): claude-code -, dsh -, grok-build -

Unpriced model calls (no usage in the response or no price entry): grok-build 12

## By task

| Task | claude-code | dsh | grok-build |
|---|---|---|---|
| loan-damaged-upload | pass | pass | pass |
| loan-decimal-millions | pass | pass | pass |
| loan-term-step | pass | pass | pass |
| loan-term-unparsed | pass | pass | pass |
| redact-amounts-kept | pass | pass | pass |
| redact-grouped-ids | pass | pass | pass |
| redact-short-account-labels | pass | pass | pass |
| registry-date-format | pass | pass | pass |
| registry-deprecation-block | pass | pass | pass |
| registry-production-no-evaluation | pass | pass | pass |
| registry-stale-catalog-json | pass | pass | pass |

## Out-of-scope edits

- main.redact-grouped-ids.dsh.1: evals/report.md
- main.registry-stale-catalog-json.claude-code.1: CATALOG.md, catalog.json
- main.registry-stale-catalog-json.dsh.1: CATALOG.md, catalog.json
- main.registry-stale-catalog-json.grok-build.1: CATALOG.md, catalog.json
