/**
 * AI SDK harness sandbox backed by a local Docker container, driven through the `docker` CLI.
 *
 * The runner and the sandbox containers share the trial's internal network, so a harness bridge port is
 * reached by container name and nothing is published to the host. The sandbox has no direct route out;
 * its only exits are the gateway's model routes and the gateway's logging CONNECT proxy.
 *
 * There is no `setNetworkPolicy` or `addRequestTransformations`: the network is fixed when the container is
 * created, and provider keys are injected by the gateway, so adapters only ever hand placeholder
 * credentials to the sandbox.
 */
import { spawn as spawnChild } from 'node:child_process';
import { Readable } from 'node:stream';
import type { HarnessV1NetworkSandboxSession, HarnessV1PortEndpoint } from '@ai-sdk/harness';
import {
  extractLines,
  type Experimental_SandboxProcess as SandboxProcess,
  type Experimental_SandboxSession as SandboxSession,
} from '@ai-sdk/provider-utils';

type ExecResult = { exitCode: number; stdout: Buffer; stderr: Buffer };
type ProcessOptions = {
  command: string;
  workingDirectory?: string;
  env?: Record<string, string>;
  abortSignal?: AbortSignal;
};

const MISSING = 44; // exit code used by the read helper when the path is not a regular file

export function docker(args: string[], options: { stdin?: Uint8Array; abortSignal?: AbortSignal } = {}) {
  return new Promise<ExecResult>((resolve, reject) => {
    const child = spawnChild('docker', args, { stdio: ['pipe', 'pipe', 'pipe'], signal: options.abortSignal });
    const out: Buffer[] = [];
    const err: Buffer[] = [];
    child.stdout.on('data', chunk => out.push(chunk));
    child.stderr.on('data', chunk => err.push(chunk));
    child.on('error', reject);
    child.on('close', code => resolve({ exitCode: code ?? -1, stdout: Buffer.concat(out), stderr: Buffer.concat(err) }));
    child.stdin.end(options.stdin ?? undefined);
  });
}

function execArgs(container: string, { workingDirectory, env }: ProcessOptions, interactive = false): string[] {
  const args = ['exec'];
  if (interactive) args.push('-i');
  if (workingDirectory) args.push('-w', workingDirectory);
  for (const [key, value] of Object.entries(env ?? {})) args.push('-e', `${key}=${value}`);
  return [...args, container];
}

export class DockerSandboxSession implements SandboxSession {
  #processes = 0;

  constructor(readonly container: string) {}

  get description(): string {
    return `Docker container ${this.container} on an internal network. Files persist for the lifetime of the container.`;
  }

  async run(options: ProcessOptions): Promise<{ exitCode: number; stdout: string; stderr: string }> {
    options.abortSignal?.throwIfAborted();
    const result = await docker([...execArgs(this.container, options), 'bash', '-c', options.command], {
      abortSignal: options.abortSignal,
    });
    return { exitCode: result.exitCode, stdout: result.stdout.toString('utf8'), stderr: result.stderr.toString('utf8') };
  }

  async spawn(options: ProcessOptions): Promise<SandboxProcess> {
    options.abortSignal?.throwIfAborted();
    // `docker exec` does not stop the process when the client goes away, so the command runs as the leader
    // of its own process group and records its pid; kill() signals the whole group inside the container.
    const pidFile = `/tmp/.sandbox-process-${process.pid}-${++this.#processes}`;
    const wrapper = `echo $$ > ${pidFile}; exec bash -c "$1"`;
    const child = spawnChild(
      'docker',
      [...execArgs(this.container, options), 'setsid', '-w', 'bash', '-c', wrapper, 'sandbox-process', options.command],
      { stdio: ['ignore', 'pipe', 'pipe'] },
    );
    const exited = new Promise<{ exitCode: number }>(resolve =>
      child.on('close', code => resolve({ exitCode: code ?? -1 })),
    );
    const kill = async () => {
      await docker(['exec', this.container, 'bash', '-c', `kill -TERM -- -"$(cat ${pidFile})" 2>/dev/null; true`]);
    };
    options.abortSignal?.addEventListener('abort', () => void kill(), { once: true });
    return {
      pid: child.pid,
      stdout: Readable.toWeb(child.stdout) as ReadableStream<Uint8Array>,
      stderr: Readable.toWeb(child.stderr) as ReadableStream<Uint8Array>,
      wait: () => exited,
      kill,
    };
  }

