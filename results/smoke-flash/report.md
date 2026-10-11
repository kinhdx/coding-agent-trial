# Trial smoke-flash

1 runs over 1 tasks. Resolved means the patch applies, every hidden test passes and the original suite still passes. Costs are computed by the gateway from the usage each provider returned.

| Harness | Model | Resolved | Cost (USD) | USD per resolved | Median agent time (s) | Median tool calls | Out-of-scope edits | Hidden pass, suite broken | Blocked egress | Errors | Time limit |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dsh | deepseek-v4-flash | 1/1 (100%) | 0.03 | 0.030 | 101 | 19 | 0 | 0 | 0 | 0 | 0 |

## By task

| Task | dsh |
|---|---|
| redact-grouped-ids | pass |
