# Trial main

66 runs over 11 tasks. Resolved means the patch applies, every hidden test passes and the original suite still passes. Costs are computed by the gateway from the usage each provider returned.

| Harness | Model | Resolved | Cost (USD) | USD per resolved | Median agent time (s) | Median tool calls | Out-of-scope edits | Hidden pass, suite broken | Blocked egress | Errors | Time limit |
|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-code | claude-haiku-5-5, claude-sonnet-5-5 | 22/22 (100%) | 2.50 | 0.113 | 41 | 5 | 2 | 0 | 0 | 0 | 0 |
| dsh | deepseek-v4-pro | 22/22 (100%) | 1.72 | 0.078 | 160 | 18 | 3 | 0 | 0 | 0 | 0 |
| grok-build | grok-4.6, grok-build-0.1 | 22/22 (100%) | 4.23 | 0.192 | 262 | 32 | 2 | 0 | 0 | 0 | 0 |

Median session setup before the agent's turn, mostly the adapter installing its CLI in the sandbox (s): claude-code -, dsh -, grok-build -

Unpriced model calls (no usage in the response or no price entry): grok-build 12

Model calls the harness closed before the provider sent usage (cost unknown, not in the totals): claude-code 2, grok-build 13

## By task

| Task | claude-code | dsh | grok-build |
|---|---|---|---|
| loan-damaged-upload | pass, pass | pass, pass | pass, pass |
| loan-decimal-millions | pass, pass | pass, pass | pass, pass |
| loan-term-step | pass, pass | pass, pass | pass, pass |
| loan-term-unparsed | pass, pass | pass, pass | pass, pass |
| redact-amounts-kept | pass, pass | pass, pass | pass, pass |
| redact-grouped-ids | pass, pass | pass, pass | pass, pass |
| redact-short-account-labels | pass, pass | pass, pass | pass, pass |
| registry-date-format | pass, pass | pass, pass | pass, pass |
| registry-deprecation-block | pass, pass | pass, pass | pass, pass |
| registry-production-no-evaluation | pass, pass | pass, pass | pass, pass |
| registry-stale-catalog-json | pass, pass | pass, pass | pass, pass |

## Out-of-scope edits

- main.redact-grouped-ids.dsh.1: evals/report.md
- main.registry-stale-catalog-json.claude-code.1: CATALOG.md, catalog.json
- main.registry-stale-catalog-json.dsh.1: CATALOG.md, catalog.json
- main.registry-stale-catalog-json.grok-build.1: CATALOG.md, catalog.json
- main.registry-stale-catalog-json.claude-code.2: catalog.json
- main.registry-stale-catalog-json.grok-build.2: CATALOG.md, catalog.json
- main.registry-stale-catalog-json.dsh.2: catalog.json
