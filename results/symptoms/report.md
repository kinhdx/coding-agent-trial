# Trial symptoms

36 runs over 4 tasks. Resolved means the patch applies, every hidden test passes and the original suite still passes. Costs are computed by the gateway from the usage each provider returned.

| Harness | Model | Resolved | Cost (USD) | USD per resolved | Median agent time (s) | Median tool calls | Out-of-scope edits | Hidden pass, suite broken | Blocked egress | Errors | Time limit |
|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-code | claude-haiku-5-5, claude-sonnet-5-5 | 12/12 (100%) | 1.18 | 0.098 | 48 | 6 | 0 | 0 | 0 | 0 | 0 |
| dsh | deepseek-v4-pro | 12/12 (100%) | 1.61 | 0.134 | 175 | 31 | 0 | 0 | 0 | 0 | 0 |
| grok-build | grok-4.6, grok-build-0.1 | 12/12 (100%) | 3.63 | 0.302 | 239 | 37 | 0 | 0 | 0 | 2 | 0 |

Median session setup before the agent's turn, mostly the adapter installing its CLI in the sandbox (s): claude-code -, dsh -, grok-build -

Unpriced model calls (no usage in the response or no price entry): grok-build 12

Model calls the harness closed before the provider sent usage (cost unknown, not in the totals): claude-code 1, grok-build 11

## By task

| Task | claude-code | dsh | grok-build |
|---|---|---|---|
| loan-card-without-expiry | pass, pass, pass | pass, pass, pass | pass, pass, pass |
| loan-incomplete-review-queue | pass, pass, pass | pass, pass, pass | pass, pass, pass |
| registry-unreadable-manifest | pass, pass, pass | pass, pass, pass | pass, pass, pass |
| triage-provider-outage | pass, pass, pass | pass, pass, pass | pass, pass, pass |

## Errors

- symptoms.triage-provider-outage.grok-build.1: RequestError: Internal error
- symptoms.loan-card-without-expiry.grok-build.2: RequestError: Internal error
