# 0003: ACP for the trial, HarnessAgent alongside it

## Context

There are two ways to drive a coding agent from a program without writing the agent loop yourself.

- The Agent Client Protocol (ACP): the harness runs as a subprocess and speaks JSON-RPC over stdio. Claude
  Code (through `claude-agent-acp`), Grok Build and dsh all implement it. The client creates a session, sends
  a prompt, receives tool calls and file edits as notifications, and answers permission requests.
- AI SDK HarnessAgent: a TypeScript class that wraps a harness behind the AI SDK stream API. An adapter per
  harness (`@ai-sdk/harness-claude-code`, `@ai-sdk/harness-grok-build`) installs the harness CLI and a small
  bridge in a sandbox it is given, then streams the turn back as AI SDK parts.

The trial needs the same containment, cost accounting and grading for every harness, and a way to tell
whether a difference in results comes from the harness or from the way it was driven.

## Decision

ACP drives the main trial. The Python CLI starts each harness with `docker exec -i` in its sandbox and talks
to it with the `agent-client-protocol` package. All three harnesses go through one client, one permission
policy and one transcript format.

HarnessAgent runs alongside it for the two harnesses that have an adapter. `trial run-agent` writes a jobs
file and starts the `ts/` runner in a container on the internal network; the runner drives each job through
HarnessAgent against a Docker sandbox, and the Python side grades the run folders and prices the ledger
lines exactly as for ACP runs. These rows carry an `sdk-` prefix so both kinds appear in one report.

- The sandbox interface the adapters need (run a command, spawn a process, read and write files, expose a
  port) is implemented in `ts/src/docker-sandbox.ts` with `docker exec`. The bridge port is reached by
  container name on the internal network.
- The adapters install their CLI with pnpm when a session starts, so these runs get `registry.npmjs.org` on
  the egress allowlist. The setup time is recorded apart from the agent's turn.
- The Docker sandbox does not implement request transformations, so the adapters fall back to forwarding
  credential variables into the sandbox. Those variables hold the placeholder key and the gateway URL, so
  the real key still never enters it.

## Consequences

- One task through both paths gave the same verdict for both harnesses (`results/sdk-check`, compared with
  `results/main`). The HarnessAgent runs spent 161 s (Claude Code) and 58 s (Grok Build) on setup before the
  turn began. ACP sandboxes have the CLI baked into the image and spend nothing on it.
- The runner answers no tool approvals and sets no permission mode, so the adapters' defaults apply; the
  Grok Build adapter, built on `@ai-sdk/harness-acp`, defaults to allowing everything. For HarnessAgent runs, as for dsh, the containment is the
  sandbox and the network.
- HarnessAgent covers two of the three harnesses. dsh has no adapter, which is the main reason ACP stays the
  path for the comparison.
- Adapter versions move quickly (the Claude Code adapter was at 1.0.152 when this was written). They are
  pinned in `ts/package-lock.json`.
