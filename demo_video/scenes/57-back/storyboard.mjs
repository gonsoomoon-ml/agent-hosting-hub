// 57-back (stage 5), one recording over three surfaces: the developer publishes the fixed quality_agent (developer
// PC); its hosting review passes on the hub screen while the agent is still stopped (real time, a note at every step);
// on the agents page the platform engineer resumes it (one press, the job's lines); a user asks it and it answers.
// Changes the hub: a new version, approved, and the agent resumed. With REHEARSE=1 in the environment the take only
// frames the agents page (no publish, no wait, no press, no call).
import { INSPECTION } from '../lib/guardrail.mjs';
import { openPage, press, waitForJob, waitForReview } from '../lib/hub.mjs';
import { term } from '../lib/plugin.mjs';
import { command, idle, need, openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['dev', 'hub', 'user'];

const ROW = '#agent-quality_agent';

export default async function storyboard({ page, rec, tap, option, maxSeconds }) {
  await needState({ records: { quality_agent: 'APPROVED', release_review: 'APPROVED', docs_adk: 'APPROVED' },
    reviewing: [], stopped: ['quality_agent'] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  const rehearse = process.env.REHEARSE === '1';

  if (!rehearse) {
    // the developer publishes the fixed version (the base agent, without the variant that loops)
    await openShell(page, rec, 'dev', t, { check: '! grep -q "asking again" dev_team/quality_agent/agent.py' });
    await cam.reset('shell', 'the developer PC');
    await cam.hold(3000);
    await command(page, 'publish quality_agent');
    rec.note('publish_fixed');
    if (!(await idle(page, t.prompt.dev, 120000))) throw new Error('publish quality_agent did not end');
    await need(page, 'is PENDING_APPROVAL', 1000, 'publish quality_agent');
    rec.note('fixed_pending');
    await cam.rows('submitted', 'publish quality_agent', 'PENDING_APPROVAL', { kmax: 1.5 }, 'the fixed version is submitted');
    await cam.hold(6000);

    // its review passes while the agent is stopped
    await openPage(page, rec, '/reviews/quality_agent');
    await cam.focus('steps', '#panel-steps', { pad: 12, kmax: 1.7 }, 'the fixed version\'s hosting review');
    const review = await waitForReview(page, rec, cam, { until: maxSeconds - 150 });
    if (!review.approved) {
      throw new Error(`the review of the fixed version did not end in APPROVED (${review.ended || 'still running'})`);
    }
    await cam.hold(1500);
    await cam.focus('approved', '#panel-application .app-facts', { pad: 16, kmax: 2.0 }, 'the fixed version is approved');
    await cam.hold(5000);
    await cam.focus('steps_done', '#panel-steps', { pad: 12, kmax: 1.7 }, 'every step passed while the agent was stopped');
    await cam.hold(6000);
  }

  // the agents page: still stopped; resume
  await openPage(page, rec, '/agents');
  await cam.focus('stopped', '#panel-agents', { pad: 16, kmax: 1.5 }, 'quality_agent is still stopped');
  await cam.hold(5000);
  await cam.focus('row', ROW, { pad: 24, kmax: 1.6 }, 'resume it');
  await cam.hold(3000);
  if (rehearse) { rec.note('rehearsal_no_press'); await cam.hold(2000); return; }

  await press(page, rec, tap, page.locator(`${ROW} form[action$="/resume"] button`));
  rec.note('resume_pressed');
  const frameJob = () => cam.focus('job', '#panel-job', { pad: 16, kmax: 1.8 }, 'the job removes its stop policy');
  await frameJob();
  const job = await waitForJob(page, rec, { timeoutMs: 120000, onLines: frameJob });
  rec.note(`job_${job.state}`);
  await cam.focus('job_done', '#panel-job', { pad: 16, kmax: 1.8 }, 'the job\'s lines');
  await cam.hold(6000);
  await cam.focus('running', '#panel-agents', { pad: 16, kmax: 1.5 }, 'quality_agent runs again');
  await cam.hold(7000);

  // a user asks it again
  await openShell(page, rec, 'user', t);
  await cam.reset('user_shell', 'the user\'s shell');
  await cam.hold(3000);
  await command(page, INSPECTION);
  rec.note('asked');
  if (!(await idle(page, t.prompt.user, 200000))) throw new Error('ask quality_agent did not end');
  const said = (await term.screenText(page)).split('\n').find(r => /^HTTP \d{3} /.test(r.trim())) || '(no status line)';
  if (!said.trim().startsWith('HTTP 200')) throw new Error(`ask quality_agent: ${said.trim()}, not HTTP 200`);
  rec.note('answered');
  await cam.rows('answer', 'ask quality_agent', t.prompt.user, { kmax: 1.4 }, 'quality_agent answers again');
  await cam.hold(9000);
}
