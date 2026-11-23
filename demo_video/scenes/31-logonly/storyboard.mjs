// 31-logonly (stage 3): the platform engineer turns the company policy guard_prompt on in log-only mode on the policy
// page: the policy's card (off), the press, the job's lines, the card reading log-only, and the policy rows of the
// agent gateway, one per hosted agent, in log-only mode. Changes the hub (one press). With REHEARSE=1 in the
// environment the take does everything but the press.
import { openPage, press, waitForJob } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';
import { policyRows, PROMPT_CARD } from '../lib/policies.mjs';

export const surfaces = ['hub'];

export default async function storyboard({ page, rec, tap, option }) {
  await needState({ records: { release_review: 'APPROVED', docs_adk: 'APPROVED', quality_agent: 'APPROVED' },
    reviewing: [], mode: null, attached: false, stopped: [] });
  texts(option);
  const cam = kit({ page, rec, option });

  await openPage(page, rec, '/policies');
  await cam.reset('wide', 'the company policies and the custom guardrail');
  await cam.hold(5000);
  await cam.focus('off', PROMPT_CARD, { pad: 16, kmax: 1.9 }, 'guard_prompt is off');
  await cam.hold(6000);
  if (process.env.REHEARSE === '1') { rec.note('rehearsal_no_press'); await cam.hold(2000); return; }

  await press(page, rec, tap, page.locator(`${PROMPT_CARD} button[name=mode][value=log-only]`));
  rec.note('logonly_pressed');
  const frameJob = () => cam.focus('job', '#panel-job', { pad: 16, kmax: 1.8 }, 'the job puts the policy on every agent');
  await frameJob();
  const job = await waitForJob(page, rec, { timeoutMs: 240000, onLines: frameJob });
  rec.note(`job_${job.state}`);
  await cam.focus('job_done', '#panel-job', { pad: 16, kmax: 1.8 }, 'each agent reads LOG_ONLY');
  await cam.hold(7000);
  await cam.focus('logonly', PROMPT_CARD, { pad: 16, kmax: 1.9 }, 'guard_prompt reads log-only');
  await cam.hold(6000);
  await policyRows(page, cam, 'rows', 'guard_prompt_', 'one policy per hosted agent, in log-only mode');
  await cam.hold(6000);
}
