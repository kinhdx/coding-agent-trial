# Trial sdk-check

2 runs over 1 tasks. Resolved means the patch applies, every hidden test passes and the original suite still passes. Costs are computed by the gateway from the usage each provider returned.

| Harness | Model | Resolved | Cost (USD) | USD per resolved | Median agent time (s) | Median tool calls | Out-of-scope edits | Hidden pass, suite broken | Blocked egress | Errors | Time limit |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sdk-claude-code | claude-sonnet-5-5 | 1/1 (100%) | 0.11 | 0.109 | 17 | 4 | 0 | 0 | 0 | 0 | 0 |
| sdk-grok-build | grok-4.6, grok-build-0.1 | 1/1 (100%) | 0.08 | 0.078 | 103 | 26 | 0 | 0 | 0 | 0 | 0 |

Median session setup before the agent's turn, mostly the adapter installing its CLI in the sandbox (s): sdk-claude-code 161, sdk-grok-build 58

Model calls the harness closed before the provider sent usage (cost unknown, not in the totals): sdk-grok-build 1

## By task

| Task | sdk-claude-code | sdk-grok-build |
|---|---|---|
| registry-deprecation-block | pass | pass |
