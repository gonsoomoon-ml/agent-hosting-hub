// 52-incident (stage 5), one recording over three surfaces: the developer publishes quality_agent's v2-loop version
// (developer PC); its hosting review on the hub screen in real time until the record reads APPROVED (a note at every
// step: the wait is cut by these notes); then a user asks it about inspection Q-1002 with --timeout 60 and no answer
// comes (the agent keeps asking its tool). Changes the hub: a new version is reviewed and approved, and its loop runs.
// Start 53-alarm as soon as the shot `asked` shows in this take's texts file (a line `== <t> asked` in
// out/raw/52-incident.texts.txt): the alarm comes about a minute after the call.
import { openPage, strip } from '../lib/hub.mjs';
import { command, idle, need, openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['dev', 'hub', 'user'];

const INCIDENT = 'ask quality_agent "What is the result of inspection Q-1002?" --timeout 60';

export default async function storyboard({ page, rec, option, maxSeconds }) {
  await needState({ records: { quality_agent: 'APPROVED', release_review: 'APPROVED', docs_adk: 'APPROVED' },
    reviewing: [], mode: 'ACTIVE', attached: true, stopped: [] });
  const t = texts(option);
  const cam = kit({ page, rec, option });

  // the developer publishes the version that loops
  await openShell(page, rec, 'dev', t, { check: 'test -f dev_team/quality_agent/variants/v2-loop/agent.py' });
  await cam.reset('shell', 'the developer PC');
  await cam.hold(3000);
  await command(page, 'publish quality_agent v2-loop');
  rec.note('publish_loop');
  if (!(await idle(page, t.prompt.dev, 120000))) throw new Error('publish quality_agent v2-loop did not end');
  await need(page, 'is PENDING_APPROVAL', 1000, 'publish quality_agent v2-loop');
  rec.note('loop_pending');
  await cam.rows('submitted', 'publish quality_agent v2-loop', 'PENDING_APPROVAL', { kmax: 1.5 }, 'the new version is submitted');
  await cam.hold(6000);

  // its review, in real time, until the record reads APPROVED
  await openPage(page, rec, '/reviews/quality_agent');
  await cam.focus('steps', '#panel-steps', { pad: 12, kmax: 1.7 }, 'the new version\'s hosting review');
  const seen = {};
  // the end counts only after this review was seen running (the page could first show the earlier, finished one)
  let approved = false, ended = '', running = false;
  while (rec.now() < maxSeconds - 150) {
    await cam.hold(1000);
    const now = await strip(page, '#panel-steps').catch(() => []);
    let changed = false;
    for (const step of now) {
      if (step.state && seen[step.name] !== step.state) { seen[step.name] = step.state; rec.note(`${step.name}_${step.state}`); changed = true; }
    }
    const facts = await page.evaluate(() => ({
      record: document.querySelector('#panel-application .pill')?.textContent.trim() || '',
      run: document.querySelector('#panel-steps .review-meta .pill')?.textContent.trim() || '',
    })).catch(() => ({ record: '', run: '' }));
    if (facts.run === 'RUNNING') running = true;
    if (running && facts.run && facts.run !== 'RUNNING' && !ended) { ended = facts.run; rec.note(`review_${facts.run}`); }
    if (facts.record === 'APPROVED' && ended === 'SUCCEEDED') { approved = true; rec.note('approved'); break; }
    if (changed) await cam.focus('steps', '#panel-steps', { pad: 12, kmax: 1.7 });
    if (ended && ended !== 'SUCCEEDED') break;
  }
  if (!approved) throw new Error(`the review of v2-loop did not end in APPROVED (${ended || 'still running'})`);
  await cam.hold(1500);
  await cam.focus('approved', '#panel-application .app-facts', { pad: 16, kmax: 2.0 }, 'the version that loops is approved');
  await cam.hold(5000);

  // a user asks it about an inspection whose result is still pending: no answer comes
  await openShell(page, rec, 'user', t);
  await cam.reset('user_shell', 'the user\'s shell');
  await cam.hold(3000);
  await command(page, INCIDENT);
  rec.note('incident_asked');
  await cam.rows('asked', 'ask quality_agent', t.prompt.user, { kmax: 1.5 }, 'the user asks about inspection Q-1002');
  if (!(await idle(page, t.prompt.user, 120000))) throw new Error('the incident call did not end');
  await need(page, 'no answer from quality_agent within 60 s', 1000, 'the incident call');
  rec.note('no_answer');
  await cam.rows('no_answer', 'ask quality_agent', t.prompt.user, { kmax: 1.5 }, 'no answer comes');
  await cam.hold(8000);
}