  async readBinaryFile({ path, abortSignal }: { path: string; abortSignal?: AbortSignal }): Promise<Uint8Array | null> {
    const result = await docker(
      ['exec', this.container, 'bash', '-c', `test -f "$1" || exit ${MISSING}; cat -- "$1"`, 'read', path],
      { abortSignal },
    );
    if (result.exitCode === MISSING) return null;
    if (result.exitCode !== 0) throw new Error(`reading ${path} failed: ${result.stderr.toString('utf8').trim()}`);
    return new Uint8Array(result.stdout.buffer, result.stdout.byteOffset, result.stdout.byteLength);
  }

  async readFile(options: { path: string; abortSignal?: AbortSignal }): Promise<ReadableStream<Uint8Array> | null> {
    const bytes = await this.readBinaryFile(options);
    return bytes == null ? null : (Readable.toWeb(Readable.from([bytes])) as ReadableStream<Uint8Array>);
  }

  async readTextFile(options: {
    path: string;
    encoding?: string;
    startLine?: number;
    endLine?: number;
    abortSignal?: AbortSignal;
  }): Promise<string | null> {
    const bytes = await this.readBinaryFile(options);
    if (bytes == null) return null;
    const text = Buffer.from(bytes).toString((options.encoding ?? 'utf-8') as BufferEncoding);
    return extractLines({ text, startLine: options.startLine, endLine: options.endLine });
  }

  async writeBinaryFile({ path, content, abortSignal }: { path: string; content: Uint8Array; abortSignal?: AbortSignal }) {
    const result = await docker(
      ['exec', '-i', this.container, 'bash', '-c', 'mkdir -p -- "$(dirname -- "$1")" && cat > "$1"', 'write', path],
      { stdin: content, abortSignal },
    );
    if (result.exitCode !== 0) throw new Error(`writing ${path} failed: ${result.stderr.toString('utf8').trim()}`);
  }

  async writeFile(options: { path: string; content: ReadableStream<Uint8Array>; abortSignal?: AbortSignal }) {
    const chunks: Uint8Array[] = [];
    for await (const chunk of options.content) chunks.push(chunk);
    await this.writeBinaryFile({ ...options, content: Buffer.concat(chunks) });
  }

  async writeTextFile(options: { path: string; content: string; encoding?: string; abortSignal?: AbortSignal }) {
    await this.writeBinaryFile({
      ...options,
      content: Buffer.from(options.content, (options.encoding ?? 'utf-8') as BufferEncoding),
    });
  }
}

export class DockerNetworkSandboxSession extends DockerSandboxSession implements HarnessV1NetworkSandboxSession {
  readonly id: string;
  #ports: number[];

  constructor(
    container: string,
    readonly defaultWorkingDirectory: string,
    ports: number[],
  ) {
    super(container);
    this.id = container;
    this.#ports = [...ports];
  }

  get ports(): ReadonlyArray<number> {
    return this.#ports;
  }

  restricted(): SandboxSession {
    return new DockerSandboxSession(this.container);
  }

  getPortEndpoint = async ({ port, protocol = 'http' }: { port: number; protocol?: 'http' | 'https' | 'ws' }) => {
    if (!this.#ports.includes(port)) {
      throw new Error(`Port ${port} is not exposed on ${this.container}. Exposed ports: [${this.#ports.join(', ')}].`);
    }
    // Traffic stays on the internal network, which carries no TLS; https is served as plain http.
    const scheme = protocol === 'ws' ? 'ws' : 'http';
    return { url: `${scheme}://${this.container}:${port}` } satisfies HarnessV1PortEndpoint;
  };

  getPortUrl = async (options: { port: number; protocol?: 'http' | 'https' | 'ws' }) =>
    (await this.getPortEndpoint(options)).url;

  // Every port of a container is reachable on the internal network, so changing the list needs no other work.
  setPorts = async (ports: ReadonlyArray<number>) => {
    this.#ports = [...ports];
  };

  stop = async () => {
    await docker(['stop', '-t', '5', this.container]);
  };

  destroy = async () => {
    await docker(['rm', '-f', this.container]);
  };
}
