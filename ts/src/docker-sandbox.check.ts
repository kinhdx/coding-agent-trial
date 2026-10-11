/**
 * Exercises DockerNetworkSandboxSession against a throwaway container: files, run, spawn with streaming
 * output, kill of a process group, and endpoint names.
 *
 *   tsx src/docker-sandbox.check.ts [image]
 */
import assert from 'node:assert/strict';
import { docker, DockerNetworkSandboxSession } from './docker-sandbox';

const image = process.argv[2] ?? 'trial-base';
const container = `sandbox-check-${process.pid}`;

async function text(stream: ReadableStream<Uint8Array>): Promise<string> {
  return new Response(stream).text();
}

const started = await docker(['run', '-d', '--init', '--name', container, image, 'sleep', 'infinity']);
assert.equal(started.exitCode, 0, started.stderr.toString());
const session = new DockerNetworkSandboxSession(container, '/work', [4000]);
try {
  await session.writeTextFile({ path: '/tmp/check/a b.txt', content: 'one\ntwo\nthree\n' });
  assert.equal(await session.readTextFile({ path: '/tmp/check/a b.txt', startLine: 2, endLine: 2 }), 'two');
  assert.equal(await session.readBinaryFile({ path: '/tmp/check/missing' }), null);
  const bytes = new Uint8Array([0, 255, 10, 13, 1]);
  await session.writeBinaryFile({ path: '/tmp/check/bin', content: bytes });
  assert.deepEqual([...(await session.readBinaryFile({ path: '/tmp/check/bin' }))!], [...bytes]);

  const ran = await session.run({ command: 'echo "$GREETING" && pwd && exit 3', workingDirectory: '/tmp', env: { GREETING: 'hi there' } });
  assert.deepEqual([ran.exitCode, ran.stdout], [3, 'hi there\n/tmp\n']);

  const short = await session.spawn({ command: 'for i in 1 2 3; do echo $i; done; echo err >&2' });
  const [out, err, exit] = await Promise.all([text(short.stdout), text(short.stderr), short.wait()]);
  assert.deepEqual([out, err, exit.exitCode], ['1\n2\n3\n', 'err\n', 0]);

  const long = await session.spawn({ command: 'sleep 300 & sleep 300; echo never' });
  const output = text(long.stdout);
  await new Promise(resolve => setTimeout(resolve, 1000));
  await long.kill();
  const killed = await long.wait();
  assert.notEqual(killed.exitCode, 0);
  assert.equal(await output, '');
  const left = await session.run({ command: 'pgrep -c -x sleep || true' });
  assert.equal(left.stdout.trim().split('\n').at(-1), '1', 'only the container command should still sleep');

  assert.equal(await session.getPortUrl({ port: 4000, protocol: 'ws' }), `ws://${container}:4000`);
  await assert.rejects(session.getPortEndpoint({ port: 5000 }));
  console.log('docker sandbox: all checks passed');
} finally {
  await session.destroy();
}
