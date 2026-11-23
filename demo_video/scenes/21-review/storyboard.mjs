// 21-review (stage 2): the hosting reviews of the two applications, in real time, on the hub screen. Both applications in
// the list; quality_agent fails at Scan (its vulnerable dependency); release_review passes the seven steps, each with
// the AWS service that runs it, and its record reads APPROVED. A note at every change (a step's new state, the
// failure, the approval): the waits are cut by these notes. Record it right after 13-submit, with 720 s.
import { openPage, strip } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['hub'];

export default async function storyboard({ page, rec, option, maxSeconds }) {
  const s = await needState({ records: { release_review: 'PENDING_APPROVAL', quality_agent: 'PENDING_APPROVAL' },
    mode: null, attached: false, stopped: [] });
  if (!s.reviewing.includes('release_review')) throw new Error('state: the review of release_review is not running');
  texts(option);
  const cam = kit({ page, rec, option });
  const seen = {};
  // a note for each step whose state changed since the last look: <agent>_<step>_<state>
  const changes = async (agent, scope) => {
    const now = await strip(page, scope).catch(() => []);
    const changed = [];
    for (const step of now) {
      const key = `${agent}_${step.name}`;
      if (step.state && seen[key] !== step.state) { seen[key] = step.state; rec.note(`${key}_${step.state}`); changed.push(step); }
    }
    return { now, changed };
  };

  // both applications, both reviews running; quality_agent fails at Scan
  await openPage(page, rec, '/reviews');
  await cam.reset('list', 'both applications in the hosting review');
  await changes('quality_agent', '#app-quality_agent');
  await changes('release_review', '#app-release_review');
  await cam.hold(5000);
  await cam.focus('cards', '#panel-applications', { pad: 12, kmax: 1.4 }, 'both reviews running');
  const t0 = rec.now();
  let failed = false;
  while (rec.now() - t0 < 180) {
    await cam.hold(1000);
    const q = await changes('quality_agent', '#app-quality_agent');
    await changes('release_review', '#app-release_review');
    if (q.now.some(step => step.state === 'failed')) { failed = true; break; }
    if (q.changed.length) await cam.focus('cards', '#panel-applications', { pad: 12, kmax: 1.4 });
  }
  rec.note(failed ? 'quality_failed' : 'quality_not_failed_yet');
  await cam.hold(1500);
  await cam.focus('quality', '#app-quality_agent', { pad: 12, kmax: 1.6 }, 'quality_agent stops at Scan');
  await cam.hold(7000);
  await cam.focus('release_card', '#app-release_review', { pad: 12, kmax: 1.6 }, 'release_review goes on');
  await cam.hold(5000);

  // release_review's review, step by step, until its record reads APPROVED
  await openPage(page, rec, '/reviews/release_review');
  await cam.focus('steps', '#panel-steps', { pad: 12, kmax: 1.7 }, 'the seven steps and their AWS services');
  await changes('release_review', '#panel-steps');
  let approved = false, ended = '';
  while (rec.now() < maxSeconds - 45) {
    await cam.hold(1000);
    const r = await changes('release_review', '#panel-steps');
    const facts = await page.evaluate(() => ({
      record: document.querySelector('#panel-application .pill')?.textContent.trim() || '',
      run: document.querySelector('#panel-steps .review-meta .pill')?.textContent.trim() || '',
    })).catch(() => ({ record: '', run: '' }));
    if (facts.run && facts.run !== 'RUNNING' && !ended) { ended = facts.run; rec.note(`release_review_${facts.run}`); }
    if (facts.record === 'APPROVED') { approved = true; rec.note('approved'); break; }
    if (r.changed.length) await cam.focus('steps', '#panel-steps', { pad: 12, kmax: 1.7 });
    if (ended && ended !== 'SUCCEEDED') break;
  }
  if (!approved) rec.note('not_approved_in_time');
  await cam.hold(1500);
  await cam.focus('record', '#panel-application .app-facts', { pad: 16, kmax: 2.0 }, 'the record reads APPROVED');
  await cam.hold(5000);
  await cam.focus('steps_done', '#panel-steps', { pad: 12, kmax: 1.7 }, 'every step passed');
  await cam.hold(7000);

  // the list again: release_review approved, quality_agent stopped at Scan
  await openPage(page, rec, '/reviews');
  await cam.focus('list_end', '#panel-applications', { pad: 12, kmax: 1.4 }, 'one approved, one stopped at Scan');
  await cam.hold(6000);
}
