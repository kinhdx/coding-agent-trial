# 0001: The gateway holds the keys, the sandbox gets placeholders

## Context

A coding agent runs shell commands chosen by a model, against a repository it has just been handed. Anything
in its environment can end up in a command, a file or a request to a host the agent picked. A trial also has
to answer two questions the harnesses do not answer for you: what each run cost, and whether the agent tried
to reach anything beyond the model provider.

## Decision

Every sandbox joins an internal Docker network with no route out. One container, the gateway, sits on that
network and on the host bridge, and it is the only holder of the provider keys.

- Harnesses are configured with the gateway as their provider base URL, `http://gateway:8080/<run id>/<provider>`,
  and a placeholder key. The gateway drops the incoming credential headers, adds the real key and relays the
  response as it streams.
- The gateway reads the usage block of every response (Anthropic Messages, chat completions and Responses
  formats), prices it from `config/prices.yaml` and writes one ledger line per call with the run id taken from
  the path. Once the ledger total reaches the budget it answers 429 without calling the provider.
- Sandboxes get `HTTPS_PROXY` pointing at the gateway's CONNECT proxy, with the run id as the proxy user name.
  The proxy tunnels only hosts on its allowlist, which is empty for ACP runs, and records every attempt.
- The ACP client answers permission requests by policy: no network fetch tools, no writes outside `/work`.

## Consequences

- A key cannot leak from a run, because no run ever had one. The placeholder is visible in every transcript,
  and that is fine.
- Cost and egress are measured outside the harness, the same way for all of them, so one harness's own
  accounting cannot flatter it.
- A harness that opens a socket without honouring the proxy variables fails to connect instead of reaching
  the internet. The internal network has no DNS for outside names, so such attempts never reach the proxy log.
  The ledger shows them only as missing work.
- The permission policy helps only for harnesses that ask. dsh in `workspace-write` mode runs its tools in the
  workspace without asking, so for dsh the containment is the sandbox and the network alone.
- Prices are a dated copy of the providers' pages. Requests that return no usage, or name a model with no price
  entry, are counted as unpriced calls and listed in the report instead of being priced at zero silently.
- HarnessAgent runs (`ts/`) need the npm registry, because the adapters install their CLI when a session
  starts. Those runs get `registry.npmjs.org` on the allowlist and nothing else.
