# Trial smoke

3 runs over 1 tasks. Resolved means the patch applies, every hidden test passes and the original suite still passes. Costs are computed by the gateway from the usage each provider returned.

| Harness | Model | Resolved | Cost (USD) | USD per resolved | Median agent time (s) | Median tool calls | Out-of-scope edits | Hidden pass, suite broken | Blocked egress | Errors | Time limit |
|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-code | claude-haiku-5-5, claude-sonnet-5-5 | 1/1 (100%) | 0.14 | 0.136 | 34 | 4 | 0 | 0 | 0 | 0 | 0 |
| dsh | deepseek-v4-pro | 1/1 (100%) | 0.06 | 0.062 | 92 | 11 | 0 | 0 | 0 | 0 | 0 |
| grok-build | grok-4.6, grok-build-0.1 | 1/1 (100%) | 0.14 | 0.136 | 318 | 32 | 0 | 0 | 0 | 0 | 0 |

Unpriced model calls (no usage in the response or no price entry): grok-build 1

## By task

| Task | claude-code | dsh | grok-build |
|---|---|---|---|
| redact-grouped-ids | pass | pass | pass |
