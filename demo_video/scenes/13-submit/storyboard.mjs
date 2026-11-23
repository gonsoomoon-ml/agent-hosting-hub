// 13-submit (stage 1): the developer submits two agents for hosting: release_review first, then quality_agent in its
// version with a vulnerable dependency (v1-vulnerable). Both records read PENDING_APPROVAL and their reviews start.
// Changes the hub: record 21-review right after this take (record.sh 13-submit && record.sh 21-review 720).
import { term } from '../lib/plugin.mjs';
import { command, idle, need, openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['dev'];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { release_review: 'absent', quality_agent: 'absent' }, reviewing: [], stopped: [] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  // the repo's quality_agent is in the developer's checkout (run.sh agent quality_agent), with its variants
  await openShell(page, rec, 'dev', t, { check: 'test -f dev_team/quality_agent/variants/v1-vulnerable/requirements.txt' });
  await cam.reset('shell', 'the developer PC');
  await cam.hold(3000);

  await command(page, 'publish release_review');
  rec.note('publish_release');
  if (!(await idle(page, t.prompt.dev, 120000))) throw new Error('publish release_review did not end');
  await need(page, 'is PENDING_APPROVAL', 1000, 'publish release_review');
  rec.note('release_pending');
  await cam.rows('release', 'publish release_review', 'PENDING_APPROVAL', { kmax: 1.5 }, 'release_review submitted');
  await cam.hold(5000);

  await command(page, 'publish quality_agent v1-vulnerable');
  rec.note('publish_quality');
  if (!(await idle(page, t.prompt.dev, 120000))) throw new Error('publish quality_agent did not end');
  const screen = await term.screenText(page);
  if ((screen.match(/is PENDING_APPROVAL/g) || []).length < 2) throw new Error('quality_agent is not PENDING_APPROVAL');
  rec.note('quality_pending');
  await cam.rows('both', 'publish release_review', 'PENDING_APPROVAL', { kmax: 1.5 }, 'both submitted, awaiting approval');
  await cam.hold(6000);
}
