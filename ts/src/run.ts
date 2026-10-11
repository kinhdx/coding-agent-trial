/**
 * Runs trial jobs through AI SDK HarnessAgent adapters.
 *
 *   tsx src/run.ts <jobs.json>
 *
 * `trial run-agent` writes the jobs file (task prompts, run ids, gateway address) and starts this runner in a
 * container on the trial network. For each job the runner starts a sandbox container, prepares the workspace,
 * runs one prompt turn through HarnessAgent, saves the workspace diff and a stream transcript, and removes the
 * container. Grading and cost accounting happen afterwards in the Python side, exactly as for ACP runs.
 */
import { appendFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { HarnessAgent } from '@ai-sdk/harness/agent';
import { createClaudeCode } from '@ai-sdk/harness-claude-code';
import { createGrokBuild } from '@ai-sdk/harness-grok-build';
import { docker, DockerNetworkSandboxSession } from './docker-sandbox';

type Job = {
  run: string;
  repo: string;
  base: string;
  harness: 'claude-code' | 'grok-build';
  model: string;
  prompt: string;
  sandboxEnv: Record<string, string>;
};

type JobsFile = {
  gateway: string;
  placeholderKey: string;
  image: string;
  network: string;
  runsDir: string;
  concurrency: number;
  timeLimitSeconds: number;
  jobs: Job[];
};

const BRIDGE_PORT = 4000;

function harnessFor(job: Job, spec: JobsFile) {
  const base = `${spec.gateway}/${job.run}`;
  switch (job.harness) {
    case 'claude-code':
      return createClaudeCode({
        env: {
          ANTHROPIC_BASE_URL: `${base}/anthropic`,
          ANTHROPIC_API_KEY: spec.placeholderKey,
          // Without this the CLI also calls api.anthropic.com directly, which the proxy refuses.
          CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1',
          DISABLE_AUTOUPDATER: '1',
        },
      });
    case 'grok-build':
      // A flat record is used as the run's authentication environment; the adapter forwards these values
      // to the sandbox, so the CLI talks to this run's gateway route with a placeholder key.
      return createGrokBuild({
        auth: {
          XAI_API_KEY: spec.placeholderKey,
          GROK_XAI_API_BASE_URL: `${base}/xai/v1`,
          GROK_MODELS_BASE_URL: `${base}/xai/v1`,
        },
      });
  }
}

async function startSandbox(container: string, job: Job, spec: JobsFile): Promise<void> {
  await docker(['rm', '-f', container]);
  const env = Object.entries(job.sandboxEnv).flatMap(([key, value]) => ['-e', `${key}=${value}`]);
  const started = await docker([
    'run', '-d', '--init', '--name', container, '--network', spec.network,
    '--memory', '4g', '--cpus', '2', '--pids-limit', '512',
    ...env, spec.image, 'sleep', 'infinity',
  ]);
  if (started.exitCode !== 0) throw new Error(`sandbox start failed: ${started.stderr.toString('utf8').trim()}`);
  const prepared = await docker(['exec', container, 'prepare-workspace.sh', job.repo, job.base]);
  if (prepared.exitCode !== 0) {
    throw new Error(`workspace setup failed: ${prepared.stderr.toString('utf8').trim().slice(-500)}`);
  }
}

async function runJob(job: Job, spec: JobsFile): Promise<void> {
  const runDir = join(spec.runsDir, job.run);
  await mkdir(runDir, { recursive: true });
  const transcript = join(runDir, 'transcript.jsonl');
  const container = `trial-${job.run.replaceAll('.', '-')}`;
  const meta: Record<string, unknown> = { run: job.run, harness: job.harness, model: job.model, error: null };
  const log = (event: string, data: unknown) =>
    appendFile(transcript, JSON.stringify({ ts: Date.now() / 1000, event, data }) + '\n');
  const toolCalls = new Set<string>();
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(new Error('time_limit')), spec.timeLimitSeconds * 1000);
  let setupStarted = 0;
  let agentStarted = 0;
  try {
    await startSandbox(container, job, spec);
    const sandboxSession = new DockerNetworkSandboxSession(container, '/work', [BRIDGE_PORT]);
    const agent = new HarnessAgent({
      harness: harnessFor(job, spec),
      id: job.run,
      model: job.model,
      sandboxConfig: { workDir: '.' },
    });
    // Session setup installs the harness CLI in the sandbox; it is timed apart from the agent's turn.
    setupStarted = Date.now();
    const session = await agent.createSession({ sandboxSession, abortSignal: abort.signal });
    agentStarted = Date.now();
    try {
      const result = await agent.stream({ session, prompt: job.prompt, abortSignal: abort.signal });
      for await (const part of result.stream) {
        if (part.type === 'tool-call') toolCalls.add(part.toolCallId);
        if (part.type === 'finish') meta.stop_reason = part.finishReason;
        if (part.type === 'error') meta.error = String(part.error).slice(0, 1000);
        if (part.type !== 'text-delta' && part.type !== 'reasoning-delta') await log('part', part);
      }
    } finally {
      await session.destroy().catch(error => log('session-destroy-error', String(error)));
    }
  } catch (error) {
    meta.stop_reason = abort.signal.aborted ? 'time_limit' : (meta.stop_reason ?? null);
    meta.error = abort.signal.aborted ? null : `${(error as Error).name}: ${(error as Error).message}`.slice(0, 1000);
  } finally {
    clearTimeout(timer);
  }
  const seconds = (from: number, to: number) => Math.round((to - from) / 100) / 10;
  meta.setup_seconds = setupStarted ? seconds(setupStarted, agentStarted || Date.now()) : null;
  meta.agent_seconds = agentStarted ? seconds(agentStarted, Date.now()) : null;
  meta.tool_calls = toolCalls.size;
  const diff = await docker(['exec', '-w', '/work', container, 'bash', '-c', 'git add -A && git diff --cached --binary HEAD']);
  await writeFile(join(runDir, 'patch.diff'), diff.exitCode === 0 ? diff.stdout : Buffer.alloc(0));
  if (diff.exitCode !== 0) meta.error = `${meta.error ?? ''} diff failed: ${diff.stderr.toString('utf8').trim().slice(-300)}`;
  await docker(['rm', '-f', container]);
  await writeFile(join(runDir, 'agent-run.json'), JSON.stringify(meta, null, 2) + '\n');
  console.log(`${job.run}: ${meta.stop_reason ?? 'stopped'}, ${meta.tool_calls} tool calls${meta.error ? `, error: ${String(meta.error).slice(0, 120)}` : ''}`);
}

async function main(): Promise<void> {
  const spec = JSON.parse(await readFile(process.argv[2], 'utf8')) as JobsFile;
  const queue = [...spec.jobs];
  // Fan out over the jobs with a fixed number of workers; the Python side fans in by reading the run folders.
  const worker = async () => {
    for (let job = queue.shift(); job; job = queue.shift()) await runJob(job, spec);
  };
  await Promise.all(Array.from({ length: Math.max(1, spec.concurrency) }, worker));
}

await main();
