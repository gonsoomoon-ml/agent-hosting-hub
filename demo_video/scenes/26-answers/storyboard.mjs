// 26-answers (stage 2): a user asks the approved quality_agent about part P-100: the answer holds the specification the
// shared tool returned. Changes nothing.
import { command, idle, need, openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['user'];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { quality_agent: 'APPROVED' }, reviewing: [], stopped: [] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  await openShell(page, rec, 'user', t);
  await cam.reset('shell', 'the user\'s shell');
  await cam.hold(3000);

  await command(page, 'ask quality_agent "What is the spec of part P-100?"');
  rec.note('asked');
  if (!(await idle(page, t.prompt.user, 200000))) throw new Error('ask quality_agent did not end');
  await need(page, 'HTTP 200', 1000, 'ask quality_agent');
  rec.note('answered');
  await cam.rows('answer', 'ask quality_agent', t.prompt.user, { kmax: 1.5 }, 'quality_agent answers with the part\'s specification');
  await cam.hold(9000);
}
