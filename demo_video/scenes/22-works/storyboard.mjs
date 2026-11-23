// 22-works (stage 2): a user of a team asks the hosted release_review through the agent gateway, with a change to review:
// HTTP 200 and the agent's answer. Changes nothing.
import { command, idle, need, openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['user'];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { release_review: 'APPROVED' }, stopped: [] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  await openShell(page, rec, 'user', t);
  await cam.reset('shell', 'the user\'s shell');
  await cam.hold(3000);

  await command(page, 'cat demo_scenes/inputs/change-ok.txt');
  await idle(page, t.prompt.user, 10000);
  await cam.rows('change', 'cat demo_scenes/inputs/change-ok.txt', t.prompt.user, { kmax: 1.5 }, 'the change to review');
  await cam.hold(5000);
  await command(page, 'ask release_review --file demo_scenes/inputs/change-ok.txt');
  rec.note('asked');
  if (!(await idle(page, t.prompt.user, 200000))) throw new Error('ask release_review did not end');
  await need(page, 'HTTP 200', 1000, 'ask release_review');
  rec.note('answered');
  await cam.rows('answer', 'ask release_review --file', t.prompt.user, { kmax: 1.4 }, 'release_review answers');
  await cam.hold(9000);
}
