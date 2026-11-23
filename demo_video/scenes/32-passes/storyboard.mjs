// 32-passes (stage 3): with guard_prompt in log-only mode, a user sends release_review a change description followed by
// a hidden instruction: HTTP 200 (log-only mode does not block). Changes nothing; the policy counts the match,
// which 33-record shows (record it right after this take: record.sh 32-passes && record.sh 33-record 300).
import { command, idle, need, openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['user'];

const INPUT = 'demo_scenes/inputs/change-with-hidden-instruction.txt';

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { release_review: 'APPROVED' }, mode: 'LOG_ONLY', stopped: [] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  await openShell(page, rec, 'user', t);
  await cam.reset('shell', 'the user\'s shell');
  await cam.hold(3000);

  await command(page, `cat ${INPUT}`);
  await idle(page, t.prompt.user, 10000);
  await cam.rows('change', `cat ${INPUT}`, t.prompt.user, { kmax: 1.5 }, 'a change followed by a hidden instruction');
  await cam.hold(8000);
  await command(page, `ask release_review --file ${INPUT}`);
  rec.note('asked');
  if (!(await idle(page, t.prompt.user, 200000))) throw new Error('ask release_review did not end');
  await need(page, 'HTTP 200', 1000, 'ask release_review');
  rec.note('answered');
  await cam.rows('passes', 'ask release_review --file', t.prompt.user, { kmax: 1.4 }, 'log-only mode lets the request through');
  await cam.hold(9000);
}
