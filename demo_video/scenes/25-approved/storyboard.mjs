// 25-approved (stage 2): the hosting review of quality_agent's fixed version, in real time: every step passes and the
// record reads APPROVED. A note at every change. Record it right after 24-again, with 720 s.
import { openPage, strip } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['hub'];

export default async function storyboard({ page, rec, option, maxSeconds }) {
  const s = await needState({ records: { quality_agent: 'PENDING_APPROVAL', release_review: 'APPROVED' },
    mode: null, attached: false, stopped: [] });
  if (!s.reviewing.includes('quality_agent')) throw new Error('state: the review of quality_agent is not running');
  texts(option);
  const cam = kit({ page, rec, option });
  const seen = {};
  const changes = async scope => {
    const now = await strip(page, scope).catch(() => []);
    const changed = now.filter(step => step.state && seen[step.name] !== step.state);
    for (const step of changed) { seen[step.name] = step.state; rec.note(`quality_agent_${step.name}_${step.state}`); }
    return changed;
  };

  await openPage(page, rec, '/reviews/quality_agent');
  await cam.reset('wide', 'the fixed version under review');
  await changes('#panel-steps');
  await cam.hold(5000);
  await cam.focus('steps', '#panel-steps', { pad: 12, kmax: 1.7 }, 'the seven steps and their AWS services');
  let approved = false, ended = '';
  while (rec.now() < maxSeconds - 40) {
    await cam.hold(1000);
    const changed = await changes('#panel-steps');
    const facts = await page.evaluate(() => ({
      record: document.querySelector('#panel-application .pill')?.textContent.trim() || '',
      run: document.querySelector('#panel-steps .review-meta .pill')?.textContent.trim() || '',
    })).catch(() => ({ record: '', run: '' }));
    if (facts.run && facts.run !== 'RUNNING' && !ended) { ended = facts.run; rec.note(`quality_agent_${facts.run}`); }
    if (facts.record === 'APPROVED') { approved = true; rec.note('approved'); break; }
    if (changed.length) await cam.focus('steps', '#panel-steps', { pad: 12, kmax: 1.7 });
    if (ended && ended !== 'SUCCEEDED') break;
  }
  if (!approved) rec.note('not_approved_in_time');
  await cam.hold(1500);
  await cam.focus('record', '#panel-application .app-facts', { pad: 16, kmax: 2.0 }, 'the record reads APPROVED');
  await cam.hold(5000);
  await cam.focus('steps_done', '#panel-steps', { pad: 12, kmax: 1.7 }, 'every step passed');
  await cam.hold(7000);
}
