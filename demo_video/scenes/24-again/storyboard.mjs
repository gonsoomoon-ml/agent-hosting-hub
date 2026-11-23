// 24-again (stage 2): after the rejection, the developer submits quality_agent again in its fixed version (its
// dependencies without the vulnerable one). Changes the hub: record 25-approved right after this take
// (record.sh 24-again && record.sh 25-approved 720).
import { command, idle, need, openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['dev'];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { quality_agent: 'REJECTED', release_review: 'APPROVED' }, reviewing: [], stopped: [] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  await openShell(page, rec, 'dev', t, { check: '! grep -q jinja2 dev_team/quality_agent/requirements.txt' });
  await cam.reset('shell', 'the developer PC');
  await cam.hold(3000);

  await command(page, 'cat dev_team/quality_agent/requirements.txt');
  await idle(page, t.prompt.dev, 10000);
  await cam.rows('requirements', 'cat dev_team/quality_agent/requirements.txt', t.prompt.dev, { kmax: 1.5 }, 'the fixed dependencies');
  await cam.hold(5000);
  await command(page, 'publish quality_agent');
  rec.note('publish_quality');
  if (!(await idle(page, t.prompt.dev, 120000))) throw new Error('publish quality_agent did not end');
  await need(page, 'is PENDING_APPROVAL', 1000, 'publish quality_agent');
  rec.note('quality_pending');
  await cam.rows('submitted', 'publish quality_agent', 'PENDING_APPROVAL', { kmax: 1.5 }, 'the fixed version submitted');
  await cam.hold(6000);
}
