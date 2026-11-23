// A take starts by checking that the hub is in the state it needs, through a read of the hub (hub_state.py: the
// catalog's records, the reviews running, the company policy's mode, the custom guardrail, the stopped agents), with
// the credentials of the person who records. When it is not, the take stops with one line saying what differs.
//   await needState({ records: { release_review: 'absent' }, reviewing: [], mode: null, attached: false, stopped: [] });
import { execFile } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');

export async function hubState() {
  try {
    const { stdout } = await promisify(execFile)('uv', ['run', '--quiet', '--project', ROOT, 'python', '-I',
      path.join(ROOT, 'demo_video', 'scenes', 'lib', 'hub_state.py')], { timeout: 120000 });
    return JSON.parse(stdout);
  } catch (error) {
    const said = `${error.stderr || ''}${error.stdout || ''}`.trim().split('\n').pop() || error.message;
    throw new Error(`state: ${said}`);
  }
}

const list = v => [].concat(v);

/** What differs between the hub's state and `want` ({records: {name: status | [statuses] | 'absent'}, reviewing:
 * [agents], mode: null | 'LOG_ONLY' | 'ACTIVE' (as SSM holds it), attached: bool, stopped: [agents]}; a key left out
 * is not checked). */
export function differences(s, want) {
  const wrong = [];
  for (const [name, status] of Object.entries(want.records ?? {})) {
    const got = s.records[name]?.status ?? 'absent';
    if (!list(status).includes(got)) wrong.push(`${name} is ${got}, not ${list(status).join(' or ')}`);
  }
  const same = (a, b) => [...a].sort().join(',') === [...b].sort().join(',');
  if ('reviewing' in want && !same(s.reviewing, want.reviewing)) {
    wrong.push(`reviews running: ${s.reviewing.join(', ') || 'none'} (this take needs ${want.reviewing.join(', ') || 'none'})`);
  }
  if ('mode' in want && (s.mode ?? null) !== want.mode) wrong.push(`guard_prompt is ${s.mode ?? 'off'}, not ${want.mode ?? 'off'}`);
  if ('attached' in want && s.attached !== want.attached) wrong.push(`the custom guardrail is ${s.attached ? 'attached' : 'detached'}`);
  if ('stopped' in want && !same(s.stopped, want.stopped)) wrong.push(`stopped: ${s.stopped.join(', ') || 'none'}`);
  return wrong;
}

export async function needState(want) {
  const s = await hubState();
  const wrong = differences(s, want);
  if (wrong.length) {
    const line = `state: not what this take needs: ${wrong.join('; ')}`;
    console.error(line);
    throw new Error(line);
  }
  console.log(`state: as this take needs (${Object.keys(want).join(', ')})`);
  return s;
}
